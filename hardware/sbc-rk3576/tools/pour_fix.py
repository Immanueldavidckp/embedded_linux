#!/usr/bin/env python3
"""Reshape the power pours so every rail is one connected plane region per layer.

    python3 pour_fix.py IN.kicad_pcb OUT.kicad_pcb [--res 0.05]

Why: pour.py gives each rail the bounding box of its pads and lets the smaller box
win. Under the RK3576 / LPDDR5 some thirty boxes overlap, so a wide rail with few
pads (VCCA_3V3_S0) takes the ball field while the core rails get no copper there,
and other rails come out diced into islands or empty (VDD_DDR_S0, VDD1_DDR_S3).
A layout engineer draws each rail's plane as one shape that reaches all its vias.
This does that on a fine grid per power layer, in "centre space": other-net copper
and holes are grown by their clearance + half the min width, so a free cell is a
place where a min-width strand of the rail fits (the BGA via fields stay passable).
  1. per rail, most local first: a Steiner tree over its vias / own tracks / PTH
     pads (Mehlhorn: geodesic Voronoi of the terminals + MST over the cell borders),
     then a band of clearance + min width around it is reserved for that rail, so
     later rails route around it instead of cutting it;
  2. the rest of the layer is shared out by geodesic Voronoi from those trees, cut
     back by a clearance gap between rails and to the pieces that hold a tree;
  3. each rail's cells become its zone outline (grown by half the min width): solid
     pad connection, 0.10 clearance, 0.09 min width, distinct priorities. The board
     is then refilled in a fresh process (KiCad 9 can crash filling an edited board).
Zones are matched by name (PWR_<net>) and keep their layer, so it runs on any later
version of the board. Vias that no tree can reach are reported and left to routing.
"""
import argparse, math, os, re, subprocess, sys, time
import numpy as np
from PIL import Image, ImageDraw
from scipy import ndimage, sparse
from scipy.sparse import csgraph
import pcbnew

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import zones_strip

MM, TOMM = pcbnew.FromMM, pcbnew.ToMM
CLR, MINW, HOLE_CLR, EDGE_CLR, SLACK = 0.10, 0.09, 0.12, 0.30, 0.025
PEN_NEAR, PEN = 0.35, 4.0          # avoid hugging (and boxing in) other rails' vias


class Grid:
    def __init__(self, b, res):
        bb = b.GetBoardEdgesBoundingBox()
        self.res, self.x0, self.y0 = res, TOMM(bb.GetLeft()) - 0.5, TOMM(bb.GetTop()) - 0.5
        self.W = int(math.ceil((TOMM(bb.GetRight()) + 0.5 - self.x0) / res))
        self.H = int(math.ceil((TOMM(bb.GetBottom()) + 0.5 - self.y0) / res))
        self.sep = 2 * (res / math.sqrt(2) + MINW / 2) + CLR     # centre spacing between rails

    @staticmethod
    def put(arr, sl, m, val):
        """Stamp val; cells already owned by another net become -1 (nobody's)."""
        sub = arr[sl]
        if val < 0:
            sub[m] = -1
            return
        sub[m & (sub != 0) & (sub != val)] = -1
        sub[m & (sub == 0)] = val

    def poly(self, arr, ps, val):
        for i in range(ps.OutlineCount()):
            rings = [ps.COutline(i)] + [ps.CHole(i, j) for j in range(ps.HoleCount(i))]
            pts = [[((r.CPoint(k).x / 1e6 - self.x0) / self.res - .5, (r.CPoint(k).y / 1e6 - self.y0) / self.res - .5)
                    for k in range(r.PointCount())] for r in rings]
            xs, ys = [p[0] for p in pts[0]], [p[1] for p in pts[0]]
            j0, i0 = max(int(min(xs)) - 1, 0), max(int(min(ys)) - 1, 0)
            j1, i1 = min(int(max(xs)) + 2, self.W), min(int(max(ys)) + 2, self.H)
            if j1 <= j0 or i1 <= i0 or len(pts[0]) < 3:
                continue
            im = Image.new('L', (j1 - j0, i1 - i0), 0)
            d = ImageDraw.Draw(im)
            for k, r in enumerate(pts):
                if len(r) >= 3:
                    d.polygon([(x - j0, y - i0) for x, y in r], fill=int(k == 0), outline=int(k == 0))
            self.put(arr, (slice(i0, i1), slice(j0, j1)), np.asarray(im, bool), val)

    def disk(self, arr, x, y, r, val):
        ci, cj, rc = (y - self.y0) / self.res - .5, (x - self.x0) / self.res - .5, r / self.res
        i0, j0 = max(int(ci - rc) - 1, 0), max(int(cj - rc) - 1, 0)
        i1, j1 = min(int(ci + rc) + 2, self.H), min(int(cj + rc) + 2, self.W)
        I, J = np.ogrid[i0:i1, j0:j1]
        self.put(arr, (slice(i0, i1), slice(j0, j1)), (I - ci) ** 2 + (J - cj) ** 2 <= rc * rc, val)


