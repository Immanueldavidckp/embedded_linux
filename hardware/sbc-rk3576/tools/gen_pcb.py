#!/usr/bin/env python3
"""Build the KiCad PCB from design.py: 8-layer stackup, outline, net classes,
floorplan placement of every footprint, ground planes.

Placement strategy (this is a floorplan, not a routed board):
  * Connectors, BGAs, PMIC, regulators: fixed coordinates in PLACE below.
    The positions follow the RK3576 ballout: the DDR balls sit on the column-1
    edge (left), HDMI/PCIe/USB/eMMC exit on the right and bottom edges.
  * Every passive is auto-placed by a spiral search around its "anchor" - the
    IC it serves (shares a net with, same sheet). BGA decoupling goes on the
    bottom side directly under the BGA, everything else on top.
"""
import json, math, os, re
import pcbnew
from design import build

HERE = os.path.dirname(os.path.abspath(__file__))
KICAD = os.path.join(HERE, '..', 'kicad')
SYSFP = '/usr/share/kicad/footprints'
PCB = os.path.join(KICAD, 'rk3576-sbc.kicad_pcb')
PRO = os.path.join(KICAD, 'rk3576-sbc.kicad_pro')

W, H = 100.0, 72.0         # board size (mm), Pico-ITX-like (room for RJ45 + 3 USB-A)
CORNER = 3.0
MM = pcbnew.FromMM
TOP, BOT = 'top', 'bottom'

# ref: (x, y, rot, side) - or (edge, pos, side, overhang) for edge connectors
PLACE = {
    'U401': (45.0, 33.0, 0, TOP),     # RK3576 (DDR balls on its left edge, HS I/O right/bottom)
    'U601': (25.0, 33.0, 0, TOP),     # LPDDR5 - left of SoC, on the DDR ball edge
    'U701': (66.0, 21.0, 0, TOP),     # eMMC - right/top of SoC (EMMC balls D..G28)
    'U201': (45.0, 12.0, 0, TOP),     # RK806 PMIC above the SoC (short core-rail loops)
    'Y501': (58.0, 44.5, 0, TOP),     # 24 MHz near OSC_XIN/XOUT (U28/U29)
    'U301': (8.0, 20.0, 0, TOP),     # 2V0 pre-reg
    'U302': (8.0, 27.0, 0, TOP),     # 1V1 pre-reg
    'U303': (8.0, 34.0, 0, TOP),     # VDD2L for LPDDR5
    'U304': (62.0, 56.0, 0, TOP),     # M.2 3V3 buck
    'U305': (60.0, 4.5, 0, TOP),      # VCC_3V3_S0 switch
    'U901': (52.5, 55.0, 0, TOP),     # HDMI ESD
    'U902': (48.5, 55.0, 0, TOP),     # HDMI ESD
    'U1001': (22.0, 60.0, 0, TOP),    # USB-C ESD
    'U1002': (80.0, 21.0, 0, TOP),    # USB3 SS ESD
    'U1003': (80.0, 11.0, 0, TOP),     # USB3-A D+/D- ESD
    'U1004': (75.0, 6.0, 0, TOP),     # USB3-A VBUS switch
    'U702': (8.0, 40.0, 0, BOT),      # SD power switch
    'U1301': (72.0, 60.0, 0, TOP),    # RTL8211F next to the RJ45
    'Y1301': (72.0, 66.5, 0, TOP),
    'U1401': (74.5, 34.0, 90, TOP),   # FE1.1s hub between SoC and the USB-A stack
    'Y1401': (74.5, 42.5, 0, TOP),
    'U1402': (81.0, 37.5, 0, TOP),    # USB-A #1 ESD
    'U1403': (81.0, 42.0, 0, TOP),    # USB-A #2 ESD
    'U1404': (70.0, 4.5, 0, TOP),     # USB2-A VBUS switch
    'U1405': (17.0, 9.0, 0, TOP),     # Wi-Fi/BT module, top-left away from the SoC
    'J1402': (4.5, 13.0, 0, TOP),     # u.FL antenna
    'J101': ('bottom', 12.0, TOP, 1.0),     # USB-C power/OTG
    'J901': ('bottom', 34.0, TOP, 1.0),     # HDMI
    'J1001': ('right', 16.0, TOP, 2.0),     # USB3 type-A
    'J1401': ('right', 34.8, TOP, 2.0),     # 2x USB2 type-A (stacked)
    'J1301': ('right', 56.0, TOP, 2.0),     # RJ45 GbE
    'J701': ('left', 50.0, BOT, -0.3),      # microSD (bottom side)
    'J801': (74.0, 44.0, 90, BOT),    # M.2 socket, card extends to -x over the bottom
    'H801': (32.0, 44.0, 0, BOT),     # 2242 standoff (verify vs connector datum)
    'H802': (44.0, 44.0, 0, BOT),     # 2230 standoff
    'J501': (50.0, 68.6, 90, TOP),    # debug UART header (GND/TX/RX) on the bottom edge
    'SW501': (28.0, 4.0, 0, TOP),     # MASKROM
    'SW502': (35.0, 4.0, 0, TOP),     # POWER
    'SW503': (42.0, 4.0, 0, TOP),     # RESET
    'LED101': (4.0, 58.0, 0, TOP),
    'LED501': (4.0, 55.0, 0, TOP),
    'LED801': (4.0, 52.0, 0, TOP),
    'H1201': (3.5, 3.5, 0, TOP), 'H1202': (96.5, 3.5, 0, TOP),
    'H1203': (3.5, 68.5, 0, TOP), 'H1204': (96.5, 68.5, 0, TOP),
    'FID1201': (52.0, 2.5, 0, TOP), 'FID1202': (64.0, 69.5, 0, TOP), 'FID1203': (24.0, 69.5, 0, TOP),
}
# local "mouth" (cable side) direction of edge connectors in footprint coords
MOUTH = {'J101': (0, 1), 'J901': (1, 0), 'J1001': (0, 1), 'J701': (0, 1), 'J1301': (0, -1), 'J1401': (-1, 0)}
BGA_ANCHORS = {'U401', 'U601', 'U701'}

