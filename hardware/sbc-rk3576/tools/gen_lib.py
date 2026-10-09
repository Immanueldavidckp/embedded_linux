#!/usr/bin/env python3
"""Generate the project symbol library (sbc.kicad_sym) and footprint library
(sbc.pretty/) for the parts KiCad's stock libraries don't have.

Pin data comes from ../data/*.csv (see extract_ref_pins.py / parse_rk3576_pins.py).
"""
import csv, os, re
from sexp import Q, dump

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.join(HERE, '..')
DATA = os.path.join(ROOT, 'data')
KICAD = os.path.join(ROOT, 'kicad')

G = 2.54          # schematic grid
MAX_SIDE = 64     # max pins per symbol side before a unit is split


def read_pins(name):
    return [(r['ball'], r['name']) for r in csv.DictReader(open(os.path.join(DATA, name)))]


def natkey(s):
    return [int(t) if t.isdigit() else t for t in re.split(r'(\d+)', s)]


# --------------------------------------------------------------- RK3576 model
GND_RE = re.compile(r'^(VSS|AVSS|AVSS1|TVSS|PLL_AVSS|DDRPHY_PLL_AVSS)(_\d+)?$')
PWR_RE = re.compile(r'(VDD|VCC|AVDD|DVDD)')
GPIO_RE = re.compile(r'GPIO(\d)_([A-D]\d)_[udz]')


def rk3576_pin_class(name):
    parts = name.split('/')
    if any(p.startswith(('LP5_', 'LP4_')) for p in parts) or name in ('ZQ_A', 'ZQ_B'):
        return 'DDR'
    if GND_RE.match(name):
        return 'GND'
    m = GPIO_RE.search(name)
    if m:
        return f'GPIO{m.group(1)}'
    if PWR_RE.search(name) and '/' not in name:
        return 'PWR'
    return 'SYS'


def rk3576_short(name):
    """Readable pin name: LP5 function for DDR, GPIOx_yN/<first function> for IO."""
    parts = name.split('/')
    lp5 = [p for p in parts if p.startswith('LP5_')]
    if lp5:
        return lp5[0]
    if parts[0].startswith('LP4_'):
        return parts[0]
    m = GPIO_RE.search(name)
    if m:
        g = f'GPIO{m.group(1)}_{m.group(2)}'
        first = parts[0]
        return g if first.startswith('GPIO') else f'{g}/{first}'
    return parts[0] if len(parts[0]) <= 28 else parts[0][:28]


def rk3576_units():
    pins = read_pins('rk3576_pins.csv')
    groups = {}
    for ball, name in pins:
        groups.setdefault(rk3576_pin_class(name), []).append((ball, rk3576_short(name), name))
    units = []

    # DDR: channel A left, channel B right
    ddr = groups.pop('DDR')
    a = sorted([p for p in ddr if not p[1].endswith('_B')], key=lambda p: natkey(p[1]))
    b = sorted([p for p in ddr if p[1].endswith('_B')], key=lambda p: natkey(p[1]))
    units.append(('DDR', [(p[0], p[1], 'bidirectional') for p in a],
                  [(p[0], p[1], 'bidirectional') for p in b]))

    sys_ = sorted(groups.pop('SYS'), key=lambda p: natkey(p[1]))
    half = (len(sys_) + 1) // 2
    units.append(('SYS', [(p[0], p[1], 'passive') for p in sys_[:half]],
                  [(p[0], p[1], 'passive') for p in sys_[half:]]))

    for bank in sorted(k for k in groups if k.startswith('GPIO')):
        io = sorted(groups.pop(bank), key=lambda p: natkey(p[1]))
        for i in range(0, len(io), 2 * MAX_SIDE):
            chunk = io[i:i + 2 * MAX_SIDE]
            h = (len(chunk) + 1) // 2
            units.append((bank, [(p[0], p[1], 'bidirectional') for p in chunk[:h]],
                          [(p[0], p[1], 'bidirectional') for p in chunk[h:]]))

    pwr = sorted(groups.pop('PWR'), key=lambda p: natkey(p[1]))
    h = (len(pwr) + 1) // 2
    units.append(('PWR', [(p[0], p[1], 'power_in') for p in pwr[:h]],
                  [(p[0], p[1], 'power_in') for p in pwr[h:]]))

    gnd = sorted(groups.pop('GND'), key=lambda p: natkey(p[1]))
    for i in range(0, len(gnd), 2 * MAX_SIDE):
        chunk = gnd[i:i + 2 * MAX_SIDE]
        h = (len(chunk) + 1) // 2
        units.append(('GND', [(p[0], p[1], 'power_in') for p in chunk[:h]],
                      [(p[0], p[1], 'power_in') for p in chunk[h:]]))
    assert not groups, groups
    return units


