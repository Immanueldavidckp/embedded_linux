#!/usr/bin/env python3
"""Grid maze router for the connections Freerouting left open.

    python3 maze_route.py IN.kicad_pcb OUT.kicad_pcb [--nets REGEX] [--exclude REGEX]
                          [--drc drc.json] [--patch out.json] [--res 0.025] [--margin 3]

Why a second router: Freerouting plateaued at ~480 open connections (LOG.md
#19/#20). Most of them are short (fragments 0.5-5 mm apart) in the dense areas
around the 0.55 mm RK3576 and the LPDDR5. A Lee/A* maze router on a fine grid
finds those paths reliably because it searches every free cell, where a
topological autorouter gives up.

How it works
  1. Rasterise every copper item per layer (pads, tracks, vias, zone fills,
     keepouts, board edge, drill holes) at RES mm/cell, remembering the net
     and its clearance.
  2. Take the open connections from KiCad's own DRC (unconnected_items: item
     A <-> item B, by UUID). That is KiCad's ratsnest, so "done" means DRC agrees.
  3. For each connection (shortest first) cut a window around A and B, dilate
     other-net copper by clearance + half the track width (distance transform),
     and run A* (C, tools/maze/astar.c) over all allowed layers. A layer change
     is a through via, allowed only where the drill and both pads fit.
  4. String-pull the cell path into straight segments, add tracks and vias to
     the board, and stamp them into the rasters so later routes avoid them.

Layers: signals use L1/L3/L6/L8 (F, In2, In5, B). Power nets may also use their
own pours on L4/L7 (In3, In6); GND may use everything. L2/L5 stay solid GND.
New vias remove unconnected pads (non-functional pad removal), which also
opens the channels between the BGA fan-out vias on the inner layers.
"""
import argparse, ctypes, json, math, os, re, subprocess, sys, time
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage
import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
MM, TOMM = pcbnew.FromMM, pcbnew.ToMM
LAYERS = [pcbnew.F_Cu, pcbnew.In1_Cu, pcbnew.In2_Cu, pcbnew.In3_Cu, pcbnew.In4_Cu, pcbnew.In5_Cu,
          pcbnew.In6_Cu, pcbnew.B_Cu]
LI = {l: i for i, l in enumerate(LAYERS)}
SIG = (0, 2, 5, 7)            # F, In2, In5, B
PWR_LAYERS = (3, 6)           # In3, In6 pours
X0, Y0, X1, Y1 = -0.5, -0.5, 100.5, 72.5
EDGE_CLR, HOLE_CLR, HOLE2HOLE = 0.30, 0.12, 0.25
# name-pattern -> (track width, clearance); first match wins (mirrors gen_pcb.NETCLASSES)
CLASSES = [
    (r'^(LP5_|DDR_RESET_L)', 0.09, 0.09), (r'^HDMI_(TX_)?D', 0.10, 0.12),
    (r'^(PCIE0_(TX|RX|REFCLK)|M2_PET)', 0.13, 0.12), (r'^(USBC_D|USB3A_D|USB3_|USB3A_SS)', 0.11, 0.12),
    (r'^(EMMC_|SD_)', 0.10, 0.10),
    (r'^(VDD|VCC|VBUS|PMIC_SW)|_SW$|^HDMI_5V_PTC', 0.20, 0.10),
]
VIAS = [(0.35, 0.20), (0.30, 0.15), (0.25, 0.15)]
BGA_REFS = ('U401', 'U601', 'U701')     # RK3576, LPDDR5, eMMC

_so = os.path.join(HERE, 'maze', 'libastar.so')
if not os.path.exists(_so) or os.path.getmtime(_so) < os.path.getmtime(_so.replace('libastar.so', 'astar.c')):
    subprocess.run(['gcc', '-O3', '-march=native', '-shared', '-fPIC', '-o', _so + '.tmp',
                    _so.replace('libastar.so', 'astar.c'), '-lm'], check=True)
    os.replace(_so + '.tmp', _so)          # atomic: running routers keep the old inode
lib = ctypes.CDLL(_so)
U8P = np.ctypeslib.ndpointer(np.uint8, flags='C_CONTIGUOUS')
lib.astar.argtypes = [ctypes.c_int] * 3 + [U8P, U8P, U8P, U8P, np.ctypeslib.ndpointer(np.float32),
                     ctypes.c_float, ctypes.c_float] + [ctypes.c_int] * 4 + \
                    [np.ctypeslib.ndpointer(np.int32), ctypes.c_int, ctypes.c_long,
                     ctypes.c_void_p, ctypes.c_void_p, ctypes.c_float]
lib.astar.restype = ctypes.c_int


def net_class(name):
    for pat, w, c in CLASSES:
        if re.search(pat, name):
            return w, c, pat.startswith('^(VDD')
    return 0.10, 0.10, False