def shape(it, layer, grow, hole=False):
    ps = pcbnew.SHAPE_POLY_SET()
    if hole:
        it.TransformHoleToPolygon(ps, MM(grow), MM(0.005), pcbnew.ERROR_OUTSIDE)
    else:
        it.TransformShapeToPolygon(ps, layer, MM(grow), MM(0.005), pcbnew.ERROR_OUTSIDE)
    return ps


def obstacles(b, G, L, rails):
    """halo: net that may use the cell (0 = anyone, -1 = nobody); term: rail copper to reach."""
    halo = np.zeros((G.H, G.W), np.int32)
    term = np.zeros((G.H, G.W), np.int32)
    g = MINW / 2 + SLACK
    clr = lambda it: max(CLR, TOMM(it.GetOwnClearance(L)))
    ps = pcbnew.SHAPE_POLY_SET()
    b.GetBoardPolygonOutlines(ps)
    inside = np.zeros_like(halo)
    G.poly(inside, ps, 1)
    halo[ndimage.distance_transform_edt(inside) * G.res < EDGE_CLR + g] = -1
    for z in list(b.Zones()) + [z for f in b.GetFootprints() for z in f.Zones()]:
        if not z.IsOnLayer(L) or z.GetZoneName().startswith('PWR_'):
            continue
        if z.GetIsRuleArea():
            if z.GetDoNotAllowCopperPour():
                G.poly(halo, z.Outline(), -1)
        else:                               # foreign pour on a power layer: keep clear of it
            fp = z.GetFilledPolysList(L).CloneDropTriangulation()
            fp.Inflate(MM(CLR + g), pcbnew.CORNER_STRATEGY_CHAMFER_ALL_CORNERS, MM(0.005))
            G.poly(halo, fp, z.GetNetCode() or -1)
    for t in b.GetTracks():
        n = t.GetNetCode() or -1
        if t.GetClass() == 'PCB_VIA':
            x, y = TOMM(t.GetPosition().x), TOMM(t.GetPosition().y)
            rp, rh = TOMM(t.GetWidth(L)) / 2, TOMM(t.GetDrillValue()) / 2
            if n in rails:                  # flashed once its rail's pour reaches it
                G.disk(halo, x, y, rp + clr(t) + g, n)
                G.disk(term, x, y, rp, n)
            else:
                G.disk(halo, x, y, (rp + clr(t) if t.FlashLayer(L) else rh + HOLE_CLR) + g, n)
        elif t.GetLayer() == L:
            G.poly(halo, shape(t, L, clr(t) + g), n)
            if n in rails:
                G.poly(term, shape(t, L, 0), n)
    for f in b.GetFootprints():
        for p in f.Pads():
            if not p.HasHole():
                continue
            npth = p.GetAttribute() == pcbnew.PAD_ATTRIB_NPTH
            n = -1 if npth else (p.GetNetCode() or -1)
            if not npth and p.IsOnLayer(L) and (p.FlashLayer(L) or n in rails):
                G.poly(halo, shape(p, L, clr(p) + g), n)
                if n in rails:
                    G.poly(term, shape(p, L, 0), n)
            G.poly(halo, shape(p, L, HOLE_CLR + g, hole=True), n)
    return halo, term


def graph(ok, cost, diag=True):
    """Undirected grid graph over the True cells of ok; no corner cutting past two blocked cells."""
    H, W = ok.shape
    idx = -np.ones(ok.shape, np.int64)
    idx[ok] = np.arange(int(ok.sum()))
    rows, cols, wts = [], [], []
    for di, dj, s in ((0, 1, 1.0), (1, 0, 1.0)) + (((1, 1, 1.4142), (1, -1, 1.4142)) if diag else ()):
        a = (slice(0, H - di), slice(max(0, -dj), W - max(0, dj)))
        c = (slice(di, H), slice(max(0, dj), W - max(0, -dj)))
        m = ok[a] & ok[c]
        if di and dj:
            m &= ok[a[0], c[1]] | ok[c[0], a[1]]
        rows.append(idx[a][m]); cols.append(idx[c][m]); wts.append(s * 0.5 * (cost[a][m] + cost[c][m]))
    n = int(ok.sum())
    return idx, sparse.csr_matrix((np.concatenate(wts), (np.concatenate(rows), np.concatenate(cols))), shape=(n, n))