NETCLASSES = [
    # name, clearance, track, via_d, via_drill, dp_width, dp_gap, patterns
    ('Default', 0.10, 0.10, 0.35, 0.20, 0.10, 0.15, []),
    ('LPDDR5', 0.09, 0.09, 0.35, 0.20, 0.09, 0.12, ['LP5_*', 'DDR_RESET_L', 'LP5_ZQ']),
    ('HDMI_100R', 0.12, 0.10, 0.35, 0.20, 0.10, 0.16, ['HDMI_TX_D*', 'HDMI_D*']),
    ('PCIE_85R', 0.12, 0.13, 0.35, 0.20, 0.13, 0.15, ['PCIE0_TX*', 'PCIE0_RX*', 'PCIE0_REFCLK*', 'M2_PET*']),
    ('USB_90R', 0.12, 0.11, 0.35, 0.20, 0.11, 0.15, ['USBC_D*', 'USB3A_D*', 'USB3_*', 'USB3A_SS*']),
    ('EMMC_SD', 0.10, 0.10, 0.35, 0.20, 0.10, 0.15, ['EMMC_*', 'SD_*']),
    ('POWER', 0.12, 0.20, 0.35, 0.20, 0.20, 0.20,
     ['VDD*', 'VCC*', 'VBUS*', 'PMIC_SW*', '*_SW', 'HDMI_5V_PTC']),
]