class Raster:
    """Full-board per-layer copper maps."""

    def __init__(self, board, res):
        self.res = res
        self.W = int(math.ceil((X1 - X0) / res))
        self.H = int(math.ceil((Y1 - Y0) / res))
        self.hard = [np.zeros((self.H, self.W), np.int32) for _ in LAYERS]   # net code, -1 = all-net obstacle
        self.clr = [np.zeros((self.H, self.W), np.uint8) for _ in LAYERS]    # clearance, 10 um units
        self.zone = [np.zeros((self.H, self.W), np.int32) for _ in LAYERS]
        self.holes = np.zeros((self.H, self.W), np.int32)                  # drilled holes: net, -1 = NPTH
        self.nopadvia = np.zeros((self.H, self.W), np.uint8)                # vias never inside SMD pads
        self.viakeep = np.zeros((self.H, self.W), np.uint8)
        self.edge = np.ones((self.H, self.W), np.uint8)
        # copper that rip-up may remove (routed tracks and unlocked vias): its net per cell
        self.soft = [np.zeros((self.H, self.W), np.int32) for _ in LAYERS]
        self.hsoft = np.zeros((self.H, self.W), np.uint8)
        self.index, self.boxes = [], None
        self.build(board)

    # -- geometry helpers ------------------------------------------------
    def px(self, x_nm, y_nm):
        return ((x_nm / 1e6 - X0) / self.res - 0.5, (y_nm / 1e6 - Y0) / self.res - 0.5)

    def polys(self, ps):
        out = []
        for i in range(ps.OutlineCount()):
            o = ps.Outline(i)
            out.append(([self.px(o.CPoint(k).x, o.CPoint(k).y) for k in range(o.PointCount())],
                        [[self.px(h.CPoint(k).x, h.CPoint(k).y) for k in range(h.PointCount())]
                         for h in (ps.Hole(i, j) for j in range(ps.HoleCount(i)))]))
        return out

    @staticmethod
    def item_poly(item, layer, grow=0):
        ps = pcbnew.SHAPE_POLY_SET()
        item.TransformShapeToPolygon(ps, layer, MM(grow) if grow else 0, MM(0.003), pcbnew.ERROR_OUTSIDE)
        return ps

    def stamp_polys(self, arr, plist, value, bbox_only=False):
        """Draw polygons into a numpy array via a PIL image of the polygons' bbox."""
        for outline, holes in plist:
            if len(outline) < 3:
                continue
            xs = [p[0] for p in outline]; ys = [p[1] for p in outline]
            x0, y0 = max(int(math.floor(min(xs))) - 1, 0), max(int(math.floor(min(ys))) - 1, 0)
            x1, y1 = min(int(math.ceil(max(xs))) + 2, self.W), min(int(math.ceil(max(ys))) + 2, self.H)
            if x1 <= x0 or y1 <= y0:
                continue
            im = Image.new('L', (x1 - x0, y1 - y0), 0)
            d = ImageDraw.Draw(im)
            d.polygon([(x - x0, y - y0) for x, y in outline], fill=1, outline=1)
            for h in holes:
                if len(h) >= 3:
                    d.polygon([(x - x0, y - y0) for x, y in h], fill=0, outline=0)
            m = np.asarray(im, dtype=bool)
            arr[y0:y1, x0:x1][m] = value

    def mask_polys(self, plist, x0, y0, w, h):
        """Boolean mask of polygons inside the window (x0, y0, w, h)."""
        im = Image.new('L', (w, h), 0)
        d = ImageDraw.Draw(im)
        for outline, holes in plist:
            if len(outline) >= 3:
                d.polygon([(x - x0, y - y0) for x, y in outline], fill=1, outline=1)
            for hh in holes:
                if len(hh) >= 3:
                    d.polygon([(x - x0, y - y0) for x, y in hh], fill=0, outline=0)
        return np.asarray(im, dtype=bool)

    def stamp_segment(self, li, a, b, width, net, clr):
        """Exact stamping of a straight track (mm coords) into hard/clr of layer li."""
        r = width / 2
        xa, ya, xb, yb = a[0], a[1], b[0], b[1]
        cx0 = max(int((min(xa, xb) - r - X0) / self.res) - 1, 0)
        cx1 = min(int((max(xa, xb) + r - X0) / self.res) + 2, self.W)
        cy0 = max(int((min(ya, yb) - r - Y0) / self.res) - 1, 0)
        cy1 = min(int((max(ya, yb) + r - Y0) / self.res) + 2, self.H)
        gx = X0 + (np.arange(cx0, cx1) + 0.5) * self.res
        gy = Y0 + (np.arange(cy0, cy1) + 0.5) * self.res
        GX, GY = np.meshgrid(gx, gy)
        dx, dy = xb - xa, yb - ya
        L2 = dx * dx + dy * dy
        t = np.clip(((GX - xa) * dx + (GY - ya) * dy) / L2, 0, 1) if L2 > 0 else 0
        d = np.hypot(GX - (xa + t * dx), GY - (ya + t * dy))
        m = d <= r + 0.5 * self.res
        self.hard[li][cy0:cy1, cx0:cx1][m] = net
        self.soft[li][cy0:cy1, cx0:cx1][m] = net
        sub = self.clr[li][cy0:cy1, cx0:cx1]
        sub[m] = np.maximum(sub[m], int(round(clr * 100)))

    def stamp_disc(self, arr, c, r, value):
        cx0 = max(int((c[0] - r - X0) / self.res) - 1, 0); cx1 = min(int((c[0] + r - X0) / self.res) + 2, self.W)
        cy0 = max(int((c[1] - r - Y0) / self.res) - 1, 0); cy1 = min(int((c[1] + r - Y0) / self.res) + 2, self.H)
        gx = X0 + (np.arange(cx0, cx1) + 0.5) * self.res
        gy = Y0 + (np.arange(cy0, cy1) + 0.5) * self.res
        GX, GY = np.meshgrid(gx, gy)
        m = np.hypot(GX - c[0], GY - c[1]) <= r + 0.5 * self.res
        arr[cy0:cy1, cx0:cx1][m] = value
        return (slice(cy0, cy1), slice(cx0, cx1)), m

    @staticmethod
    def removable(it):
        if it.GetClass() not in ('PCB_TRACK', 'PCB_ARC', 'PCB_VIA') or it.IsLocked():
            return False
        return True

    def register(self, it):
        bb = it.GetBoundingBox()
        self.index.append(it)
        self.boxes = None
        self._bb = getattr(self, '_bb', [])
        self._bb.append((TOMM(bb.GetLeft()), TOMM(bb.GetTop()), TOMM(bb.GetRight()), TOMM(bb.GetBottom())))

    def query(self, x0, y0, x1, y1):
        """Registered items whose bbox overlaps the mm rectangle."""
        if self.boxes is None or len(self.boxes) != len(self._bb):
            self.boxes = np.array(self._bb)
        B = self.boxes
        hit = np.nonzero((B[:, 0] <= x1) & (B[:, 2] >= x0) & (B[:, 1] <= y1) & (B[:, 3] >= y0))[0]
        return [self.index[i] for i in hit if self.index[i] is not None]

    def stamp_item(self, it):
        net = it.GetNetCode() if it.GetNetCode() > 0 else -1
        cls = it.GetClass()
        soft = self.removable(it)
        if cls == 'PAD' and it.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH:
            net = -1
        for l in LAYERS:
            if not it.IsOnLayer(l):
                continue
            if cls in ('PAD', 'PCB_VIA') and not it.FlashLayer(l):
                continue
            c = int(round(TOMM(it.GetOwnClearance(l)) * 100))
            pl = self.polys(self.item_poly(it, l))
            self.stamp_polys(self.hard[LI[l]], pl, net)
            self.stamp_polys(self.clr[LI[l]], pl, c)
            if soft:
                self.stamp_polys(self.soft[LI[l]], pl, net)
            if cls == 'PAD' and it.GetAttribute() == pcbnew.PAD_ATTRIB_SMD:
                self.stamp_polys(self.nopadvia, pl, 1)
                if it.GetParentFootprint().GetReference() in BGA_REFS:
                    # BGA balls may take a via-in-pad (filled + capped, see manufacturing.md),
                    # but only dead centre
                    px, py = self.px(it.GetPosition().x, it.GetPosition().y)
                    self.nopadvia[int(round(py)), int(round(px))] = 0
        if cls in ('PAD', 'PCB_VIA') and it.HasHole():
            hs = it.GetEffectiveHoleShape()
            a, bb = hs.GetSeg().A, hs.GetSeg().B
            r = TOMM(hs.GetWidth()) / 2
            for k in range(5):
                q = ((a.x + (bb.x - a.x) * k / 4) / 1e6, (a.y + (bb.y - a.y) * k / 4) / 1e6)
                sl, m = self.stamp_disc(self.holes, q, r, net)
                if soft:
                    self.hsoft[sl][m] = 1

    def unstamp(self, removed):
        """Forget removed items: clear their area and re-stamp everything else that overlaps it."""
        rm = {id(it) for it in removed}
        for i, it in enumerate(self.index):
            if it is not None and id(it) in rm:
                self.index[i] = None
        for it in removed:
            bb = it.GetBoundingBox()
            x0, y0 = TOMM(bb.GetLeft()) - 0.1, TOMM(bb.GetTop()) - 0.1
            x1, y1 = TOMM(bb.GetRight()) + 0.1, TOMM(bb.GetBottom()) + 0.1
            cx0, cy0 = max(int((x0 - X0) / self.res), 0), max(int((y0 - Y0) / self.res), 0)
            cx1, cy1 = min(int((x1 - X0) / self.res) + 2, self.W), min(int((y1 - Y0) / self.res) + 2, self.H)
            sl = (slice(cy0, cy1), slice(cx0, cx1))
            for li in range(len(LAYERS)):
                self.hard[li][sl] = 0
                self.clr[li][sl] = 0
                self.soft[li][sl] = 0
            self.holes[sl] = 0
            self.hsoft[sl] = 0
            self.nopadvia[sl] = 0
            gx0, gy0 = X0 + cx0 * self.res, Y0 + cy0 * self.res
            gx1, gy1 = X0 + cx1 * self.res, Y0 + cy1 * self.res
            for pl, lis, tracks in self.keepouts:
                if tracks:
                    for li in lis:
                        m = self.mask_polys(pl, cx0, cy0, cx1 - cx0, cy1 - cy0)
                        self.hard[li][sl][m] = -1
            for other in sorted(self.query(gx0 - 1, gy0 - 1, gx1 + 1, gy1 + 1),
                                key=lambda o: o.GetOwnClearance(pcbnew.F_Cu)):
                self.stamp_item(other)

    # -- build -------------------------------------------------------------
    def build(self, b):
        t0 = time.time()
        ps = pcbnew.SHAPE_POLY_SET()
        b.GetBoardPolygonOutlines(ps)
        inside = np.zeros_like(self.edge)
        self.stamp_polys(inside, self.polys(ps), 1)
        self.edge = (inside == 0).astype(np.uint8)
        for z in b.Zones():
            if z.GetIsRuleArea():
                continue
            for l in z.GetLayerSet().CuStack():
                if l in LI:
                    self.stamp_polys(self.zone[LI[l]], self.polys(z.GetFilledPolysList(l)), z.GetNetCode())
        rule_areas = [z for z in b.Zones() if z.GetIsRuleArea()] + \
                     [z for f in b.GetFootprints() for z in f.Zones() if z.GetIsRuleArea()]
        for z in rule_areas:
            pl = self.polys(z.Outline())
            for l in z.GetLayerSet().CuStack():
                if l in LI and z.GetDoNotAllowTracks():
                    self.stamp_polys(self.hard[LI[l]], pl, -1)
            if z.GetDoNotAllowVias():
                self.stamp_polys(self.viakeep, pl, 1)
        self.keepouts = [(self.polys(z.Outline()), [LI[l] for l in z.GetLayerSet().CuStack() if l in LI],
                          z.GetDoNotAllowTracks()) for z in rule_areas]
        items = []
        for f in b.GetFootprints():
            for p in f.Pads():
                items.append(p)
        items += list(b.GetTracks())
        # larger clearances last so they win where items overlap
        items.sort(key=lambda it: it.GetOwnClearance(pcbnew.F_Cu))
        for it in items:
            self.register(it)
            self.stamp_item(it)
        print(f'raster {self.W}x{self.H}x{len(LAYERS)} @ {self.res} mm built in {time.time() - t0:.0f} s', flush=True)