def steiner(G, usable, term, cost):
    """Mehlhorn Steiner tree over the terminal components of term (in a window). Returns
    (tree cell mask, number of terminal components, number left unconnected)."""
    lab, nt = ndimage.label(term, np.ones((3, 3)))
    lab[~usable] = 0
    reach = np.unique(lab[lab > 0])
    tree = (lab > 0)
    if len(reach) < 2:
        return tree, nt, nt - len(reach)
    idx, A = graph(usable, cost)
    src = idx[lab > 0]
    dist, pred, origin = csgraph.dijkstra(A, directed=False, indices=src, min_only=True, return_predecessors=True)
    comp = np.zeros(len(dist), np.int64)
    comp[idx[lab > 0]] = lab[lab > 0]
    ok = origin >= 0
    oc = np.where(ok, comp[np.where(ok, origin, 0)], 0)
    A = A.tocoo()
    u, v, w = A.row, A.col, A.data
    m = ok[u] & ok[v] & (oc[u] != oc[v])
    u, v, cst = u[m], v[m], dist[u[m]] + w[m] + dist[v[m]]
    a, c = np.minimum(oc[u], oc[v]), np.maximum(oc[u], oc[v])
    order = np.lexsort((cst, c, a))
    first = np.ones(len(order), bool)
    first[1:] = (a[order][1:] != a[order][:-1]) | (c[order][1:] != c[order][:-1])
    cand = sorted((cst[k], a[k], c[k], u[k], v[k]) for k in order[first])
    par = {k: k for k in reach}

    def find(k):
        while par[k] != k:
            par[k] = par[par[k]]
            k = par[k]
        return k
    cells = np.argwhere(idx >= 0)
    joined = 0
    for _c, ca, cb, cu, cv in cand:
        ra, rb = find(ca), find(cb)
        if ra == rb:
            continue
        par[ra] = rb
        joined += 1
        for s in (cu, cv):
            while s >= 0:
                tree[tuple(cells[s])] = True
                s = pred[s]
    return tree, nt, nt - 1 - joined


def plan_layer(b, G, L, rails, log):
    """rails: {netcode: name}. Returns {netcode: cell mask} of connected regions."""
    t0 = time.time()
    halo, term = obstacles(b, G, L, rails)
    owner_d, owner_i = ndimage.distance_transform_edt(term == 0, return_indices=True)
    owner = term[owner_i[0], owner_i[1]]
    resv = np.zeros_like(halo)          # band reserved around each rail's tree
    core = np.zeros_like(halo)
    sep = int(math.ceil(G.sep / G.res))
    disk = np.hypot(*np.mgrid[-sep:sep + 1, -sep:sep + 1]) <= G.sep / G.res
    order = []
    for n in rails:
        ij = np.argwhere(term == n)
        if len(ij):
            order.append((np.ptp(ij[:, 0]) * np.ptp(ij[:, 1]), n, ij.min(0), ij.max(0)))
    for _a, n, lo, hi in sorted(order, key=lambda o: o[0]):
        pad = int(3.0 / G.res)
        sl = (slice(max(lo[0] - pad, 0), hi[0] + pad + 1), slice(max(lo[1] - pad, 0), hi[1] + pad + 1))
        usable = ((halo[sl] == 0) | (halo[sl] == n)) & ((resv[sl] == 0) | (resv[sl] == n))
        cost = 1.0 + PEN * ((owner_d[sl] * G.res < PEN_NEAR) & (owner[sl] != n))
        tree, nt, left = steiner(G, usable, term[sl] == n, cost)
        tree = ndimage.binary_dilation(tree, [[0, 1, 0], [1, 1, 1], [0, 1, 0]]) & usable
        core[sl][tree] = n
        band = ndimage.binary_dilation(tree, disk) & usable
        resv[sl][band & (resv[sl] == 0)] = n
        if left:
            log.append(f'{b.GetLayerName(L)} {rails[n]}: {left}/{nt} via groups not reachable')
    # share out the rest: geodesic Voronoi from the trees
    ok = (halo == 0) | (resv > 0)
    idx, A = graph(ok, np.ones(halo.shape), diag=False)
    src = idx[core > 0]
    _d, _p, origin = csgraph.dijkstra(A, directed=False, indices=src[src >= 0], min_only=True,
                                      return_predecessors=True)
    lab = np.zeros_like(halo)
    flat = np.zeros(len(origin), np.int32)
    flat[origin >= 0] = core[ok][origin[origin >= 0]]
    lab[ok] = flat
    lab[resv > 0] = resv[resv > 0]
    rail = np.isin(halo, list(rails))
    lab[rail] = halo[rail]

    def keep_trees(lab):
        out = np.zeros_like(lab)
        for n in rails:
            cl, k = ndimage.label(lab == n, np.ones((3, 3)))
            if k:
                hit = np.unique(cl[(core == n) & (cl > 0)])
                out[np.isin(cl, hit[hit > 0])] = n
        return out
    lab = keep_trees(lab)
    diff = np.zeros(lab.shape, bool)
    for a, c in (((slice(None), slice(1, None)), (slice(None), slice(None, -1))),
                 ((slice(1, None), slice(None)), (slice(None, -1), slice(None)))):
        d = (lab[a] > 0) & (lab[c] > 0) & (lab[a] != lab[c])
        diff[a] |= d
        diff[c] |= d
    near = ndimage.distance_transform_edt(~diff) * G.res < (G.sep + G.res) / 2
    lab[near & (core == 0)] = 0
    lab = keep_trees(lab)
    print(f'  {b.GetLayerName(L)}: {len(order)} rails planned in {time.time() - t0:.0f} s', flush=True)
    return {n: lab == n for n in rails}


