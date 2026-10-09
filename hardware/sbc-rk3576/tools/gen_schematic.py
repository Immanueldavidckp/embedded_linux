#!/usr/bin/env python3
"""Emit the hierarchical KiCad 7 schematic from design.py.

Style: every pin carries a global label with its net name (or a no-connect
flag). That keeps machine-generated sheets readable - you can grep a net name
on any sheet - and connectivity is identical to wired schematics. The root
sheet holds one sheet symbol per functional block plus the block diagram text.
"""
import os, uuid, datetime
from sexp import Q, dump, load_lib, flatten_symbol, symbol_pins, find, findall
from design import build, SHEETS

HERE = os.path.dirname(os.path.abspath(__file__))
KICAD = os.path.join(HERE, '..', 'kicad')
SYSLIB = '/usr/share/kicad/symbols'
PROJECT = 'rk3576-sbc'
NS = uuid.UUID('6f1c3c58-8e0b-4f0e-9a51-5b1c7d2e3a10')
PAPERS = [('A4', 297, 210), ('A3', 420, 297), ('A2', 594, 420), ('A1', 841, 594), ('A0', 1189, 841)]
TITLE = 'RK3576 SBC (LPDDR5 / eMMC / NVMe / HDMI 4K)'
REV = 'A0-draft'


def uid(*parts):
    return Q(str(uuid.uuid5(NS, '/'.join(map(str, parts)))))


def snap(v, g=2.54):
    return round(round(v / g) * g, 4)


def font(size=1.27):
    return ['font', ['size', size, size]]


# ------------------------------------------------------------- symbol cache
_sym = {}


def lib_symbol(lib_id):
    if lib_id not in _sym:
        lib, name = lib_id.split(':', 1)
        path = os.path.join(KICAD, 'sbc.kicad_sym') if lib == 'sbc' else os.path.join(SYSLIB, lib + '.kicad_sym')
        s = flatten_symbol(load_lib(path), name)
        s[1] = Q(lib_id)
        _sym[lib_id] = s
    return _sym[lib_id]


def unit_geometry(sym, unit):
    """Pins of a unit (+ common unit 0) and body bbox in symbol coords (y up)."""
    pins = [p for p in symbol_pins(sym) if p[0] in (0, unit)]
    xs, ys = [], []
    for sub in findall(sym, 'symbol'):
        if not (sub[1].endswith(f'_{unit}_1') or sub[1].endswith('_0_1') or sub[1].endswith(f'_{unit}_0')):
            continue
        for g in sub[2:]:
            if not isinstance(g, list):
                continue
            for k in ('start', 'end', 'center', 'at'):
                e = find(g, k)
                if e and g[0] in ('rectangle', 'circle', 'arc', 'polyline'):
                    xs.append(float(e[1]))
                    ys.append(float(e[2]))
            if g[0] == 'polyline':
                pts = find(g, 'pts')
                for xy in findall(pts, 'xy'):
                    xs.append(float(xy[1]))
                    ys.append(float(xy[2]))
    for p in pins:
        xs.append(p[3])
        ys.append(p[4])
    return pins, (min(xs), min(ys), max(xs), max(ys))


def label_len(net):
    return len(net) * 1.05 + 3.5


# ------------------------------------------------------------------ layout
def place(items, width, height, margin=20):
    """Shelf-pack (w, h) boxes; return positions or None if they don't fit."""
    x, y, shelf = margin, margin + 10, 0
    pos = []
    for w, h in items:
        if x + w > width - margin:
            x, y, shelf = margin, y + shelf + 8, 0
        if w > width - 2 * margin or y + h > height - margin - 35:
            return None
        pos.append((x, y))
        x += w + 8
        shelf = max(shelf, h)
    return pos