# 8-layer 1.6mm stackup (JLCPCB JLC08161H-3313-like). Confirm with the fab's
# impedance calculator before release; trace widths above assume these values.
STACKUP = [
    ('F.SilkS', 'Top Silk Screen', None, None), ('F.Paste', 'Top Solder Paste', None, None),
    ('F.Mask', 'Top Solder Mask', 0.01, None),
    ('F.Cu', 'copper', 0.035, 'L1 SIG (BGA escape, HS pairs)'),
    ('dielectric 1', 'prepreg', 0.0994, ('3313', 4.10)),
    ('In1.Cu', 'copper', 0.0152, 'L2 GND'),
    ('dielectric 2', 'core', 0.30, ('FR4', 4.60)),
    ('In2.Cu', 'copper', 0.0152, 'L3 SIG (DDR byte lanes)'),
    ('dielectric 3', 'prepreg', 0.0994, ('3313', 4.10)),
    ('In3.Cu', 'copper', 0.0152, 'L4 PWR (core rails split)'),
    ('dielectric 4', 'core', 0.30, ('FR4', 4.60)),
    ('In4.Cu', 'copper', 0.0152, 'L5 GND'),
    ('dielectric 5', 'prepreg', 0.0994, ('3313', 4.10)),
    ('In5.Cu', 'copper', 0.0152, 'L6 SIG (DDR CA, low speed)'),
    ('dielectric 6', 'core', 0.30, ('FR4', 4.60)),
    ('In6.Cu', 'copper', 0.0152, 'L7 GND / PWR'),
    ('dielectric 7', 'prepreg', 0.0994, ('3313', 4.10)),
    ('B.Cu', 'copper', 0.035, 'L8 SIG + decoupling'),
    ('B.Mask', 'Bottom Solder Mask', 0.01, None), ('B.Paste', 'Bottom Solder Paste', None, None),
    ('B.SilkS', 'Bottom Silk Screen', None, None),
]


def stackup_sexp():
    out = ['\t\t(stackup']
    for name, typ, th, extra in STACKUP:
        s = f'\t\t\t(layer "{name}" (type "{typ}")'
        if th is not None:
            s += f' (thickness {th})'
        if typ in ('prepreg', 'core'):
            s += f' (material "{extra[0]}") (epsilon_r {extra[1]}) (loss_tangent 0.02)'
        if 'Mask' in name:
            s += ' (color "Green")'
        if 'SilkS' in name:
            s += ' (color "White")'
        out.append(s + ')')
    out += ['\t\t\t(copper_finish "ENIG")', '\t\t\t(dielectric_constraints no)', '\t\t)']
    return '\n'.join(out)


# ---------------------------------------------------------------- helpers
def load_fp(fpid):
    lib, name = fpid.split(':', 1)
    path = os.path.join(KICAD, 'sbc.pretty') if lib == 'sbc' else os.path.join(SYSFP, lib + '.pretty')
    fp = pcbnew.FootprintLoad(path, name)
    if fp is None:
        raise SystemExit(f'footprint not found: {fpid}')
    fp.SetFPID(pcbnew.LIB_ID(lib, name))
    return fp


def bbox_mm(fp):
    """Courtyard bbox (falls back to full bbox) in mm: (x0, y0, x1, y1)."""
    layer = pcbnew.B_CrtYd if fp.IsFlipped() else pcbnew.F_CrtYd
    try:
        fp.BuildCourtyardCaches()
        poly = fp.GetCourtyard(layer)
        if poly.OutlineCount():
            b = poly.BBox()
        else:
            b = fp.GetBoundingBox(False)
    except Exception:
        b = fp.GetBoundingBox(False)
    return (pcbnew.ToMM(b.GetLeft()), pcbnew.ToMM(b.GetTop()), pcbnew.ToMM(b.GetRight()), pcbnew.ToMM(b.GetBottom()))


def is_tht(fp):
    return any(p.GetAttribute() in (pcbnew.PAD_ATTRIB_PTH, pcbnew.PAD_ATTRIB_NPTH) for p in fp.Pads())


