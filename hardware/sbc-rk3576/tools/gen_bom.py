#!/usr/bin/env python3
"""BOM + cost roll-up from design.py, plus a JLCPCB-format BOM.

Outputs (../fab/):
  bom.csv            grouped engineering BOM with unit/extended price
  bom_jlcpcb.csv     Comment, Designator, Footprint, LCSC Part #
  cost_summary.md    per-variant cost estimate (4GB/32GB and 8GB/64GB)
Prices are 1k-qty budget estimates, not quotes.
"""
import csv, os, re
from collections import OrderedDict
from design import build

HERE = os.path.dirname(os.path.abspath(__file__))
FAB = os.path.join(HERE, '..', 'fab')

# Upgrades for the high-end variant (same footprints)
VARIANT_8G = {'U601': ('LPDDR5 8GB', 'MT62F2G32D4DS-026 WT:B', 26.00),
              'U701': ('eMMC 64GB', 'FEMDNN064G-A3A55', 8.50)}
# Board-level costs (USD per board @1k, budgetary; JLCPCB/PCBWay style pricing)
PCB_COST = 9.50        # 10L 100x72mm 1.6mm ENIG, via-in-pad (POFV), impedance control
ASSY_COST = 7.50       # double-sided SMT, ~410 placements, BGA X-ray, stencils amortised
TEST_COST = 1.00       # flash + functional test fixture amortised


def natkey(s):
    return [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', s)]


def main():
    os.makedirs(FAB, exist_ok=True)
    d = build()
    groups = OrderedDict()
    for p in sorted(d.parts, key=lambda p: natkey(p.ref)):
        if not p.bom:
            continue
        key = (p.value, p.footprint, p.mpn, p.dnp)
        g = groups.setdefault(key, {'refs': [], 'p': p, 'desc': set()})
        g['refs'].append(p.ref)
        g['desc'].add(p.desc)

    rows, total = [], 0.0
    for (val, fp, mpn, dnp), g in sorted(groups.items(), key=lambda kv: (kv[0][3], natkey(kv[1]['refs'][0]))):
        p = g['p']
        qty = len(g['refs'])
        ext = 0.0 if dnp else qty * p.price
        total += ext
        rows.append([qty, ' '.join(g['refs']), val, fp.split(':')[1], mpn, p.mfr, p.lcsc,
                     f'{p.price:.4f}', f'{ext:.3f}', 'DNP' if dnp else '',
                     p.desc if len(g['desc']) == 1 else 'decoupling / various'])
    with open(os.path.join(FAB, 'bom.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['Qty', 'References', 'Value', 'Footprint', 'MPN', 'Manufacturer', 'LCSC',
                    'Unit USD', 'Ext USD', 'Populate', 'Notes'])
        w.writerows(rows)

    with open(os.path.join(FAB, 'bom_jlcpcb.csv'), 'w', newline='') as f:
        w = csv.writer(f)
        w.writerow(['Comment', 'Designator', 'Footprint', 'LCSC Part #'])
        for (val, fp, mpn, dnp), g in groups.items():
            if not dnp:
                w.writerow([f'{val} {mpn}'.strip(), ','.join(g['refs']), fp.split(':')[1], g['p'].lcsc])

    # cost summary
    by_cat = OrderedDict()
    for p in d.parts:
        if p.dnp or not p.bom:
            continue
        cat = ('SoC' if p.ref == 'U401' else 'Memory (LPDDR5)' if p.ref == 'U601' else
               'Storage (eMMC)' if p.ref == 'U701' else 'PMIC + regulators' if p.sheet[:2] in ('02', '03') and p.ref[0] in 'UL' else
               'Connectors' if p.ref.startswith('J') else 'Passives (R/C/L/FB)' if re.match(r'(R|C|L|FB)\d', p.ref) else
               'Other active / protection / mech')
        by_cat[cat] = by_cat.get(cat, 0) + p.price
    base_parts = sum(by_cat.values())
    up = sum(v[2] for v in VARIANT_8G.values()) - sum(p.price for p in d.parts if p.ref in VARIANT_8G)
    n_place = sum(1 for p in d.parts if not p.dnp and p.bom)
    n_dnp = sum(1 for p in d.parts if p.dnp)
    lines = ['# Cost summary (budgetary, USD @ 1k units, Oct 2026)', '',
             f'{n_place} placed parts, {n_dnp} DNP footprints, {len(groups)} BOM lines.', '',
             '| Category | USD |', '|---|---:|']
    lines += [f'| {k} | {v:.2f} |' for k, v in sorted(by_cat.items(), key=lambda kv: -kv[1])]
    lines += [f'| **Parts total (4GB LPDDR5 / 32GB eMMC)** | **{base_parts:.2f}** |', '',
              '| Build cost per board | 4GB / 32GB | 8GB / 64GB |', '|---|---:|---:|',
              f'| Parts | {base_parts:.2f} | {base_parts + up:.2f} |',
              f'| PCB (10L, ENIG, POFV, impedance) | {PCB_COST:.2f} | {PCB_COST:.2f} |',
              f'| Assembly (2-sided, BGA X-ray) | {ASSY_COST:.2f} | {ASSY_COST:.2f} |',
              f'| Test / flashing | {TEST_COST:.2f} | {TEST_COST:.2f} |',
              f'| **Total** | **{base_parts + PCB_COST + ASSY_COST + TEST_COST:.2f}** | '
              f'**{base_parts + up + PCB_COST + ASSY_COST + TEST_COST:.2f}** |', '',
              'Variant parts (same footprints): ' + '; '.join(f'{r} -> {v[0]} {v[1]}' for r, v in VARIANT_8G.items()),
              '', 'Cost drivers: SoC (~40%) and LPDDR5 (~25-40%). The 10-layer PCB with via-in-pad is the '
              'next biggest line (rev A1 was 8 layers, ~USD 3 cheaper, but could not be fully routed: '
              'LOG.md #31-#33). 1-step HDI (laser microvias) on 8 layers is the alternative at similar cost.',
              '', 'Prototype quantities (5 boards) cost far more per board: expect roughly USD 150-250 each '
              'including PCB/stencil/BGA assembly setup fees.']
    open(os.path.join(FAB, 'cost_summary.md'), 'w').write('\n'.join(lines) + '\n')
    print(f'BOM: {len(groups)} lines, parts {base_parts:.2f} USD (8GB variant +{up:.2f})')


if __name__ == '__main__':
    main()