def build_sheet(sheet, insts, root_uuid, sheet_uuid, page_no, pwr_flags):
    """insts: [(part, unit)]."""
    boxes = []
    for part, unit in insts:
        sym = lib_symbol(part.lib_id)
        pins, (x0, y0, x1, y1) = unit_geometry(sym, unit)
        lmax = rmax = tmax = bmax = 0
        for (_, num, _, px, py, ang, _, _) in pins:
            ln = label_len(part.nets.get(num) or 'NC')
            if ang == 0:
                lmax = max(lmax, ln)
            elif ang == 180:
                rmax = max(rmax, ln)
            elif ang == 90:
                bmax = max(bmax, ln)
            else:
                tmax = max(tmax, ln)
        w = (x1 - x0) + lmax + rmax + 4
        h = (y1 - y0) + tmax + bmax + 10
        boxes.append((part, unit, pins, (x0, y0, x1, y1), (lmax, rmax, tmax, bmax), w, h))
    order = sorted(range(len(boxes)), key=lambda i: (-boxes[i][6], boxes[i][0].ref))
    extra = 60 if pwr_flags else 0
    for paper, pw, ph in PAPERS:
        pos = place([(boxes[i][5], boxes[i][6]) for i in order] + ([(pw - 60, extra)] if pwr_flags else []), pw, ph)
        if pos:
            break
    else:
        raise SystemExit(f'{sheet}: does not fit on A0')

    body = []
    lib_ids = set()
    for k, i in enumerate(order):
        part, unit, pins, (x0, y0, x1, y1), (lm, rm, tm, bm), w, h = boxes[i]
        bx, by = pos[k]
        # symbol origin: body top-left lands at (bx+lm+2, by+tm+5); schematic y = -symbol y
        ox = snap(bx + lm + 2 - x0)
        oy = snap(by + tm + 5 + y1)
        lib_ids.add(part.lib_id)
        sym = ['symbol', ['lib_id', Q(part.lib_id)], ['at', ox, oy, 0], ['unit', unit],
               ['in_bom', 'yes' if part.bom else 'no'], ['on_board', 'yes'], ['dnp', 'yes' if part.dnp else 'no'],
               ['uuid', uid(part.ref, unit)]]
        props = [('Reference', part.ref, ox, snap(oy - y1 - 2.54, 1.27), False),
                 ('Value', part.value, ox, snap(oy - y0 + 2.54, 1.27), False),
                 ('Footprint', part.footprint, ox, oy, True), ('Datasheet', '', ox, oy, True),
                 ('MPN', part.mpn, ox, oy, True), ('Manufacturer', part.mfr, ox, oy, True),
                 ('LCSC', part.lcsc, ox, oy, True), ('Description', part.desc, ox, oy, True)]
        for name, val, px, py, hide in props:
            eff = ['effects', font()]
            if hide:
                eff.append('hide')
            sym.append(['property', Q(name), Q(val), ['at', px, py, 0], eff])
        for p in pins:
            sym.append(['pin', Q(p[1]), ['uuid', uid(part.ref, unit, 'pin', p[1], p[3], p[4])]])
        sym.append(['instances', ['project', Q(PROJECT),
                                  ['path', Q(f'/{root_uuid}/{sheet_uuid}'), ['reference', Q(part.ref)], ['unit', unit]]]])
        body.append(sym)
        for (_, num, pname, px, py, ang, _, etype) in pins:
            sx, sy = round(ox + px, 4), round(oy - py, 4)
            net = part.nets.get(num)
            if net is None:
                body.append(['no_connect', ['at', sx, sy], ['uuid', uid(part.ref, unit, 'nc', num, px, py)]])
                continue
            lang = (ang + 180) % 360
            just = 'left' if lang in (0, 90) else 'right'
            body.append(['global_label', Q(net), ['shape', 'passive'], ['at', sx, sy, lang],
                         ['fields_autoplaced'], ['effects', font(), ['justify', just]],
                         ['uuid', uid(part.ref, unit, 'gl', num, px, py)],
                         ['property', Q('Intersheetrefs'), Q('${INTERSHEET_REFS}'), ['at', sx, sy, 0],
                          ['effects', font(), 'hide']]])

    if pwr_flags:
        lib_ids.add('power:PWR_FLAG')
        fx, fy = pos[-1]
        body.append(['text', Q('ERC power flags: rails generated by PMIC/regulator pins typed passive'),
                     ['at', snap(fx), snap(fy), 0], ['effects', font(1.5), ['justify', 'left', 'bottom']],
                     ['uuid', uid(sheet, 'pfnote')]])
        for k, net in enumerate(pwr_flags):
            cx = snap(fx + 10 + (k % 8) * 40)
            cy = snap(fy + 15 + (k // 8) * 15)
            r = f'#FLG{k + 1:03d}'
            body.append(['symbol', ['lib_id', Q('power:PWR_FLAG')], ['at', cx, cy, 0], ['unit', 1],
                         ['in_bom', 'yes'], ['on_board', 'yes'], ['dnp', 'no'], ['uuid', uid('flag', net)],
                         ['property', Q('Reference'), Q(r), ['at', cx, cy - 5, 0], ['effects', font(), 'hide']],
                         ['property', Q('Value'), Q('PWR_FLAG'), ['at', cx, cy - 3.8, 0], ['effects', font()]],
                         ['property', Q('Footprint'), Q(''), ['at', cx, cy, 0], ['effects', font(), 'hide']],
                         ['property', Q('Datasheet'), Q(''), ['at', cx, cy, 0], ['effects', font(), 'hide']],
                         ['pin', Q('1'), ['uuid', uid('flagpin', net)]],
                         ['instances', ['project', Q(PROJECT), ['path', Q(f'/{root_uuid}/{sheet_uuid}'),
                                                                ['reference', Q(r)], ['unit', 1]]]]])
            body.append(['global_label', Q(net), ['shape', 'passive'], ['at', cx, cy, 270], ['fields_autoplaced'],
                         ['effects', font(), ['justify', 'right']], ['uuid', uid('flaglbl', net)],
                         ['property', Q('Intersheetrefs'), Q('${INTERSHEET_REFS}'), ['at', cx, cy, 0],
                          ['effects', font(), 'hide']]])

    sch = ['kicad_sch', ['version', 20230121], ['generator', 'eeschema'], ['uuid', Q(sheet_uuid)],
           ['paper', Q(paper)],
           ['title_block', ['title', Q(f'{SHEETS[sheet]}')], ['date', Q(datetime.date.today().isoformat())],
            ['rev', Q(REV)], ['company', Q(TITLE)],
            ['comment', 1, Q('Generated by tools/gen_schematic.py from tools/design.py - edit the source, not this file')]],
           ['lib_symbols'] + [lib_symbol(l) for l in sorted(lib_ids)]]
    sch += body
    sch.append(['text', Q(f'{sheet}: {SHEETS[sheet]}'), ['at', 20, 20, 0],
                ['effects', font(3), ['justify', 'left', 'bottom']], ['uuid', uid(sheet, 'title')]])
    return sch, paper


def main():
    d = build()
    root_uuid = str(uuid.uuid5(NS, 'root'))
    # power flags: nets with power_in pins but no power_out pin
    pin_types = {}
    for p in d.parts:
        sym = lib_symbol(p.lib_id)
        for (_, num, _, _, _, _, _, et) in symbol_pins(sym):
            n = p.nets.get(num)
            if n:
                pin_types.setdefault(n, set()).add(et)
    flags = sorted(n for n, t in pin_types.items() if 'power_in' in t and 'power_out' not in t)

    per_sheet = {s: [] for s in SHEETS}
    for p in d.parts:
        sym = lib_symbol(p.lib_id)
        units = sorted({u for (u, *_r) in symbol_pins(sym)} - {0}) or [1]
        for u in units:
            per_sheet[p.unit_sheets.get(u, p.sheet)].append((p, u))

    root_body = []
    y = 40
    for i, sheet in enumerate(SHEETS):
        sheet_uuid = str(uuid.uuid5(NS, 'sheet/' + sheet))
        sch, paper = build_sheet(sheet, per_sheet[sheet], root_uuid, sheet_uuid, i + 2,
                                 flags if sheet == '01_power_input' else [])
        with open(os.path.join(KICAD, f'{sheet}.kicad_sch'), 'w') as f:
            f.write(dump(sch) + '\n')
        col, row = divmod(i, 6)
        sx, sy = 30 + col * 130, 50 + row * 38
        root_body.append(['sheet', ['at', sx, sy], ['size', 100, 25], ['fields_autoplaced'],
                          ['stroke', ['width', 0.1524], ['type', 'solid']], ['fill', ['color', 0, 0, 0, 0.0]],
                          ['uuid', Q(sheet_uuid)],
                          ['property', Q('Sheetname'), Q(sheet), ['at', sx, sy - 0.7, 0],
                           ['effects', font(), ['justify', 'left', 'bottom']]],
                          ['property', Q('Sheetfile'), Q(f'{sheet}.kicad_sch'), ['at', sx, sy + 25.6, 0],
                           ['effects', font(), ['justify', 'left', 'top']]],
                          ['instances', ['project', Q(PROJECT), ['path', Q(f'/{root_uuid}'), ['page', Q(str(i + 2))]]]]])
        root_body.append(['text', Q(SHEETS[sheet]), ['at', sx + 3, sy + 13, 0],
                          ['effects', font(1.8), ['justify', 'left']], ['uuid', uid('roottext', sheet)]])
        print(f'{sheet}: {len(per_sheet[sheet])} symbol units on {paper}')

    block = [
        'BLOCK DIAGRAM',
        'USB-C 5V --fuse/TVS--> VCC5V0_SYS --> RK806S-5 PMIC (10 bucks, 10 LDOs) --> SoC / DDR rails',
        '                                  --> 4x TPS56x buck (2V0, 1V1, VDD2L 0.9V, M.2 3V3)',
        'RK3576 (4xA72 + 4xA53, Mali-G52, 6TOPS NPU)',
        '  DDR PHY (32-bit) <==> LPDDR5 315b x32, 4GB or 8GB (same footprint)',
        '  EMMC (HS400 8-bit)  <==> eMMC 5.1 153b 32/64GB  (boot)',
        '  SDMMC0 (4-bit)      <==> microSD               (recovery boot)',
        '  PCIE0 (2.1 x1)      <==> M.2 M-key 2230/2242 NVMe SSD',
        '  HDMI TX 2.1         <==> HDMI-A  (4K60 TMDS, 4K120 FRL)',
        '  USB2 OTG0           <==> USB-C (maskrom / ADB, shares power port)',
        '  USB3 OTG1 + USB2    <==> USB 3.0 Type-A host',
        '  UART0 (3.3V)        <==> 3-pin debug header, 1500000 8N1',
        f'Notes: ' + ' | '.join(d.notes),
    ]
    for k, line in enumerate(block):
        root_body.append(['text', Q(line[:240]), ['at', 30, 150 + k * 6, 0],
                          ['effects', font(2.0 if k == 0 else 1.6), ['justify', 'left']], ['uuid', uid('block', k)]])
    root = ['kicad_sch', ['version', 20230121], ['generator', 'eeschema'], ['uuid', Q(root_uuid)],
            ['paper', Q('A3')],
            ['title_block', ['title', Q(TITLE)], ['date', Q(datetime.date.today().isoformat())], ['rev', Q(REV)],
             ['company', Q('embedded_linux portfolio')],
             ['comment', 1, Q('Generated - edit tools/design.py and run tools/build.sh')]],
            ['lib_symbols']] + root_body + [['sheet_instances', ['path', Q('/'), ['page', Q('1')]]]]
    with open(os.path.join(KICAD, f'{PROJECT}.kicad_sch'), 'w') as f:
        f.write(dump(root) + '\n')
    print('power flags:', len(flags))


if __name__ == '__main__':
    main()