def set_pose(fp, x, y, rot, side):
    fp.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
    fp.SetOrientationDegrees(rot)
    if side == BOT and not fp.IsFlipped():
        fp.Flip(fp.GetPosition(), pcbnew.FLIP_DIRECTION_LEFT_RIGHT)


def local_to_world_dir(fp, local_fp, v):
    """Transform a local direction vector using two pads as reference."""
    pads = [(p.GetNumber(), p.GetPosition()) for p in local_fp.Pads()]
    wpad = {}
    for p in fp.Pads():
        wpad.setdefault(p.GetNumber(), p.GetPosition())
    # pick two pads whose local positions are non-collinear with the origin
    best = None
    for i in range(len(pads)):
        for j in range(i + 1, len(pads)):
            a, b = pads[i][1], pads[j][1]
            det = a.x * b.y - a.y * b.x
            if abs(det) > 1e6 and pads[i][0] != pads[j][0]:
                best = (pads[i], pads[j], det)
                break
        if best:
            break
    (na, a), (nb, b), det = best
    c = fp.GetPosition()
    wa, wb = wpad[na] - c, wpad[nb] - c
    # solve M such that M*a = wa, M*b = wb
    inv = [[b.y / det, -b.x / det], [-a.y / det, a.x / det]]
    m00 = wa.x * inv[0][0] + wb.x * inv[1][0]
    m01 = wa.x * inv[0][1] + wb.x * inv[1][1]
    m10 = wa.y * inv[0][0] + wb.y * inv[1][0]
    m11 = wa.y * inv[0][1] + wb.y * inv[1][1]
    return (m00 * v[0] + m01 * v[1], m10 * v[0] + m11 * v[1])


def place_edge(fp, ref, edge, pos, side, overhang):
    want = {'bottom': (0, 1), 'top': (0, -1), 'left': (-1, 0), 'right': (1, 0)}[edge]
    local = load_fp(fp.GetFPIDAsString())
    for rot in (0, 90, 180, 270):
        set_pose(fp, 0, 0, rot, side)
        d = local_to_world_dir(fp, local, MOUTH[ref])
        n = math.hypot(*d)
        if (d[0] / n) * want[0] + (d[1] / n) * want[1] > 0.9:
            break
    else:
        raise SystemExit(f'{ref}: no rotation points the mouth to {edge}')
    x0, y0, x1, y1 = bbox_mm(fp)
    if edge == 'bottom':
        dx, dy = pos - (x0 + x1) / 2, H + overhang - y1
    elif edge == 'top':
        dx, dy = pos - (x0 + x1) / 2, -overhang - y0
    elif edge == 'left':
        dx, dy = -overhang - x0, pos - (y0 + y1) / 2
    else:
        dx, dy = W + overhang - x1, pos - (y0 + y1) / 2
    fp.Move(pcbnew.VECTOR2I(MM(dx), MM(dy)))


class Occupancy:
    """0.25mm raster per side; a cell is busy if any courtyard covers it."""
    RES = 0.25

    def __init__(self):
        self.nx, self.ny = int(W / self.RES) + 1, int(H / self.RES) + 1
        self.grid = {TOP: [bytearray(self.nx) for _ in range(self.ny)],
                     BOT: [bytearray(self.nx) for _ in range(self.ny)]}

    def _rng(self, x0, y0, x1, y1):
        r = self.RES
        return (max(0, int(x0 / r)), max(0, int(y0 / r)), min(self.nx, int(math.ceil(x1 / r))),
                min(self.ny, int(math.ceil(y1 / r))))

    def mark(self, box, sides, pad=0.1):
        i0, j0, i1, j1 = self._rng(box[0] - pad, box[1] - pad, box[2] + pad, box[3] + pad)
        for s in sides:
            for j in range(j0, j1):
                row = self.grid[s][j]
                row[i0:i1] = b'\x01' * (i1 - i0)

    def free(self, box, side, margin=0.6):
        if box[0] < margin or box[1] < margin or box[2] > W - margin or box[3] > H - margin:
            return False
        i0, j0, i1, j1 = self._rng(*box)
        g = self.grid[side]
        return not any(any(g[j][i0:i1]) for j in range(j0, j1))