# ------------------------------------------------------------- symbol builder
def _pin(etype, x, y, ang, number, name, hidden=False):
    p = ['pin', etype, 'line', ['at', x, y, ang], ['length', G],
         ['name', Q(name), ['effects', ['font', ['size', 1.016, 1.016]]]],
         ['number', Q(number), ['effects', ['font', ['size', 1.016, 1.016]]]]]
    if hidden:
        p.insert(3, 'hide')
    return p


def make_symbol(name, ref, units, footprint='', datasheet='', desc='', value=None):
    """units: [(unit_label, left_pins, right_pins)]; pin = (number, name, etype)."""
    out = ['symbol', Q(name), ['pin_names', ['offset', 0.762]], ['in_bom', 'yes'], ['on_board', 'yes']]
    tallest = max(max(len(l), len(r)) for _, l, r in units)
    props = [('Reference', ref, 0), ('Value', value or name, 0),
             ('Footprint', footprint, 1), ('Datasheet', datasheet, 1), ('Description', desc, 1)]
    for i, (k, v, hide) in enumerate(props):
        eff = ['effects', ['font', ['size', 1.27, 1.27]]]
        if hide:
            eff.append('hide')
        y = (tallest / 2 + 2 + i) * G if i < 2 else 0
        out.append(['property', Q(k), Q(v), ['at', 0, y, 0], eff])
    for ui, (label, left, right) in enumerate(units, 1):
        n = max(len(left), len(right), 1)
        lw = max([len(p[1]) for p in left] + [4])
        rw = max([len(p[1]) for p in right] + [4])
        w = (lw + rw) * 1.016 * 0.75 + 4 * G
        w = G * round(w / G / 2) * 2                     # keep pins on grid
        top = G * ((n - 1) // 2 + 1)
        body = ['symbol', Q(f'{name}_{ui}_1'),
                ['rectangle', ['start', -w / 2, top], ['end', w / 2, top - (n + 1) * G],
                 ['stroke', ['width', 0.254], ['type', 'default']], ['fill', ['type', 'background']]],
                ['text', Q(label), ['at', 0, top - (n + 1) * G - 1.27, 0],
                 ['effects', ['font', ['size', 1.27, 1.27]]]]]
        for side, plist in ((0, left), (1, right)):
            for i, (num, pname, et) in enumerate(plist):
                y = top - (i + 1) * G
                if side == 0:
                    body.append(_pin(et, -w / 2 - G, y, 0, num, pname))
                else:
                    body.append(_pin(et, w / 2 + G, y, 180, num, pname))
        out.append(body)
    return out


def lpddr5_units():
    pins = read_pins('lpddr5_315b_pins.csv')
    sig = [(b, n) for b, n in pins if not re.match(r'(VSS|VDD|NC_|RFU)', n)]
    a = sorted([p for p in sig if not p[1].endswith('_B')], key=lambda p: natkey(p[1]))
    b = sorted([p for p in sig if p[1].endswith('_B')], key=lambda p: natkey(p[1]))
    nm = lambda n: n.replace('RESET*', 'RESET_N')
    u1 = ('SIGNALS', [(p[0], nm(p[1]), 'bidirectional') for p in a],
          [(p[0], nm(p[1]), 'bidirectional') for p in b])
    vdd = sorted([(b, n) for b, n in pins if n.startswith('VDD')], key=lambda p: natkey(p[1]))
    v2h = [p for p in vdd if p[1].startswith('VDD2H')]
    oth = [p for p in vdd if not p[1].startswith('VDD2H')]
    u2 = ('POWER', [(p[0], p[1], 'power_in') for p in v2h], [(p[0], p[1], 'power_in') for p in oth])
    vss = sorted([(b, n) for b, n in pins if n.startswith('VSS')], key=lambda p: natkey(p[1]))
    h = (len(vss) + 1) // 2
    u3 = ('GND', [(p[0], p[1], 'power_in') for p in vss[:h]], [(p[0], p[1], 'power_in') for p in vss[h:]])
    return [u1, u2, u3]


def emmc_units():
    pins = [(b, n) for b, n in read_pins('emmc_153b_pins.csv') if n not in ('NC', 'RFU')]
    cnt = {}
    named = []
    for b, n in sorted(pins, key=lambda p: natkey(p[1])):
        cnt[n] = cnt.get(n, 0) + 1
        named.append((b, n))
    sig = [p for p in named if not p[1].startswith(('VCC', 'VSS', 'VDDI'))]
    pwr = [p for p in named if p[1].startswith(('VCC', 'VSS', 'VDDI'))]
    return [('eMMC', [(b, n, 'bidirectional' if n.startswith('DAT') or n == 'CMD' else 'input')
                      for b, n in sig],
             [(b, n, 'power_in' if n != 'VDDI' else 'passive') for b, n in pwr])]


def rk806_units():
    pins = {int(b): n for b, n in read_pins('rk806_pins.csv')}
    buck_in = sorted([(str(k), v) for k, v in pins.items() if re.fullmatch(r'VCC([1-9]|10)(_\d)?', v)],
                     key=lambda p: natkey(p[1]))
    buck_out = sorted([(str(k), v) for k, v in pins.items() if re.match(r'(SW|VOUT|FB)\d', v)],
                      key=lambda p: (int(re.search(r'\d+', p[1]).group()), p[1]))
    u1 = ('BUCK', [(n, v, 'power_in') for n, v in buck_in], [(n, v, 'passive') for n, v in buck_out])
    ctrl = sorted([(str(k), v) for k, v in pins.items()
                   if (str(k), v) not in buck_in and (str(k), v) not in buck_out
                   and not re.match(r'[PN]LDO', v)], key=lambda p: natkey(p[1]))
    ldo = sorted([(str(k), v) for k, v in pins.items() if re.match(r'[PN]LDO', v)], key=lambda p: natkey(p[1]))
    et = lambda v: ('power_in' if v.startswith(('VCC', 'EPAD', 'VDC'))
                    else 'input' if v in ('CS', 'PWRON', 'SCL', 'PWRCTRL1', 'PWRCTRL2', 'PWRCTRL3') else 'bidirectional')
    u2 = ('LDO / CTRL', [(n, v, et(v)) for n, v in ctrl], [(n, v, 'passive') for n, v in ldo])
    return [u1, u2]


M2_PINS = {
    1: 'GND', 2: '3V3', 3: 'GND', 4: '3V3', 5: 'PERn3', 7: 'PERp3', 9: 'GND', 10: 'LED1#',
    11: 'PETn3', 12: '3V3', 13: 'PETp3', 14: '3V3', 15: 'GND', 16: '3V3', 17: 'PERn2', 18: '3V3',
    19: 'PERp2', 21: 'GND', 23: 'PETn2', 25: 'PETp2', 27: 'GND', 29: 'PERn1', 31: 'PERp1',
    33: 'GND', 35: 'PETn1', 37: 'PETp1', 38: 'DEVSLP', 39: 'GND', 40: 'SMB_CLK', 41: 'PERn0',
    42: 'SMB_DATA', 43: 'PERp0', 44: 'ALERT#', 45: 'GND', 47: 'PETn0', 49: 'PETp0', 50: 'PERST#',
    51: 'GND', 52: 'CLKREQ#', 53: 'REFCLKn', 54: 'PEWAKE#', 55: 'REFCLKp', 57: 'GND',
    68: 'SUSCLK', 69: 'PEDET', 70: '3V3', 71: 'GND', 72: '3V3', 73: 'GND', 74: '3V3', 75: 'GND',
}
for _n in list(range(1, 59)) + list(range(67, 76)):
    M2_PINS.setdefault(_n, 'NC')


def m2_units():
    pw = [(str(k), v, 'power_in') for k, v in sorted(M2_PINS.items()) if v in ('GND', '3V3')]
    sg = [(str(k), v, 'no_connect' if v == 'NC' else 'passive')
          for k, v in sorted(M2_PINS.items()) if v not in ('GND', '3V3')]
    return [('M.2 M-KEY', pw, sg)]


# ---------------------------------------------------------- footprint builder
ROWS = [r for r in ['A', 'B', 'C', 'D', 'E', 'F', 'G', 'H', 'J', 'K', 'L', 'M', 'N', 'P', 'R', 'T',
                    'U', 'V', 'W', 'Y', 'AA', 'AB', 'AC', 'AD', 'AE', 'AF', 'AG', 'AH', 'AJ', 'AK', 'AL']]


def fp_header(name, desc, smd=True):
    return ['footprint', Q(name), ['version', 20221018], ['generator', 'pcbnew'], ['layer', Q('F.Cu')],
            ['descr', Q(desc)], ['attr', 'smd' if smd else 'through_hole']]


def fp_text(kind, text, x, y, layer, hide=False):
    t = ['fp_text', kind, Q(text), ['at', x, y], ['layer', Q(layer)],
         ['effects', ['font', ['size', 1, 1], ['thickness', 0.15]]]]
    if hide:
        t.insert(5, 'hide')
    return t


def fp_rect(x1, y1, x2, y2, layer, w):
    return ['fp_rect', ['start', x1, y1], ['end', x2, y2], ['stroke', ['width', w], ['type', 'solid']],
            ['fill', 'none'], ['layer', Q(layer)]]


def fp_line(x1, y1, x2, y2, layer, w):
    return ['fp_line', ['start', x1, y1], ['end', x2, y2], ['stroke', ['width', w], ['type', 'solid']],
            ['layer', Q(layer)]]


def outline(fp, bw, bh, pin1=True, court=0.5):
    fp.append(fp_rect(-bw / 2, -bh / 2, bw / 2, bh / 2, 'F.Fab', 0.1))
    s = 0.1
    fp.append(fp_rect(-bw / 2 - s, -bh / 2 - s, bw / 2 + s, bh / 2 + s, 'F.SilkS', 0.12))
    fp.append(fp_rect(-bw / 2 - court, -bh / 2 - court, bw / 2 + court, bh / 2 + court, 'F.CrtYd', 0.05))
    if pin1:
        fp.append(['fp_circle', ['center', -bw / 2 - 0.6, -bh / 2 - 0.6], ['end', -bw / 2 - 0.4, -bh / 2 - 0.6],
                   ['stroke', ['width', 0.2], ['type', 'solid']], ['fill', 'solid'], ['layer', Q('F.SilkS')]])


def bga_pad(name, x, y, d):
    return ['pad', Q(name), 'smd', 'circle', ['at', round(x, 4), round(y, 4)], ['size', d, d],
            ['layers', Q('F.Cu'), Q('F.Paste'), Q('F.Mask')]]


def bga_grid_fp(name, desc, balls, px, py, ncol, nrow, bw, bh, pad):
    """balls: iterable of 'A1'-style ids on a ROWS x 1..ncol grid."""
    fp = fp_header(name, desc)
    fp += [fp_text('reference', 'REF**', 0, -bh / 2 - 1.5, 'F.SilkS'),
           fp_text('value', name, 0, bh / 2 + 1.5, 'F.Fab')]
    outline(fp, bw, bh)
    for b in balls:
        m = re.fullmatch(r'([A-Z]+)(\d+)', b)
        r, c = ROWS.index(m.group(1)), int(m.group(2)) - 1
        assert r < nrow and c < ncol, b
        fp.append(bga_pad(b, (c - (ncol - 1) / 2) * px, (r - (nrow - 1) / 2) * py, pad))
    return fp


def rk3576_fp():
    balls = sorted((b for b, _ in read_pins('rk3576_pins.csv')), key=natkey)
    ncol, nrow, p = 27, 26, 0.55
    fp = fp_header('RK3576_FCCSP-698_16.1x17.2mm_PLACEHOLDER',
                   'PLACEHOLDER land pattern: 698 pads on a uniform 0.55mm grid, ordered by ball name. '
                   'The real FCCSP698L uses mixed 0.55/0.60/0.65mm pitch; replace with the Rockchip '
                   'RK3576 land pattern from the Rockchip hardware design kit before fabrication.')
    bw, bh = 16.1, 17.2
    fp += [fp_text('reference', 'REF**', 0, -bh / 2 - 1.5, 'F.SilkS'),
           fp_text('value', 'RK3576', 0, bh / 2 + 1.5, 'F.Fab'),
           fp_text('user', 'PLACEHOLDER - USE ROCKCHIP LAND PATTERN', 0, 0, 'Cmts.User')]
    outline(fp, bw, bh)
    for i, b in enumerate(balls):
        r, c = divmod(i, ncol)
        fp.append(bga_pad(b, (c - (ncol - 1) / 2) * p, (r - (nrow - 1) / 2) * p, 0.25))
    return fp


def m2_socket_fp():
    """M.2 Socket 3 (M key), 0.5mm pitch per row, rows staggered by 0.25mm.
    Generic H=4.2mm top-mount footprint; verify against the chosen connector
    (e.g. LOTES APCI0076 / Amphenol MDT420M01001) before release."""
    fp = fp_header('M.2_Socket3_M-Key_H4.2mm', 'M.2 Socket 3 M-key (NVMe), 67 contacts, 0.5mm pitch. '
                   'Generic land pattern - verify against selected connector datasheet.')
    fp += [fp_text('reference', 'REF**', 0, -4.5, 'F.SilkS'), fp_text('value', 'M.2_M_KEY', 0, 4.5, 'F.Fab')]
    x0 = -(75 - 1) * 0.25 / 2
    for n in M2_PINS:
        x = x0 + (n - 1) * 0.25
        y = -1.35 if n % 2 else 1.35        # odd row / even row
        fp.append(['pad', Q(str(n)), 'smd', 'rect', ['at', round(x, 3), y], ['size', 0.3, 1.2],
                   ['layers', Q('F.Cu'), Q('F.Paste'), Q('F.Mask')]])
    for sx in (-1, 1):                       # hold-down tabs
        fp.append(['pad', Q('MP'), 'smd', 'rect', ['at', sx * 11.6, 0], ['size', 1.4, 2.6],
                   ['layers', Q('F.Cu'), Q('F.Paste'), Q('F.Mask')]])
    fp.append(fp_rect(-11.0, -2.6, 11.0, 2.6, 'F.Fab', 0.1))
    fp.append(fp_rect(-12.6, -3.2, 12.6, 3.2, 'F.CrtYd', 0.05))
    fp.append(fp_line(-11.0, -2.7, -9.6, -2.7, 'F.SilkS', 0.12))
    # key notch between pins 59-66
    kx = x0 + (62.5 - 1) * 0.25
    fp.append(fp_line(kx, -2.5, kx, 2.5, 'F.Fab', 0.1))
    return fp


def smd_standoff_fp():
    fp = fp_header('SMD_Standoff_M2_D4.0mm', 'SMD threaded standoff for M.2 card retention '
                   '(Wurth 9774020243R / PEM SMTSO-M2). Solder pad only, no drill.')
    fp += [fp_text('reference', 'REF**', 0, -3.2, 'F.SilkS'), fp_text('value', 'M2 standoff', 0, 3.2, 'F.Fab')]
    fp.append(['pad', Q('1'), 'smd', 'circle', ['at', 0, 0], ['size', 4.0, 4.0],
               ['layers', Q('F.Cu'), Q('F.Paste'), Q('F.Mask')]])
    fp.append(['fp_circle', ['center', 0, 0], ['end', 2.5, 0], ['stroke', ['width', 0.05], ['type', 'solid']],
               ['fill', 'none'], ['layer', Q('F.CrtYd')]])
    return fp


# Verified third-party land patterns (LCSC/EasyEDA via easyeda2kicad), kept in
# data/lcsc_footprints for provenance. Pad names were checked against the
# datasheets: RK3576 = all 698 ball IDs of the datasheet pin list.
LCSC_FP = {
    'FCCSP-698_L17.2-W16.1-TL_RK3576': 'RK3576_FCCSP-698_16.1x17.2mm',      # LCSC C42388007
    'WQFN-40_L5.0-W5.0-P0.4-BL-EP': 'WQFN-40-1EP_5x5mm_P0.4mm',             # RTL8211F-CG C187932
    'SSOP-28_L9.9-W3.9-P0.635-LS6.0-BL-1': 'SSOP-28_3.9x9.9mm_P0.635mm',    # FE1.1S C9359
    'RJ45-TH_HR911130C': 'RJ45_Hanrun_HR911130C_MagJack',                    # HR911130C C50933
    'WIFIM-SMD_22P-L13.0-W12.2-P1.27': 'WiFi_Module_22P_13.0x12.2mm_P1.27mm',  # BL-M8x2xU1 family
}


def copy_lcsc_footprints(pretty):
    from sexp import parse, find, findall
    src = os.path.join(DATA, 'lcsc_footprints')
    for old, new in LCSC_FP.items():
        tree = parse(open(os.path.join(src, old + '.kicad_mod')).read())
        tree[1] = Q(new)
        # drop vendor 3D model paths that only exist on the original PC, and the
        # body-only EasyEDA courtyard (it does not cover the pads)
        tree[:] = [c for c in tree if not (isinstance(c, list) and c and (
            c[0] == 'model' or (c[0] in ('fp_line', 'fp_rect', 'fp_circle', 'fp_arc')
                                and find(c, 'layer') and find(c, 'layer')[1] == 'F.CrtYd')))]
        xs, ys = [], []
        for pad in findall(tree, 'pad'):
            at, size = find(pad, 'at'), find(pad, 'size')
            x, y, w, h = float(at[1]), float(at[2]), float(size[1]), float(size[2])
            if len(at) > 3 and int(float(at[3])) % 180 == 90:
                w, h = h, w
            xs += [x - w / 2, x + w / 2]
            ys += [y - h / 2, y + h / 2]
            # mechanical pegs: unnamed plated holes with zero annular ring -> NPTH
            drill = find(pad, 'drill')
            if pad[1] == '' and pad[2] == 'thru_hole' and drill and float(drill[1]) >= w - 1e-6:
                pad[2] = 'np_thru_hole'
                pad[pad.index(find(pad, 'layers'))] = ['layers', Q('*.Cu'), Q('*.Mask')]
        for g in tree:
            if isinstance(g, list) and g and g[0] in ('fp_line', 'fp_rect') and find(g, 'layer') \
                    and find(g, 'layer')[1] in ('F.Fab', 'F.SilkS'):
                for k in ('start', 'end'):
                    e = find(g, k)
                    xs.append(float(e[1]))
                    ys.append(float(e[2]))
        m = 0.25
        tree.append(fp_rect(min(xs) - m, min(ys) - m, max(xs) + m, max(ys) + m, 'F.CrtYd', 0.05))
        with open(os.path.join(pretty, new + '.kicad_mod'), 'w') as f:
            f.write(dump(tree) + '\n')


def write_fp(fp, libdir):
    with open(os.path.join(libdir, fp[1] + '.kicad_mod'), 'w') as f:
        f.write(dump(fp) + '\n')


def main():
    os.makedirs(KICAD, exist_ok=True)
    pretty = os.path.join(KICAD, 'sbc.pretty')
    os.makedirs(pretty, exist_ok=True)

    lp5_balls = [b for b, _ in read_pins('lpddr5_315b_pins.csv')]
    emmc_balls = [b for b, _ in read_pins('emmc_153b_pins.csv')]
    copy_lcsc_footprints(pretty)
    stale = os.path.join(pretty, 'RK3576_FCCSP-698_16.1x17.2mm_PLACEHOLDER.kicad_mod')
    if os.path.exists(stale):
        os.remove(stale)
    fps = [
        bga_grid_fp('LPDDR5_FBGA-315_12.4x15.0mm_P0.8x0.7mm', 'LPDDR5/5X x32 315-ball FBGA (JEDEC), '
                    '15 cols @0.8mm x 21 rows @0.7mm, NSMD 0.35mm pads', lp5_balls, 0.8, 0.7, 15, 21,
                    12.4, 15.0, 0.35),
        bga_grid_fp('eMMC_FBGA-153_11.5x13.0mm_P0.5mm', 'eMMC 5.1 153-ball FBGA (JEDEC JESD84-B51), '
                    '14x14 @0.5mm, NSMD 0.28mm pads', emmc_balls, 0.5, 0.5, 14, 14, 11.5, 13.0, 0.28),
        m2_socket_fp(),
        smd_standoff_fp(),
    ]
    for fp in fps:
        write_fp(fp, pretty)

    syms = [
        make_symbol('RK3576', 'U', [(f'RK3576 {lbl}', l, r) for lbl, l, r in rk3576_units()],
                    'sbc:RK3576_FCCSP-698_16.1x17.2mm',
                    'https://www.rock-chips.com/uploads/pdf/2024.3.18/192/RK3576%20Brief%20Datasheet.pdf',
                    'Rockchip RK3576 octa-core (4xA72 + 4xA53) SoC, FCCSP698L'),
        make_symbol('LPDDR5_x32_315b', 'U', [(f'LPDDR5 {l}', a, b) for l, a, b in lpddr5_units()],
                    'sbc:LPDDR5_FBGA-315_12.4x15.0mm_P0.8x0.7mm', '',
                    'LPDDR5/5X x32 dual-channel SDRAM, 315-ball FBGA'),
        make_symbol('eMMC_5.1_153b', 'U', emmc_units(), 'sbc:eMMC_FBGA-153_11.5x13.0mm_P0.5mm', '',
                    'eMMC 5.1 HS400, 153-ball FBGA'),
        make_symbol('RK806S-5', 'U', [(f'RK806 {l}', a, b) for l, a, b in rk806_units()],
                    'Package_DFN_QFN:QFN-68-1EP_8x8mm_P0.4mm_EP5.2x5.2mm_ThermalVias', '',
                    'Rockchip RK806S-5 PMIC: 10 bucks, 5 PLDO, 5 NLDO'),
        make_symbol('M.2_M_Key', 'J', m2_units(), 'sbc:M.2_Socket3_M-Key_H4.2mm', '',
                    'M.2 Socket 3, M key (PCIe NVMe SSD)'),
    ]
    P, B, I, O = 'passive', 'bidirectional', 'input', 'output'
    W = 'power_in'
    rtl = {1: 'MDI0+', 2: 'MDI0-', 3: 'AVDD10', 4: 'MDI1+', 5: 'MDI1-', 6: 'MDI2+', 7: 'MDI2-', 8: 'AVDD10',
           9: 'MDI3+', 10: 'MDI3-', 11: 'AVDD33', 12: 'PHYRSTB', 13: 'MDC', 14: 'MDIO', 15: 'TXD3', 16: 'TXD2',
           17: 'TXD1', 18: 'TXD0', 19: 'TXCTL', 20: 'TXC', 21: 'DVDD10', 22: 'RXD3/PHYAD0', 23: 'RXD2/PLLOFF',
           24: 'RXD1/TXDLY', 25: 'RXD0/RXDLY', 26: 'RXCTL/PHYAD2', 27: 'RXC/PHYAD1', 28: 'DVDD_RG',
           29: 'DVDD33', 30: 'REG_OUT', 31: 'INTB/PMEB', 32: 'LED0/CFG_EXT', 33: 'LED1/CFG_LDO0',
           34: 'LED2/CFG_LDO1', 35: 'CLKOUT', 36: 'XTAL_IN', 37: 'XTAL_OUT', 38: 'AVDD10', 39: 'RSET',
           40: 'AVDD33', 41: 'EPAD'}
    rtl_pw = {3, 8, 11, 21, 28, 29, 38, 40, 41}
    rtl_l = [(str(n), v, W) for n, v in rtl.items() if n in rtl_pw] + \
            [(str(n), v, P) for n, v in rtl.items() if n in range(12, 21)]
    rtl_r = [(str(n), v, P) for n, v in rtl.items() if n not in rtl_pw and n not in range(12, 21)]
    # FE1.1s SSOP-28 per Terminus datasheet Rev 1.0 (LCSC symbol mislabels 12/13/28 as NC)
    fe = {1: 'VSS', 2: 'XOUT', 3: 'XIN', 4: 'DM4', 5: 'DP4', 6: 'DM3', 7: 'DP3', 8: 'DM2', 9: 'DP2',
          10: 'DM1', 11: 'DP1', 12: 'VD18_O', 13: 'VD33', 14: 'REXT', 15: 'DMU', 16: 'DPU', 17: 'XRSTJ',
          18: 'VBUSM', 19: 'BUSJ', 20: 'VDD5', 21: 'VD33_O', 22: 'DRV', 23: 'LED1', 24: 'LED2',
          25: 'PWRJ', 26: 'OVCJ', 27: 'TESTJ', 28: 'VD18'}
    fe_l = [(str(n), fe[n], W if n in (1, 13, 20, 28) else P) for n in (20, 13, 28, 1, 21, 12, 15, 16, 17, 18, 19, 14, 2, 3)]
    fe_r = [(str(n), fe[n], P) for n in (10, 11, 8, 9, 6, 7, 4, 5, 22, 23, 24, 25, 26, 27)]
    wifi = {1: 'GND', 2: 'RF', 3: 'NC', 4: 'GND', 5: 'PCM_IN', 6: 'PCM_OUT', 7: 'PCM_SYNC', 8: 'PCM_CLK',
            9: 'BT_WAKE_HOST', 10: 'HOST_WAKE_BT', 11: 'VDD33', 12: 'USB_DM', 13: 'USB_DP', 14: 'GND',
            15: 'GPIO/PCM', 16: '~{WL_DIS}', 17: '~{BT_DIS}', 18: 'CHIP_EN', 19: 'HOST_WAKE_WL',
            20: 'WL_WAKE_HOST', 21: 'WPS', 22: 'LED'}
    wf_l = [(str(n), wifi[n], W if n in (1, 4, 11, 14) else P) for n in (11, 1, 4, 14, 2, 3, 12, 13, 16, 17, 18)]
    wf_r = [(str(n), wifi[n], P) for n in (5, 6, 7, 8, 9, 10, 15, 19, 20, 21, 22)]
    rj = [('P2', 'MDI0+'), ('P3', 'MDI0-'), ('P4', 'MDI1+'), ('P7', 'MDI1-'), ('P5', 'MDI2+'),
          ('P6', 'MDI2-'), ('P8', 'MDI3+'), ('P9', 'MDI3-'), ('P1', 'CT_A'), ('P10', 'CT_B')]
    rj_r = [('11', 'LED_G_A'), ('12', 'LED_G_K'), ('13', 'LED_Y_A'), ('14', 'LED_Y_K'),
            ('SHIELD0', 'SHIELD'), ('SHIELD1', 'SHIELD')]
    syms += [
        make_symbol('RTL8211F-CG', 'U', [('RTL8211F', rtl_l, rtl_r)], 'sbc:WQFN-40-1EP_5x5mm_P0.4mm', '',
                    'Realtek RGMII Gigabit Ethernet PHY'),
        make_symbol('FE1.1s', 'U', [('FE1.1s', fe_l, fe_r)], 'sbc:SSOP-28_3.9x9.9mm_P0.635mm', '',
                    'Terminus USB 2.0 4-port hub'),
        make_symbol('BL-M8821CU1', 'U', [('WiFi5+BT4.2 USB', wf_l, wf_r)],
                    'sbc:WiFi_Module_22P_13.0x12.2mm_P1.27mm', '',
                    'LB-Link RTL8821CU dual-band Wi-Fi 5 + BT 4.2 USB module'),
        make_symbol('HR911130C', 'J', [('RJ45 GbE', [(n, v, P) for n, v in rj], [(n, v, P) for n, v in rj_r])],
                    'sbc:RJ45_Hanrun_HR911130C_MagJack', '', 'RJ45 with integrated 1000BASE-T magnetics + LEDs'),
    ]
    lib = ['kicad_symbol_lib', ['version', 20220914], ['generator', 'sbc_gen']] + syms
    with open(os.path.join(KICAD, 'sbc.kicad_sym'), 'w') as f:
        f.write(dump(lib) + '\n')
    print('symbols:', [s[1] for s in syms])
    print('footprints:', [f[1] for f in fps])


if __name__ == '__main__':
    main()