class Router:
    def __init__(self, board, res, margin_mm):
        self.b = board
        self.R = Raster(board, res)
        self.res = res
        self.margin = margin_mm
        self.byuuid = {}
        for f in board.GetFootprints():
            for p in f.Pads():
                self.byuuid[p.m_Uuid.AsString()] = p
        for t in board.GetTracks():
            self.byuuid[t.m_Uuid.AsString()] = t
        for z in board.Zones():
            self.byuuid[z.m_Uuid.AsString()] = z
        self.vias_by_net = {}
        for t in board.GetTracks():
            if t.GetClass() == 'PCB_VIA':
                self.vias_by_net.setdefault(t.GetNetCode(), []).append(
                    (TOMM(t.GetPosition().x), TOMM(t.GetPosition().y), TOMM(t.GetWidth(pcbnew.F_Cu)) / 2, t))
        self.added = []      # (conn_id, item)
        self.patch = []

    # cells of an item (eroded so the end point is truly inside it):
    # {layer index: (mask, centre cell or None, via diameter if the pad is not flashed yet)}
    def item_cells(self, it, pos, wx0, wy0, w, h):
        R = self.R
        out = {}
        cls = it.GetClass()
        if cls == 'ZONE':
            for l in it.GetLayerSet().CuStack():
                if l not in LI:
                    continue
                fp = it.GetFilledPolysList(l)
                best, bd = None, 1e30
                pt = pcbnew.VECTOR2I(MM(pos[0]), MM(pos[1]))
                for i in range(fp.OutlineCount()):
                    o = fp.Outline(i)
                    if o.PointInside(pt) or o.PointOnEdge(pt):
                        best, bd = i, 0
                        break
                    d = o.SquaredDistance(pt)
                    if d < bd:
                        best, bd = i, d
                if best is None or bd > MM(0.3) ** 2:
                    continue
                single = pcbnew.SHAPE_POLY_SET()
                single.AddOutline(fp.Outline(best))
                m = R.mask_polys(R.polys(single), wx0, wy0, w, h)
                m = ndimage.binary_erosion(m, iterations=2)
                if m.any():
                    out[LI[l]] = (m, None, 0)
            return out
        c = it.GetStart() if cls in ('PCB_TRACK', 'PCB_ARC') else it.GetPosition()
        cx, cy = R.px(c.x, c.y)
        ctr = (int(round(cy)) - wy0, int(round(cx)) - wx0)
        if not (0 <= ctr[0] < h and 0 <= ctr[1] < w):
            ctr = None
        for l in LAYERS:
            if not it.IsOnLayer(l):
                continue
            need = 0
            if cls == 'PCB_VIA' and not it.FlashLayer(l):
                need = TOMM(it.GetWidth(pcbnew.F_Cu))       # may connect here if its pad fits
                ps = pcbnew.SHAPE_POLY_SET()
                it.TransformShapeToPolygon(ps, pcbnew.F_Cu, 0, MM(0.003), pcbnew.ERROR_OUTSIDE)
            elif cls == 'PAD' and not it.FlashLayer(l):
                continue
            else:
                ps = Raster.item_poly(it, l)
            m = R.mask_polys(R.polys(ps), wx0, wy0, w, h)
            e = ndimage.binary_erosion(m, iterations=2)
            if not e.any() and ctr is not None:
                e = np.zeros_like(m)
                e[ctr] = True
            out[LI[l]] = (e, ctr, need)
        return out

    def route(self, conn_id, A, B, posA, posB, max_margin=8.0):
        netcode = A.GetNetCode()
        name = A.GetNetname()
        tw, clr, power = net_class(name)
        if name == 'GND':
            allowed = tuple(range(len(LAYERS)))
        elif power:
            allowed = SIG + PWR_LAYERS
        else:
            allowed = SIG
        widths = [tw] if not power else [tw, 0.12]
        R = self.R
        for margin in (self.margin, max_margin):
            xs = (posA[0], posB[0]); ys = (posA[1], posB[1])
            ext = [it.GetBoundingBox() for it in (A, B) if it.GetClass() != 'ZONE']
            bx0 = min(xs + tuple(TOMM(e.GetLeft()) for e in ext)) - margin
            bx1 = max(xs + tuple(TOMM(e.GetRight()) for e in ext)) + margin
            by0 = min(ys + tuple(TOMM(e.GetTop()) for e in ext)) - margin
            by1 = max(ys + tuple(TOMM(e.GetBottom()) for e in ext)) + margin
            wx0 = max(int((bx0 - X0) / R.res), 0); wx1 = min(int((bx1 - X0) / R.res) + 1, R.W)
            wy0 = max(int((by0 - Y0) / R.res), 0); wy1 = min(int((by1 - Y0) / R.res) + 1, R.H)
            w, h = wx1 - wx0, wy1 - wy0
            src = self.item_cells(A, posA, wx0, wy0, w, h)
            dst = self.item_cells(B, posB, wx0, wy0, w, h)
            if not src or not dst:
                return 'no-cells'
            deff = self.dist_maps(netcode, clr, allowed, wx0, wy0, w, h)
            for tw_try in widths:
                for vd, vdr in VIAS:
                    res = self.search(conn_id, netcode, name, tw_try, clr, vd, vdr, allowed, src, dst,
                                      deff, wx0, wy0, w, h)
                    if res == 'ok':
                        return 'ok'
        return 'fail'

    def dist_maps(self, net, own_clr, allowed, wx0, wy0, w, h, fixed_only=False):
        """Per layer: distance (mm) from each cell to the nearest other-net copper minus the
        required clearance. Track fits where deff >= w/2, a via pad where deff >= D/2.
        Computed on the window plus a 1 mm apron so copper just outside it still counts."""
        R = self.R
        ap = int(round(1.0 / R.res))
        px0, py0 = max(wx0 - ap, 0), max(wy0 - ap, 0)
        px1, py1 = min(wx0 + w + ap, R.W), min(wy0 + h + ap, R.H)
        sl = (slice(py0, py1), slice(px0, px1))
        crop = (slice(wy0 - py0, wy0 - py0 + h), slice(wx0 - px0, wx0 - px0 + w))
        H2, W2 = py1 - py0, px1 - px0
        edge = R.edge[sl]
        de = (ndimage.distance_transform_edt(edge == 0) * R.res - EDGE_CLR)[crop] if edge.any() else None
        out, hole_eff = {}, None
        hm = R.holes[sl]
        if fixed_only:                    # rip-up mode: routed copper is not an obstacle here
            hm = np.where(R.hsoft[sl] != 0, 0, hm)
        fh = (hm != 0) & (hm != net)
        dfh = (ndimage.distance_transform_edt(~fh) * R.res - HOLE_CLR)[crop] if fh.any() else None
        for li in range(len(LAYERS)):
            hn, hc = R.hard[li][sl], R.clr[li][sl]
            foreign = (hn != 0) & (hn != net)
            if fixed_only:
                foreign &= R.soft[li][sl] != hn
            d = np.full((h, w), 1e3, np.float32)
            dh = np.full((h, w), 1e3, np.float32)
            if foreign.any():
                for cv in np.unique(hc[foreign]):
                    m = foreign & (hc == cv)
                    e = (ndimage.distance_transform_edt(~m) * R.res)[crop]
                    d = np.minimum(d, e - max(cv / 100.0, own_clr))
                    dh = np.minimum(dh, e - HOLE_CLR)
            if de is not None:
                d = np.minimum(d, de)
            if dfh is not None:               # copper to other-net drill: hole clearance
                d = np.minimum(d, dfh)
            hole_eff = dh if hole_eff is None else np.minimum(hole_eff, dh)
            dz = d
            zn = R.zone[li][sl]
            zf = (zn != 0) & (zn != net)
            if zf.any() and li in allowed and li not in SIG:
                dz = np.minimum(d, (ndimage.distance_transform_edt(~zf) * R.res)[crop] - max(0.10, own_clr))
            out[li] = (d, dz)
        dhole = (ndimage.distance_transform_edt(hm == 0) * R.res - HOLE2HOLE)[crop] if hm.any() \
            else np.full((h, w), 1e3)
        wsl = (slice(wy0, wy0 + h), slice(wx0, wx0 + w))
        oh = hm == net
        out['ownhole'] = (ndimage.distance_transform_edt(~oh) * R.res - HOLE_CLR)[crop] if oh.any() else None
        out['hole'] = (hole_eff, dhole, (R.nopadvia[wsl] == 0) & (R.viakeep[wsl] == 0))
        if de is not None:
            out['edge'] = de
        return out

    def masks(self, net, tw, vd, vdr, allowed, src, dst, deff, wx0, wy0, w, h):
        """Track/via feasibility from distance maps: (blocked[L], padok[L], holeok, lcost[L])."""
        R, L = self.R, len(LAYERS)
        mg = 1.0 * R.res
        blocked = np.ones((L, h, w), np.uint8)
        padok = np.zeros((L, h, w), np.uint8)
        lcost = np.zeros(L, np.float32)
        for li in allowed:
            d, dz = deff[li]
            blocked[li] = dz < tw / 2 + mg
            padok[li] = d >= vd / 2 + mg
            lcost[li] = 1.0
        # Own-net vias without a pad on a layer: touching one there would make KiCad add the
        # pad (and its clearance) after the fact, so keep hole clearance from them as well,
        # except around this connection's own end items.
        if deff['ownhole'] is not None:
            ob = deff['ownhole'] < tw / 2 + mg
            yy, xx = np.ogrid[:h, :w]
            rr = (0.18 + HOLE_CLR + tw / 2) / R.res + 2
            for cells in (src, dst):
                for li, (m, ctr, need) in cells.items():
                    if ctr is not None:
                        ob &= (yy - ctr[0]) ** 2 + (xx - ctr[1]) ** 2 > rr * rr
            for li in allowed:
                own = R.hard[li][wy0:wy0 + h, wx0:wx0 + w] == net
                blocked[li] |= (ob & ~own).astype(np.uint8)
        hole_eff, dhole, nv = deff['hole']
        holeok = ((hole_eff >= vdr / 2 + mg) & (dhole >= vdr / 2 + mg) & nv).astype(np.uint8)
        if 'edge' in deff:
            holeok &= (deff['edge'] >= vd / 2 + mg).astype(np.uint8)
        return blocked, padok, holeok, lcost

    def search(self, conn_id, net, name, tw, clr, vd, vdr, allowed, src, dst, deff, wx0, wy0, w, h):
        R, L = self.R, len(LAYERS)
        mg = 1.0 * R.res
        blocked, padok, holeok, lcost = self.masks(net, tw, vd, vdr, allowed, src, dst, deff, wx0, wy0, w, h)
        pen = vpen = None
        if getattr(self, 'rip', False):
            # rip-up mode: only fixed copper blocks; crossing routed copper costs rip_pen per cell
            fixed = self.dist_maps(net, clr, allowed, wx0, wy0, w, h, fixed_only=True)
            fb, fp, fh, _ = self.masks(net, tw, vd, vdr, allowed, src, dst, fixed, wx0, wy0, w, h)
            pen = np.ascontiguousarray(((blocked != 0) & (fb == 0)).astype(np.uint8))
            vpen = np.ascontiguousarray((((holeok == 0) | (padok[list(allowed)] == 0).any(axis=0))
                                         & (fh != 0)).astype(np.uint8))
            blocked, padok, holeok = fb, fp, fh
        st = np.zeros((L, h, w), np.uint8)
        tgt_any = False
        for which, cells in ((1, src), (2, dst)):
            for li, (m, ctr, need) in cells.items():
                if lcost[li] == 0:
                    continue
                if need and (ctr is None or deff[li][0][ctr] < need / 2 + mg):
                    continue                        # unflashed via layer where its pad would not fit
                free = m & (blocked[li] == 0)
                if not free.any():
                    if ctr is None or not m[ctr]:
                        continue
                    blocked[li][ctr] = 0            # own pad centre: always a valid end point
                    free = np.zeros_like(m)
                    free[ctr] = True
                st[li][free & (st[li] == 0)] = which
                tgt_any = tgt_any or which == 2
        if not tgt_any:
            return 'no-target'
        ty, tx = np.nonzero(np.any(st == 2, axis=0))
        out = np.zeros(3 * w * h, np.int32)
        need = (vdr + HOLE2HOLE) / R.res + 1.0          # min via-to-via spacing, cells
        for attempt in range(8):
            n = lib.astar(L, h, w, np.ascontiguousarray(blocked), np.ascontiguousarray(padok), holeok,
                          np.ascontiguousarray(st), lcost, ctypes.c_float(1.2 / R.res), ctypes.c_float(0.3),
                          int(ty.min()), int(tx.min()), int(ty.max()), int(tx.max()), out, w * h, 6_000_000,
                          None if pen is None else pen.ctypes.data, None if vpen is None else vpen.ctypes.data,
                          ctypes.c_float(getattr(self, 'rip_pen', 0.0)))
            if n <= 0:
                return 'nopath'
            path = out[:3 * n].reshape(n, 3)[::-1].copy()      # source -> target
            vias = [(int(path[k][1]), int(path[k][2])) for k in range(1, n) if path[k][0] != path[k - 1][0]]
            clash = next((q for i, p in enumerate(vias) for q in vias[i + 1:]
                          if 0 < math.hypot(p[0] - q[0], p[1] - q[1]) < need), None)
            if clash is None:
                sp = blocked
                if pen is not None:            # shortcuts may not cross more routed copper than the path did
                    sp = blocked | pen
                    sp[path[:, 0], path[:, 1], path[:, 2]] = 0
                self.commit(conn_id, net, path, sp, tw, clr, vd, vdr, wx0, wy0)
                return 'ok'
            r = int(need) + 1                                  # two vias of this path too close: forbid one
            holeok[max(clash[0] - r, 0):clash[0] + r + 1, max(clash[1] - r, 0):clash[1] + r + 1] = 0
        return 'nopath'

    def flash_vias(self, net, li, a, c, tw, clr):
        """A track ending on an existing via makes KiCad add that via's pad on this layer;
        stamp the pad so later routes keep pad clearance, not just hole clearance."""
        R = self.R
        for vx, vy, vr, v in self.vias_by_net.get(net, ()):
            dx, dy = c[0] - a[0], c[1] - a[1]
            L2 = dx * dx + dy * dy
            t = 0 if L2 == 0 else max(0.0, min(1.0, ((vx - a[0]) * dx + (vy - a[1]) * dy) / L2))
            if math.hypot(vx - a[0] - t * dx, vy - a[1] - t * dy) <= vr + tw / 2:
                sl, m = R.stamp_disc(R.hard[li], (vx, vy), vr, net)
                region = R.clr[li][sl]
                region[m] = np.maximum(region[m], int(round(clr * 100)))

    def commit(self, conn_id, net, path, blocked, tw, clr, vd, vdr, wx0, wy0):
        R = self.R
        b = self.b
        netinfo = b.FindNet(net)

        def mm(y, x):
            return (float(X0 + (wx0 + x + 0.5) * R.res), float(Y0 + (wy0 + y + 0.5) * R.res))

        strict = {}

        def free_line(li, p, q):
            # straight shortcuts must clear a 1-cell dilated obstacle map, so sampling and
            # rounding along an any-angle segment can never eat into the clearance
            if li not in strict:
                strict[li] = ndimage.binary_dilation(blocked[li].astype(bool))
            sb = strict[li]
            n = int(max(abs(q[0] - p[0]), abs(q[1] - p[1])) * 3) + 1
            for k in range(1, n):
                y = int(round(p[0] + (q[0] - p[0]) * k / n)); x = int(round(p[1] + (q[1] - p[1]) * k / n))
                if sb[y, x]:
                    return False
            return True

        runs, cur = [], [tuple(path[0])]
        for k in range(1, len(path)):
            if path[k][0] != path[k - 1][0]:
                runs.append(cur); cur = [tuple(path[k])]
            else:
                cur.append(tuple(path[k]))
        runs.append(cur)
        segs, vias = [], []
        for ri, run in enumerate(runs):
            li = run[0][0]
            pts = [(int(p[1]), int(p[2])) for p in run]
            if ri > 0:
                vias.append(pts[0])
            i = 0
            while i < len(pts) - 1:
                j = len(pts) - 1
                while j > i + 1 and not free_line(li, pts[i], pts[j]):
                    j -= 1
                segs.append((li, pts[i], pts[j]))
                i = j
        for li, p, q in segs:
            a, c = mm(*p), mm(*q)
            if a == c:
                continue
            t = pcbnew.PCB_TRACK(b)
            t.SetStart(pcbnew.VECTOR2I(MM(a[0]), MM(a[1])))
            t.SetEnd(pcbnew.VECTOR2I(MM(c[0]), MM(c[1])))
            t.SetWidth(MM(tw))
            t.SetLayer(LAYERS[li])
            t.SetNet(netinfo)
            b.Add(t)
            R.stamp_segment(li, a, c, tw, net, clr)
            R.register(t)
            self.flash_vias(net, li, a, c, tw, clr)
            self.added.append((conn_id, t))
            self.patch.append({'conn': conn_id, 'type': 'track', 'net': netinfo.GetNetname(),
                               'layer': b.GetLayerName(LAYERS[li]), 'start': a, 'end': c, 'width': tw})
        for p in vias:
            c = mm(*p)
            v = pcbnew.PCB_VIA(b)
            v.SetPosition(pcbnew.VECTOR2I(MM(c[0]), MM(c[1])))
            v.SetViaType(pcbnew.VIATYPE_THROUGH)
            v.SetWidth(MM(vd))
            v.SetDrill(MM(vdr))
            v.SetNet(netinfo)
            v.Padstack().SetUnconnectedLayerMode(pcbnew.PADSTACK.UNCONNECTED_LAYER_MODE_REMOVE_ALL)
            b.Add(v)
            # a via with unconnected pads removed still blocks every layer with its hole;
            # stamp it as copper on all layers (conservative) so later routes keep clear
            for li in range(len(LAYERS)):
                sl, m = R.stamp_disc(R.hard[li], c, vd / 2, net)
                R.soft[li][sl][m] = net
                region = R.clr[li][sl]
                region[m] = np.maximum(region[m], int(round(clr * 100)))
            sl, m = R.stamp_disc(R.holes, c, vdr / 2, net)
            R.hsoft[sl][m] = 1
            R.register(v)
            self.vias_by_net.setdefault(net, []).append((c[0], c[1], vd / 2, v))
            self.added.append((conn_id, v))
            self.patch.append({'conn': conn_id, 'type': 'via', 'net': netinfo.GetNetname(), 'pos': c,
                               'size': vd, 'drill': vdr})