SPIRAL = sorted(((dx * 0.5, dy * 0.5) for dx in range(-90, 91) for dy in range(-70, 71)),
                key=lambda v: (v[0] ** 2 + v[1] ** 2, v[1], v[0]))


def autoplace(fp, anchor_xy, side, occ, rot_options=(0, 90)):
    ax, ay = anchor_xy
    for rot in rot_options:
        set_pose(fp, ax, ay, rot, side)
        bx0, by0, bx1, by1 = bbox_mm(fp)
        ox, oy = ax - (bx0 + bx1) / 2, ay - (by0 + by1) / 2
        hw, hh = (bx1 - bx0) / 2, (by1 - by0) / 2
        for dx, dy in SPIRAL:
            cx, cy = ax + dx, ay + dy
            box = (cx - hw, cy - hh, cx + hw, cy + hh)
            if occ.free(box, side):
                set_pose(fp, cx + ox, cy + oy, rot, side)
                occ.mark(bbox_mm(fp), [side])
                return True
    return False


# ------------------------------------------------------------------ main
def schematic_netlist():
    import subprocess, tempfile
    from sexp import parse, find, findall
    out = os.path.join(tempfile.mkdtemp(), 'sbc.net')
    subprocess.run(['kicad-cli', 'sch', 'export', 'netlist', '-o', out,
                    os.path.join(KICAD, 'rk3576-sbc.kicad_sch')], check=True, capture_output=True)
    m = {}
    for n in findall(find(parse(open(out).read()), 'nets'), 'net'):
        name = str(find(n, 'name')[1]).lstrip('/')
        for node in findall(n, 'node'):
            m[(str(find(node, 'ref')[1]), str(find(node, 'pin')[1]))] = name
    return m


def write_project():
    pro = json.load(open(PRO)) if os.path.exists(PRO) else {}
    pro.setdefault('meta', {'filename': 'rk3576-sbc.kicad_pro', 'version': 3})
    classes, patterns = [], []
    for name, clr, tw, vd, vdr, dpw, dpg, pats in NETCLASSES:
        classes.append({'name': name, 'clearance': clr, 'track_width': tw, 'via_diameter': vd, 'via_drill': vdr,
                        'microvia_diameter': 0.25, 'microvia_drill': 0.1, 'diff_pair_width': dpw,
                        'diff_pair_gap': dpg, 'diff_pair_via_gap': 0.25, 'wire_width': 6, 'bus_width': 12,
                        'line_style': 0, 'pcb_color': 'rgba(0, 0, 0, 0.000)',
                        'schematic_color': 'rgba(0, 0, 0, 0.000)',
                        'priority': 2147483647 if name == 'Default' else len(classes)})
        patterns += [{'netclass': name, 'pattern': p} for p in pats]
    pro['net_settings'] = {'classes': classes, 'meta': {'version': 4}, 'net_colors': None,
                           'netclass_assignments': None, 'netclass_patterns': patterns}
    rules = pro.setdefault('board', {}).setdefault('design_settings', {}).setdefault('rules', {})
    rules.update({'min_clearance': 0.09, 'min_track_width': 0.09, 'min_via_diameter': 0.25,
                  'min_via_annular_width': 0.05, 'min_through_hole_diameter': 0.15,
                  'min_hole_to_hole': 0.25, 'min_copper_edge_clearance': 0.3, 'min_hole_clearance': 0.12,
                  'min_microvia_diameter': 0.2, 'min_microvia_drill': 0.1, 'allow_blind_buried_vias': True,
                  'allow_microvias': True, 'solder_mask_to_copper_clearance': 0.0,
                  'min_silk_clearance': 0.0, 'min_text_height': 0.6, 'min_text_thickness': 0.1})
    pro['board']['design_settings'].setdefault('rule_severities', {}).update({
        # Generated placeholder BGA pads and dense 0201 fields: keep silk/courtyard
        # checks as warnings so real electrical errors stand out in the report.
        'silk_overlap': 'ignore', 'silk_over_copper': 'ignore', 'silk_edge_clearance': 'ignore',
        'courtyards_overlap': 'warning', 'lib_footprint_mismatch': 'ignore',
        'lib_footprint_issues': 'ignore', 'text_height': 'ignore', 'text_thickness': 'ignore'})
    json.dump(pro, open(PRO, 'w'), indent=2)


