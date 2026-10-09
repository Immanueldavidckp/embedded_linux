#!/usr/bin/env python3
"""Routed-length report for the high-speed interfaces -> fab/length_report.md.

Autorouters connect nets; they do not match lengths. This report shows how far
each LPDDR5 byte lane / CA group and each differential pair is from its target,
so the remaining interactive tuning work (KiCad "Tune length") is explicit.
"""
import os, re
from collections import OrderedDict
import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PCB = os.path.join(HERE, '..', 'kicad', 'rk3576-sbc.kicad_pcb')
OUT = os.path.join(HERE, '..', 'fab', 'length_report.md')

# group -> (nets, max spread mm)
DDR_TOL, CA_TOL = 0.5, 1.0
PAIRS = [('LP5_CLK{}_{}', 0.1), ('LP5_WCK0{}_{}', 0.1), ('LP5_WCK1{}_{}', 0.1),
         ('LP5_RDQS0{}_{}', 0.1), ('LP5_RDQS1{}_{}', 0.1)]
OTHER_PAIRS = [('HDMI_TX_D0P', 'HDMI_TX_D0N'), ('HDMI_TX_D1P', 'HDMI_TX_D1N'), ('HDMI_TX_D2P', 'HDMI_TX_D2N'),
               ('HDMI_TX_D3P', 'HDMI_TX_D3N'), ('PCIE0_TXP', 'PCIE0_TXN'), ('PCIE0_RXP', 'PCIE0_RXN'),
               ('PCIE0_REFCLKP', 'PCIE0_REFCLKN'), ('USB3_TXP', 'USB3_TXN'), ('USB3_RXP', 'USB3_RXN'),
               ('USBC_DP', 'USBC_DM'), ('HUB_UP_DP', 'HUB_UP_DM'), ('ETH_MDI0_P', 'ETH_MDI0_N'),
               ('ETH_MDI1_P', 'ETH_MDI1_N'), ('ETH_MDI2_P', 'ETH_MDI2_N'), ('ETH_MDI3_P', 'ETH_MDI3_N')]


def net_lengths(board):
    L = {}
    for t in board.GetTracks():
        if t.GetClass() in ('PCB_TRACK', 'PCB_ARC'):
            n = t.GetNetname()
            L[n] = L.get(n, 0.0) + pcbnew.ToMM(t.GetLength())
    return L


def main():
    b = pcbnew.LoadBoard(PCB)
    L = net_lengths(b)
    c = b.GetConnectivity()
    c.RecalculateRatsnest()
    lines = ['# Routed length report', '',
             f'Unrouted connections: **{c.GetUnconnectedCount(False)}**. Lengths are copper only '
             '(via barrels excluded), measured from the KiCad board.', '']
    bad = 0
    lines += ['## LPDDR5 byte lanes (target: DQ/DMI within ±%.1f mm of the lane mean)' % DDR_TOL, '',
              '| Lane | nets routed | min | max | spread | status |', '|---|---:|---:|---:|---:|---|']
    for ch in 'AB':
        for byte, dqs in ((0, range(0, 8)), (1, range(8, 16))):
            nets = [f'LP5_DQ{i}_{ch}' for i in dqs] + [f'LP5_DMI{byte}_{ch}']
            v = [L[n] for n in nets if n in L]
            if not v:
                lines.append(f'| {ch}{byte} | 0/{len(nets)} | - | - | - | unrouted |')
                bad += 1
                continue
            sp = max(v) - min(v)
            ok = len(v) == len(nets) and sp <= 2 * DDR_TOL
            bad += not ok
            lines.append(f'| {ch}{byte} | {len(v)}/{len(nets)} | {min(v):.2f} | {max(v):.2f} | {sp:.2f} | '
                         f'{"OK" if ok else "TUNE"} |')
        nets = [f'LP5_A{i}_{ch}' for i in range(7)] + [f'LP5_CSN0_{ch}', f'LP5_CSN1_{ch}']
        v = [L[n] for n in nets if n in L]
        sp = (max(v) - min(v)) if v else 0
        ok = len(v) == len(nets) and sp <= 2 * CA_TOL
        bad += not ok
        lines.append(f'| CA_{ch} | {len(v)}/{len(nets)} | {min(v, default=0):.2f} | {max(v, default=0):.2f} | '
                     f'{sp:.2f} | {"OK" if ok else "TUNE"} |')
    lines += ['', '## Differential pairs (intra-pair skew)', '',
              '| Pair | P mm | N mm | skew | limit | status |', '|---|---:|---:|---:|---:|---|']
    pairs = []
    for pat, tol in PAIRS:
        for ch in 'AB':
            pairs.append((pat.format('P', ch), pat.format('N', ch), tol))
    pairs += [(p, n, 0.15) for p, n in OTHER_PAIRS]
    for p, n, tol in pairs:
        lp, ln = L.get(p), L.get(n)
        if lp is None or ln is None:
            lines.append(f'| {p[:-1] if p.endswith("P") else p} | {lp or 0:.2f} | {ln or 0:.2f} | - | {tol} | unrouted |')
            bad += 1
            continue
        sk = abs(lp - ln)
        ok = sk <= tol
        bad += not ok
        lines.append(f'| {p} / {n} | {lp:.2f} | {ln:.2f} | {sk:.2f} | {tol} | {"OK" if ok else "TUNE"} |')
    lines += ['', f'**{bad} groups need tuning.** Use KiCad PCB editor → Route → Tune length / skew on each '
              'TUNE row, then re-run `tools/length_report.py`.']
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, 'w').write('\n'.join(lines) + '\n')
    print(f'wrote {OUT}: {bad} groups need tuning')


if __name__ == '__main__':
    main()