def outline(G, m):
    """Cell mask -> polygon set (cells as squares, unioned, grown by half the min width)."""
    ps = pcbnew.SHAPE_POLY_SET()
    e = 0.0005
    for i in np.unique(np.nonzero(m)[0]):
        row = np.concatenate(([0], m[i].view(np.int8), [0]))
        d = np.diff(row)
        for j0, j1 in zip(np.nonzero(d == 1)[0], np.nonzero(d == -1)[0]):
            x0, x1 = G.x0 + j0 * G.res, G.x0 + j1 * G.res
            y0, y1 = G.y0 + i * G.res - e, G.y0 + (i + 1) * G.res + e
            ps.NewOutline()
            for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
                ps.Append(MM(x), MM(y))
    ps.Simplify()
    ps.Inflate(MM(MINW / 2), pcbnew.CORNER_STRATEGY_CHAMFER_ALL_CORNERS, MM(0.005), True)
    return ps


def fill(path):
    b = pcbnew.LoadBoard(path)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(path, b)
    c = b.GetConnectivity()
    c.RecalculateRatsnest()
    print(f'filled: {c.GetUnconnectedCount(False)} unconnected')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src')
    ap.add_argument('dst', nargs='?')
    ap.add_argument('--res', type=float, default=0.05)
    ap.add_argument('--fill', action='store_true', help='internal: refill src in this process')
    a = ap.parse_args()
    if a.fill:
        return fill(a.src)
    t0 = time.time()
    b = pcbnew.LoadBoard(a.src)
    G = Grid(b, a.res)
    zones = [z for z in b.Zones() if z.GetZoneName().startswith('PWR_') and not z.GetIsRuleArea()]
    proto = {}
    for z in zones:
        proto.setdefault((z.GetLayer(), z.GetNetCode()), (z.GetNetname(), z.GetIslandRemovalMode(), z.GetMinIslandArea()))
    plans, log = [], []
    for L in sorted({l for l, _n in proto}):
        rails = {n: proto[(l, n)][0] for l, n in proto if l == L}
        plans.append((L, rails, plan_layer(b, G, L, rails, log)))
    zones_strip.strip(a.src, a.dst, ('PWR_',))
    b = pcbnew.LoadBoard(a.dst)
    nets = b.GetNetsByName()
    made = []
    for L, rails, regions in plans:
        for n, m in regions.items():
            if m.any():
                made.append((int(m.sum()), L, n, outline(G, m)))
    made.sort(key=lambda r: r[0])
    for prio, (_a, L, n, ps) in enumerate(reversed(made)):
        name, mode, area = proto[(L, n)]
        z = pcbnew.ZONE(b)
        z.SetLayer(L)
        z.SetNet(nets[name])
        z.SetZoneName(f'PWR_{name}')
        z.SetAssignedPriority(prio + 1)           # smallest region on top (regions do not overlap)
        z.SetLocalClearance(MM(CLR))
        z.SetMinThickness(MM(MINW))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        z.SetIslandRemovalMode(mode)
        z.SetMinIslandArea(area)
        for i in range(ps.OutlineCount()):
            k = z.Outline().AddOutline(ps.COutline(i))
            for j in range(ps.HoleCount(i)):
                z.Outline().AddHole(ps.CHole(i, j), k)
        b.Add(z)
    pcbnew.SaveBoard(a.dst, b)
    print('\n'.join(log))
    print(f'pour_fix: {len(made)} rail regions on {len(plans)} layers in {time.time() - t0:.0f} s; refilling')
    subprocess.run([sys.executable, os.path.abspath(__file__), a.dst, '--fill'], check=True)


if __name__ == '__main__':
    main()