def add_text(board, text, x, y, size=1.0, layer=pcbnew.F_SilkS, rot=0):
    t = pcbnew.PCB_TEXT(board)
    t.SetText(text)
    t.SetPosition(pcbnew.VECTOR2I(MM(x), MM(y)))
    t.SetLayer(layer)
    t.SetTextSize(pcbnew.VECTOR2I(MM(size), MM(size)))
    t.SetTextThickness(MM(size * 0.15))
    t.SetTextAngleDegrees(rot)
    if layer in (pcbnew.B_SilkS, pcbnew.B_Fab):
        t.SetMirrored(True)
    board.Add(t)


def outline(board):
    r = CORNER
    segs = [((r, 0), (W - r, 0)), ((W, r), (W, H - r)), ((W - r, H), (r, H)), ((0, H - r), (0, r))]
    for (a, b) in segs:
        s = pcbnew.PCB_SHAPE(board)
        s.SetShape(pcbnew.SHAPE_T_SEGMENT)
        s.SetStart(pcbnew.VECTOR2I(MM(a[0]), MM(a[1])))
        s.SetEnd(pcbnew.VECTOR2I(MM(b[0]), MM(b[1])))
        s.SetLayer(pcbnew.Edge_Cuts)
        s.SetWidth(MM(0.1))
        board.Add(s)
    k = r - r / math.sqrt(2)          # arc midpoint offset from the corner
    for st, mid, en in [((0, r), (k, k), (r, 0)), ((W - r, 0), (W - k, k), (W, r)),
                        ((W, H - r), (W - k, H - k), (W - r, H)), ((r, H), (k, H - k), (0, H - r))]:
        a = pcbnew.PCB_SHAPE(board)
        a.SetShape(pcbnew.SHAPE_T_ARC)
        a.SetArcGeometry(*(pcbnew.VECTOR2I(MM(px), MM(py)) for px, py in (st, mid, en)))
        a.SetLayer(pcbnew.Edge_Cuts)
        a.SetWidth(MM(0.1))
        board.Add(a)


def gnd_zone(board, layer, net):
    z = pcbnew.ZONE(board)
    z.SetLayer(layer)
    z.SetNet(net)
    z.SetIsRuleArea(False)
    z.SetLocalClearance(MM(0.1))      # 0.55 mm BGA via field: keep plane webs
    z.SetMinThickness(MM(0.1))
    z.SetPadConnection(pcbnew.ZONE_CONNECTION_THERMAL)
    z.SetZoneName(f'GND_{board.GetLayerName(layer)}')
    o = z.Outline()
    o.NewOutline()
    for x, y in [(0.3, 0.3), (W - 0.3, 0.3), (W - 0.3, H - 0.3), (0.3, H - 0.3)]:
        o.Append(MM(x), MM(y))
    board.Add(z)
    return z