def run_drc(path, out):
    subprocess.run(['kicad-cli', 'pcb', 'drc', '--format', 'json', '--severity-all', '-o', out, path],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return json.load(open(out))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('inp'); ap.add_argument('out')
    ap.add_argument('--drc', help='existing DRC json for INP (else run kicad-cli)')
    ap.add_argument('--nets', default='.', help='regex: only route these nets')
    ap.add_argument('--exclude', default='^$', help='regex: skip these nets')
    ap.add_argument('--res', type=float, default=0.025)
    ap.add_argument('--margin', type=float, default=2.5, help='window margin around a connection (mm)')
    ap.add_argument('--patch', help='write added items as JSON here')
    ap.add_argument('--limit', type=int, default=0)
    a = ap.parse_args()

    b = pcbnew.LoadBoard(a.inp)
    drc = json.load(open(a.drc)) if a.drc else run_drc(a.inp, a.out + '.drc_in.json')
    r = Router(b, a.res, a.margin)
    conns = []
    for k, u in enumerate(drc['unconnected_items']):
        ia, ib = u['items']
        A, B = r.byuuid.get(ia['uuid']), r.byuuid.get(ib['uuid'])
        if A is None or B is None:
            continue
        name = A.GetNetname()
        if not re.search(a.nets, name) or re.search(a.exclude, name):
            continue
        pa, pb = (ia['pos']['x'], ia['pos']['y']), (ib['pos']['x'], ib['pos']['y'])
        conns.append((math.dist(pa, pb), k, A, B, pa, pb, name))
    conns.sort(key=lambda c: c[0])
    if a.limit:
        conns = conns[:a.limit]
    print(f'{len(conns)} connections to route', flush=True)
    stats = {}
    t0 = time.time()
    for n, (dist, k, A, B, pa, pb, name) in enumerate(conns):
        # zone items: route from the pad/track side so the zone island is the target
        if A.GetClass() == 'ZONE' and B.GetClass() != 'ZONE':
            A, B, pa, pb = B, A, pb, pa
        try:
            res = r.route(k, A, B, pa, pb)
        except Exception as e:      # keep going; report
            res = f'error:{e}'
        stats[res] = stats.get(res, 0) + 1
        print(f'[{n + 1}/{len(conns)}] {name:24s} {dist:6.2f} mm  {res}  ({time.time() - t0:.0f} s)', flush=True)
    print('result:', stats, flush=True)
    pcbnew.SaveBoard(a.out, b)
    if a.patch:
        json.dump(r.patch, open(a.patch, 'w'), indent=0)


if __name__ == '__main__':
    main()