def main():
    d = build()
    write_project()
    board = pcbnew.BOARD()
    board.SetCopperLayerCount(8)
    ds = board.GetDesignSettings()
    ds.SetBoardThickness(MM(1.6))
    outline(board)

    # Nets come from the schematic (kicad-cli netlist), exactly like "Update PCB
    # from Schematic"; design.py is cross-checked against it so they can't drift.
    sch_nets = schematic_netlist()
    for p in d.parts:
        for pin, n in p.nets.items():
            if n and sch_nets.get((p.ref, pin)) != n:
                raise SystemExit(f'schematic/design mismatch on {p.ref}.{pin}: {sch_nets.get((p.ref, pin))} != {n}')
    nets = {}
    for n in sorted(set(sch_nets.values())):
        ni = pcbnew.NETINFO_ITEM(board, n)
        board.Add(ni)
        nets[n] = ni

    fps = {}
    problems = []
    for p in d.parts:
        fp = load_fp(p.footprint)
        fp.SetReference(p.ref)
        fp.SetValue(p.value)
        for k, v in (('MPN', p.mpn), ('Manufacturer', p.mfr), ('LCSC', p.lcsc), ('Description', p.desc)):
            if v:
                fp.SetField(k, v)
                f = fp.GetFieldByName(k)
                if f:
                    f.SetVisible(False)
        fp.SetDNP(p.dnp)
        attrs = fp.GetAttributes() & ~pcbnew.FP_EXCLUDE_FROM_BOM
        fp.SetAttributes(attrs if p.bom else attrs | pcbnew.FP_EXCLUDE_FROM_BOM)
        if p.dnp:
            fp.SetAttributes(fp.GetAttributes() | pcbnew.FP_EXCLUDE_FROM_POS_FILES)
        pad_nums = {pd.GetNumber() for pd in fp.Pads()}
        for pin, n in p.nets.items():
            if pin not in pad_nums:
                problems.append(f'{p.ref}: pin {pin} has no pad in {p.footprint}')
        for pd in fp.Pads():
            n = sch_nets.get((p.ref, pd.GetNumber()))
            if n:
                pd.SetNet(nets[n])
        # small passives: reference on fab layer only (assembly drawing)
        if p.ref[0] in 'RCL' and not p.ref.startswith('LED') or p.ref.startswith('FB'):
            fp.Reference().SetVisible(False)
        board.Add(fp)
        fps[p.ref] = (p, fp)
    if problems:
        raise SystemExit('\n'.join(problems))

    occ = Occupancy()
    fixed = []
    # 1) fixed parts
    for ref, spec in PLACE.items():
        p, fp = fps[ref]
        if isinstance(spec[0], str):
            place_edge(fp, ref, *spec)
            side = spec[2]
        else:
            x, y, rot, side = spec
            set_pose(fp, x, y, rot, side)
        box = bbox_mm(fp)
        sides = [TOP, BOT] if is_tht(fp) else [side]
        fixed.append((ref, box, set(sides)))
        occ.mark(box, sides, pad=0.2)
    # Keep the bottom side under the fine-pitch BGAs free for via-in-pad fan-out
    # (tools/fanout.py); their decoupling ends up as a tight ring around them.
    for r in ('U401', 'U601'):
        occ.mark(bbox_mm(fps[r][1]), [BOT], pad=0.3)
    clash = [f'{r1}/{r2}' for i, (r1, b1, s1) in enumerate(fixed) for (r2, b2, s2) in fixed[i + 1:]
             if s1 & s2 and b1[0] < b2[2] and b2[0] < b1[2] and b1[1] < b2[3] and b2[1] < b1[3]]
    if clash:
        raise SystemExit('fixed placements overlap: ' + ', '.join(clash))
    # M.2 card shadow: keep tall bottom parts out? (0402/0201 under the card are OK)

    # 2) anchors for everything else
    placed = set(PLACE)
    centers = {r: (pcbnew.ToMM(f.GetPosition().x), pcbnew.ToMM(f.GetPosition().y)) for r, (_, f) in fps.items()
               if r in placed}
    big = [r for r in placed if r[0] in 'UJQY']

    def anchor(p):
        mine = {n for n in p.nets.values() if n and n != 'GND'}
        cands = []
        for r in list(placed):
            q = fps[r][0]
            if r == p.ref or r[0] not in 'UJQYD' or r.startswith('H'):
                continue
            share = mine & {n for n in q.nets.values() if n}
            if share:
                same = q.sheet == p.sheet or q.unit_sheets and p.sheet in q.unit_sheets.values()
                cands.append((0 if same else 1, len(q.nets), r))
        if not cands:
            return None
        return min(cands)[2]

    # place ICs that are not fixed (Q, D, F...) first, then passives
    order = sorted((r for r in fps if r not in placed),
                   key=lambda r: (0 if r[0] in 'UQDFY' else 1 if r.startswith('L') else 2, r))
    failed = []
    for r in order:
        p, fp = fps[r]
        a = anchor(p)
        if a is None:
            a = {'01': 'J101', '02': 'U201', '03': 'U301', '04': 'U401', '05': 'U401', '06': 'U601',
                 '07': 'U701', '08': 'J801', '09': 'J901', '10': 'J1001', '12': 'U401', '13': 'U1301',
                 '14': 'U1401'}[p.sheet[:2]]
        side = BOT if (a in BGA_ANCHORS and r[0] in 'RC' and not r.startswith('LED')) else TOP
        if a == 'J801' or a == 'J701' or a == 'U702':
            side = BOT
        ok = autoplace(fp, centers[a], side, occ)
        if not ok:
            ok = autoplace(fp, centers[a], BOT if side == TOP else TOP, occ)
        if not ok:
            failed.append(r)
            continue
        placed.add(r)
        centers[r] = (pcbnew.ToMM(fp.GetPosition().x), pcbnew.ToMM(fp.GetPosition().y))
    if failed:
        print('could not place:', failed)

    # 3) planes: L2, L5, L7 solid GND
    for l in (pcbnew.In1_Cu, pcbnew.In4_Cu, pcbnew.In6_Cu):
        gnd_zone(board, l, nets['GND'])

    # 4) silkscreen
    add_text(board, 'RK3576 SBC  rev A1', 32, 70.4, 0.9)
    add_text(board, 'USB-C 5V / OTG', 12, 62.5, 0.7)
    add_text(board, 'HDMI 4K', 34, 61.8, 0.7)
    add_text(board, 'USB3', 92.0, 23.5, 0.7)
    add_text(board, 'USB2 x2', 91.0, 44.0, 0.7)
    add_text(board, 'GbE', 92.0, 46.5, 0.7)
    add_text(board, 'GND TX RX', 52.5, 66.2, 0.6)
    add_text(board, 'MASKROM  POWER  RESET', 35, 7.2, 0.6)
    add_text(board, 'ANT', 4.5, 16.5, 0.6)
    add_text(board, 'microSD', 9.0, 50.0, 0.8, pcbnew.B_SilkS, 90)
    add_text(board, 'M.2 2230/2242 NVMe', 58, 57.5, 0.9, pcbnew.B_SilkS)

    pcbnew.SaveBoard(PCB, board)
    # inject stackup into (setup ...)
    txt = open(PCB).read()
    if '(stackup' not in txt:
        txt = txt.replace('(setup', '(setup\n' + stackup_sexp(), 1)
    open(PCB, 'w').write(txt)
    write_project()     # SaveBoard may rewrite the project file; re-apply net classes
    # Zone fill needs a fully loaded board (filling the in-memory one segfaults in 9.0)
    b2 = pcbnew.LoadBoard(PCB)
    pcbnew.ZONE_FILLER(b2).Fill(b2.Zones())
    pcbnew.SaveBoard(PCB, b2)
    write_project()
    top = sum(1 for _, f in fps.values() if not f.IsFlipped())
    print(f'{len(fps)} footprints placed ({top} top, {len(fps) - top} bottom), {len(nets)} nets -> {PCB}')


if __name__ == '__main__':
    main()
