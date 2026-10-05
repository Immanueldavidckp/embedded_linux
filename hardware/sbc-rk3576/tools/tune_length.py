#!/usr/bin/env python3
"""Automatic length tuning: the scripted equivalent of KiCad's "Tune length".

    python3 tune_length.py IN.kicad_pcb OUT.kicad_pcb [--report out.md] [--drc in.json]
                           [--groups REGEX] [--partial] [--amax 1.0] [--gap 3] [--bump-min 1]

Why: the autorouters connect nets; nothing matched their lengths (fab/length_report.md).
LPDDR5 byte lanes must sit within +-0.5 mm (CA +-1 mm) and pairs need <0.1-0.15 mm skew,
so every short member needs meanders, and on this board free space is the limit.

How
  1. Groups and tolerances are length_report.py's, with the same metric (copper length
     per net). Target = the group's longest member. Groups with a member that KiCad's
     DRC still reports open are skipped (--partial: tune their fully routed members).
  2. For each straight segment of a short member, look up free space on both sides in
     maze_route.Raster: distance to other-net copper minus clearance (netclass), to
     drills (0.12), to the edge (0.3), and to the net's own copper (meander gap).
     That gives the free height of each side along the segment (a "skyline").
  3. Accordion meander: legs every pitch = w + gap*w (gap 3w edge-to-edge), each plateau
     left / on the line / right at the height its skyline allows (amplitude >= 3w,
     <= amax); a small DP picks the plateau sides that add the most length. 45-degree
     chamfered corners. The pattern is trimmed (prefix + bisection on one amplitude) to
     the target. Residuals smaller than one meander bump get a single 45-degree bump
     (pairs: height >= bump-min*w, it has no parallel legs to couple).
     Pairs tune the short leg, starting at the end where the skew builds up.
  4. Every new track is checked against the exact KiCad shapes nearby (clearance, hole
     clearance), stamped into the raster, and the original segment is shortened (never
     removed), so connectivity cannot change.
  5. Save, KiCad DRC; meanders involved in new clearance/drill/short/crossing errors are
     reverted (separate process) until no count is above the input's. Report.
"""
import argparse, json, math, os, re, shutil, subprocess, sys
from collections import defaultdict
import numpy as np
from scipy import ndimage
import pcbnew
import maze_route as M
import length_report as LR

MM, TOMM = pcbnew.FromMM, pcbnew.ToMM
BAD = ('clearance', 'hole_clearance', 'shorting_items', 'tracks_crossing', 'copper_edge_clearance',
       'hole_to_hole')
GRAVE = []                  # removed items must outlive the process (SWIG, see maze_ripup.py)
SQ2 = math.sqrt(2)


def groups():
    """[(name, kind, nets, tol)]: 'lane' = max-min spread <= tol, 'pair' = skew <= tol."""
    g = []
    for ch in 'AB':
        for byte, dqs in ((0, range(0, 8)), (1, range(8, 16))):
            g.append((f'{ch}{byte}', 'lane', [f'LP5_DQ{i}_{ch}' for i in dqs] + [f'LP5_DMI{byte}_{ch}'],
                      2 * LR.DDR_TOL))
        g.append((f'CA_{ch}', 'lane', [f'LP5_A{i}_{ch}' for i in range(7)] + [f'LP5_CSN0_{ch}', f'LP5_CSN1_{ch}'],
                  2 * LR.CA_TOL))
    for pat, tol in LR.PAIRS:
        for ch in 'AB':
            g.append((pat.format('', ch), 'pair', [pat.format('P', ch), pat.format('N', ch)], tol))
    g += [(os.path.commonprefix([p, n]).rstrip('_'), 'pair', [p, n], 0.15) for p, n in LR.OTHER_PAIRS]
    return g


def chamfer(pts, c):
    """45-degree chamfer of size <= c at every corner (never more than half a side)."""
    out = [pts[0]]
    for k in range(1, len(pts) - 1):
        p, q, r = np.array(pts[k - 1]), np.array(pts[k]), np.array(pts[k + 1])
        l1, l2 = np.linalg.norm(q - p), np.linalg.norm(r - q)
        cc = min(c, l1 / 2, l2 / 2)
        out += [tuple(q - (q - p) / l1 * cc), tuple(q + (r - q) / l2 * cc)]
    return out + [pts[-1]]


def polylen(pts):
    return sum(math.dist(pts[k], pts[k + 1]) for k in range(len(pts) - 1))


def accordion(legs, h, L):
    """Local (u, v) polyline of a segment of length L with plateau heights h between legs."""
    pts, prev = [(0.0, 0.0)], 0.0
    for i, hi in enumerate(list(h) + [0.0]):
        if hi != prev:
            pts += [(legs[i], prev), (legs[i], hi)]
            prev = hi
    pts.append((L, 0.0))
    return pts


class Tuner:
    def __init__(self, b, a):
        self.b, self.a, self.res = b, a, a.res
        self.R = M.Raster(b, a.res)
        self.items = defaultdict(list)                  # net -> tracks, vias, pads
        for t in b.GetTracks():
            self.items[t.GetNetCode()].append(t)
        for f in b.GetFootprints():
            for p in f.Pads():
                self.items[p.GetNetCode()].append(p)
        self.L = LR.net_lengths(b)
        self.records = []

    # -- free space ----------------------------------------------------------
    def free_map(self, seg, li, net, clr, gap_own, x0, y0, x1, y1):
        """Window (cells) and distance (mm) from each cell to the nearest copper this net's
        track centre must stay away from, minus the required clearance."""
        R, res = self.R, self.res
        wx0, wy0 = max(int((x0 - M.X0) / res), 0), max(int((y0 - M.Y0) / res), 0)
        wx1, wy1 = min(int((x1 - M.X0) / res) + 1, R.W), min(int((y1 - M.Y0) / res) + 1, R.H)
        ap = int(round(1.0 / res))
        px0, py0, px1, py1 = max(wx0 - ap, 0), max(wy0 - ap, 0), min(wx1 + ap, R.W), min(wy1 + ap, R.H)
        sl = (slice(py0, py1), slice(px0, px1))
        crop = (slice(wy0 - py0, wy1 - py0), slice(wx0 - px0, wx1 - px0))
        D = np.full((wy1 - wy0, wx1 - wx0), 1e3, np.float32)

        def near(mask, sub):
            if mask.any():
                np.minimum(D, (ndimage.distance_transform_edt(~mask) * res)[crop] - sub, out=D)
        hn, hc = R.hard[li][sl], R.clr[li][sl]
        foreign = (hn != 0) & (hn != net)
        for cv in np.unique(hc[foreign]):
            near(foreign & (hc == cv), max(cv / 100.0, clr))
        zn = R.zone[li][sl]
        near((zn != 0) & (zn != net), max(clr, 0.10))
        near(R.holes[sl] != 0, M.HOLE_CLR)              # any drill, own vias included
        near(R.edge[sl] != 0, M.EDGE_CLR)
        own = np.zeros((py1 - py0, px1 - px0), bool)    # own copper except this segment
        L = M.LAYERS[li]
        for it in self.items[net]:
            bb = it.GetBoundingBox()
            if it is seg or TOMM(bb.GetRight()) < x0 - 1 or TOMM(bb.GetLeft()) > x1 + 1 or \
                    TOMM(bb.GetBottom()) < y0 - 1 or TOMM(bb.GetTop()) > y1 + 1:
                continue
            if it.GetClass() == 'PCB_VIA':                # touching it would flash its pad here
                ps = M.Raster.item_poly(it, pcbnew.F_Cu)
            elif it.IsOnLayer(L):
                ps = M.Raster.item_poly(it, L)
            else:
                continue
            own |= R.mask_polys(R.polys(ps), px0, py0, px1 - px0, py1 - py0)
        near(own, gap_own)
        return D, wx0, wy0

    def skyline(self, D, wx0, wy0, A, t, n, L, thr):
        """Free height (mm) on the left (+n) and right (-n) side at each u sample."""
        res = self.res
        us = np.arange(0.0, L + 1e-9, res)
        vs = np.arange(2 * res, self.a.amax + 1e-9, res)
        out = []
        for sg in (1, -1):
            X = A[0] + us[:, None] * t[0] + sg * vs[None, :] * n[0]
            Y = A[1] + us[:, None] * t[1] + sg * vs[None, :] * n[1]
            ix = np.floor((X - M.X0) / res).astype(int) - wx0
            iy = np.floor((Y - M.Y0) / res).astype(int) - wy0
            ok = (ix >= 0) & (iy >= 0) & (ix < D.shape[1]) & (iy < D.shape[0])
            f = np.zeros(X.shape, bool)
            f[ok] = D[iy[ok], ix[ok]] >= thr
            first = np.where((~f).any(1), (~f).argmax(1), len(vs))
            out.append(np.where(first == 0, 0.0, vs[np.maximum(first - 1, 0)]))
        return us, out[0], out[1]

    # -- exact check ---------------------------------------------------------
    def collides(self, pts_nm, li, w, net, clr):
        """Index of the first new segment that violates clearance/hole clearance, else -1."""
        L = M.LAYERS[li]
        for k in range(len(pts_nm) - 1):
            a, c = pcbnew.VECTOR2I(*pts_nm[k]), pcbnew.VECTOR2I(*pts_nm[k + 1])
            s = pcbnew.SHAPE_SEGMENT(a, c, MM(w))
            x0, x1 = sorted((pts_nm[k][0], pts_nm[k + 1][0])); y0, y1 = sorted((pts_nm[k][1], pts_nm[k + 1][1]))
            for o in self.R.query(TOMM(x0) - 0.6, TOMM(y0) - 0.6, TOMM(x1) + 0.6, TOMM(y1) + 0.6):
                cls = o.GetClass()
                if o.GetNetCode() != net and o.IsOnLayer(L) and (cls == 'PCB_TRACK' or o.FlashLayer(L)):
                    cv = max(clr, TOMM(o.GetOwnClearance(L)))
                    if s.Collide(o.GetEffectiveShape(L), MM(cv) + 1000):
                        return k
                if cls in ('PCB_VIA', 'PAD') and o.HasHole() and \
                        s.Collide(o.GetEffectiveHoleShape(), MM(M.HOLE_CLR) + 1000):
                    if o.GetNetCode() != net or not o.IsOnLayer(L) or not o.FlashLayer(L):
                        return k
        return -1

    # -- planning ------------------------------------------------------------
    def plan_accordion(self, us, Al, Ar, L, w, aim, from_end):
        """Plateau heights (DP over left/zero/right per plateau), trimmed to add ~aim mm."""
        a, s = self.a, w * (1 + self.a.gap)
        amin, c = 3 * w, s / 4
        K = int((L - 2 * self.res) // s)
        if K < 1:
            return None
        legs = (L - K * s) / 2 + s * np.arange(K + 1)
        opts = []
        for i in range(K):
            m = (us >= legs[i] - self.res) & (us <= legs[i + 1] + self.res)
            hl, hr = (math.floor(min(x[m].min(), a.amax) * 100) / 100 for x in (Al, Ar))
            opts.append([0.0] + ([hl] if hl >= amin else []) + ([-hr] if hr >= amin else []))
        best = {0.0: (0.0, [])}
        for o in opts:
            nb = {}
            for h in o:
                v, pp = max(((pv + abs(h - ph), pp) for ph, (pv, pp) in best.items()), key=lambda z: z[0])
                nb[h] = (v, pp + [h])
            best = nb
        H = max(((v + abs(h), p) for h, (v, p) in best.items()), key=lambda z: z[0])[1]
        if not any(H):
            return None

        def f(h):
            return polylen(chamfer(accordion(legs, h, L), c)) - L
        order = list(range(K))[::-1] if from_end else list(range(K))
        if f(H) > aim:                                  # trim: shortest prefix, then one amplitude
            h = [0.0] * K
            for k, i in enumerate(order):
                h[i] = H[i]
                if f(h) >= aim:
                    break
            for i in reversed(order[:k + 1]):
                if h[i] == 0:
                    continue
                top, sg = abs(h[i]), math.copysign(1, h[i])
                h[i] = sg * amin
                if f(h) <= aim:
                    lo, hi = amin, top
                    for _ in range(30):
                        mid = (lo + hi) / 2
                        h[i] = sg * mid
                        lo, hi = (mid, hi) if f(h) < aim else (lo, mid)
                    h[i] = sg * lo
                    break
            H = h
        return chamfer(accordion(legs, H, L), c), f(H)

    def plan_bump(self, us, Al, Ar, L, w, aim, hmin, from_end):
        """One 45-degree trapezoid bump: adds 2h(sqrt2-1) mm."""
        h = min(max(aim / (2 * (SQ2 - 1)), hmin), self.a.amax)
        flat = w * (1 + self.a.gap)
        span = 2 * h + flat
        starts = np.arange(2 * self.res, L - span - 2 * self.res, self.res)
        if from_end:
            starts = starts[::-1]
        for u0 in starts:
            m = (us >= u0 - self.res) & (us <= u0 + span + self.res)
            for sg, prof in ((1, Al), (-1, Ar)):
                if prof[m].min() >= h:
                    pts = [(0.0, 0.0), (u0, 0.0), (u0 + h, sg * h), (u0 + h + flat, sg * h), (u0 + span, 0.0),
                           (L, 0.0)]
                    return pts, polylen(pts) - L
        return None

    def tune_segment(self, seg, aim, hi, bump_min, from_end_pt):
        """Add up to ~aim (never more than hi) mm to one segment; returns mm added."""
        net, li = seg.GetNetCode(), M.LI[seg.GetLayer()]
        w = TOMM(seg.GetWidth())
        _, clr, _ = M.net_class(seg.GetNetname())
        clr = max(clr, TOMM(seg.GetOwnClearance(seg.GetLayer())))
        A = np.array([TOMM(seg.GetStart().x), TOMM(seg.GetStart().y)])
        B = np.array([TOMM(seg.GetEnd().x), TOMM(seg.GetEnd().y)])
        L = float(np.linalg.norm(B - A))
        if L < 1.5 * w * (1 + self.a.gap):
            return 0.0
        t = (B - A) / L
        n = np.array([-t[1], t[0]])
        from_end = from_end_pt is not None and np.linalg.norm(B - from_end_pt) < np.linalg.norm(A - from_end_pt)
        pad = self.a.amax + 0.2
        D, wx0, wy0 = self.free_map(seg, li, net, clr, self.a.gap * w, min(A[0], B[0]) - pad,
                                    min(A[1], B[1]) - pad, max(A[0], B[0]) + pad, max(A[1], B[1]) + pad)
        us, Al, Ar = self.skyline(D, wx0, wy0, A, t, n, L, w / 2 + 1.5 * self.res)
        for attempt in range(6):
            p = self.plan_accordion(us, Al, Ar, L, w, aim, from_end)
            if p is None or p[1] > hi:              # residual below one meander bump
                p = self.plan_bump(us, Al, Ar, L, w, aim, 3 * w if bump_min is None else bump_min, from_end)
            if p is None or p[1] > hi or p[1] <= 0.005:
                return 0.0
            pts, extra = p
            g = [A + u * t + v * n for u, v in pts]
            nm = [(int(round(x * 1e6)), int(round(y * 1e6))) for x, y in g]
            nm[0], nm[-1] = (seg.GetStart().x, seg.GetStart().y), (seg.GetEnd().x, seg.GetEnd().y)
            k = self.collides(nm[1:], li, w, net, clr)
            if k < 0:
                break
            u = [pts[1 + k][0], pts[2 + k][0]]          # forbid that stretch, replan
            m = (us >= min(u) - 2 * w) & (us <= max(u) + 2 * w)
            Al[m] = 0; Ar[m] = 0
        else:
            return 0.0
        # commit: shorten the original segment, chain the meander to its old end
        rec = {'net': seg.GetNetname(), 'track': seg.m_Uuid.AsString(), 'end': list(nm[-1]), 'new': [],
               'extra': extra, 'layer': self.b.GetLayerName(seg.GetLayer())}
        seg.SetEnd(pcbnew.VECTOR2I(*nm[1]))
        netinfo = seg.GetNet()
        for k in range(1, len(nm) - 1):
            if nm[k] == nm[k + 1]:
                continue
            tr = pcbnew.PCB_TRACK(self.b)
            tr.SetStart(pcbnew.VECTOR2I(*nm[k])); tr.SetEnd(pcbnew.VECTOR2I(*nm[k + 1]))
            tr.SetWidth(seg.GetWidth()); tr.SetLayer(seg.GetLayer()); tr.SetNet(netinfo)
            self.b.Add(tr)
            self.R.stamp_segment(li, (TOMM(nm[k][0]), TOMM(nm[k][1])), (TOMM(nm[k + 1][0]), TOMM(nm[k + 1][1])),
                                 w, net, clr)
            self.R.register(tr)
            self.items[net].append(tr)
            rec['new'].append(tr.m_Uuid.AsString())
        self.records.append(rec)
        self.L[seg.GetNetname()] = self.L.get(seg.GetNetname(), 0) + extra
        return extra

    def segments(self, name):
        return [t for t in self.items[self.b.FindNet(name).GetNetCode()]
                if t.GetClass() == 'PCB_TRACK' and not t.IsLocked() and t.GetLayer() in M.LI]

    def tune_net(self, name, aim_len, max_len, bump_min=None, end_pt=None):
        """Lengthen one net towards aim_len (never beyond max_len)."""
        segs = self.segments(name)
        if end_pt is not None:          # pairs: start where the skew builds up
            segs.sort(key=lambda t: min(math.dist(end_pt, (TOMM(p.x), TOMM(p.y)))
                                        for p in (t.GetStart(), t.GetEnd())))
        else:
            segs.sort(key=lambda t: -t.GetLength())
        for seg in segs:
            aim = aim_len - self.L[name]
            if aim <= 0.01:
                break
            if seg.GetLength() > 0:
                self.tune_segment(seg, aim, max_len - self.L[name], bump_min, end_pt)

    def len_near(self, name, c, r=3.0):
        tot = 0.0
        for t in self.segments(name):
            a, e = np.array([TOMM(t.GetStart().x), TOMM(t.GetStart().y)]), np.array([TOMM(t.GetEnd().x), TOMM(t.GetEnd().y)])
            n = max(int(np.linalg.norm(e - a) / 0.05), 1)
            pts = a + (e - a) * (np.arange(n) + 0.5)[:, None] / n
            tot += np.linalg.norm(e - a) / n * np.count_nonzero(np.hypot(*(pts - c).T) <= r)
        return tot

    def mismatch_end(self, short, long):
        """Pair end (pad pair centroid) where the short leg loses most length locally."""
        pads = lambda nm: [np.array([TOMM(p.GetPosition().x), TOMM(p.GetPosition().y)])
                           for p in self.items[self.b.FindNet(nm).GetNetCode()] if p.GetClass() == 'PAD']
        ps, pl = pads(short), pads(long)
        if not ps or not pl:
            return None
        ends = [(p + min(pl, key=lambda q: np.linalg.norm(q - p))) / 2 for p in ps]
        return max(ends, key=lambda c: self.len_near(long, c) - self.len_near(short, c))


def run_drc(path, out):
    subprocess.run(['kicad-cli', 'pcb', 'drc', '--format', 'json', '--severity-all', '-o', out, path],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return json.load(open(out))


def measure(path):
    """Lengths + unconnected count of a board, in a fresh process (one board per process)."""
    r = subprocess.run([sys.executable, os.path.abspath(__file__), path, path, '--measure'],
                       capture_output=True, text=True, check=True)
    return json.loads(r.stdout.strip().splitlines()[-1])


def revert(path, idx):
    """Undo meanders idx (new tracks removed, original segment end restored)."""
    b = pcbnew.LoadBoard(path)
    recs = json.load(open(path + '.meanders.json'))
    byid = {t.m_Uuid.AsString(): t for t in b.GetTracks()}
    for i in idx:
        r = recs[i]
        for u in r['new']:
            if u in byid:
                b.Remove(byid[u]); GRAVE.append(byid[u])
        byid[r['track']].SetEnd(pcbnew.VECTOR2I(*r['end']))
        r['reverted'] = True
    pcbnew.SaveBoard(path, b)
    json.dump(recs, open(path + '.meanders.json', 'w'), indent=0)
    zl = {r['layer'] for i, r in enumerate(recs) if i in idx}
    if any(b.GetLayerName(l) in zl for z in b.Zones() if not z.GetIsRuleArea() for l in z.GetLayerSet().CuStack()):
        refill(path)


def refill(path):
    subprocess.run([sys.executable, '-c', f'import pcbnew\nb = pcbnew.LoadBoard({path!r})\n'
                    f'pcbnew.ZONE_FILLER(b).Fill(b.Zones())\npcbnew.SaveBoard({path!r}, b)'], check=True)


def counts(drc):
    c = {k: 0 for k in BAD}
    for v in drc['violations']:
        if v['type'] in c:
            c[v['type']] += 1
    return c


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('inp'); ap.add_argument('out')
    ap.add_argument('--report', help='markdown report (default: stdout)')
    ap.add_argument('--drc', help='existing DRC json for IN (else run kicad-cli)')
    ap.add_argument('--groups', default='.', help='regex on group names (A0, CA_B, LP5_CLK_A, HDMI_TX_D0, ...)')
    ap.add_argument('--partial', action='store_true',
                    help='also tune the fully routed members of groups that still have open members')
    ap.add_argument('--res', type=float, default=0.025)
    ap.add_argument('--amax', type=float, default=1.0, help='max meander amplitude (mm)')
    ap.add_argument('--gap', type=float, default=3.0, help='meander leg gap, x track width (edge to edge)')
    ap.add_argument('--bump-min', type=float, default=1.0, help='min skew-bump height on pairs, x track width')
    ap.add_argument('--measure', action='store_true', help=argparse.SUPPRESS)
    ap.add_argument('--revert', help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.measure:
        b = pcbnew.LoadBoard(a.inp)
        c = b.GetConnectivity(); c.RecalculateRatsnest()
        print(json.dumps({'L': LR.net_lengths(b), 'unconnected': c.GetUnconnectedCount(False)}))
        return
    if a.revert:
        return revert(a.inp, [int(x) for x in a.revert.split(',')])

    drc_in = json.load(open(a.drc)) if a.drc else run_drc(a.inp, a.out + '.drc_in.json')
    b = pcbnew.LoadBoard(a.inp)
    c = b.GetConnectivity(); c.RecalculateRatsnest()
    unc_in = c.GetUnconnectedCount(False)
    byid = {t.m_Uuid.AsString(): t.GetNetname() for t in b.GetTracks()}
    byid.update({p.m_Uuid.AsString(): p.GetNetname() for f in b.GetFootprints() for p in f.Pads()})
    byid.update({z.m_Uuid.AsString(): z.GetNetname() for z in b.Zones()})
    open_nets = {byid.get(i['uuid']) for u in drc_in['unconnected_items'] for i in u['items']}
    T = Tuner(b, a)
    L0 = dict(T.L)
    rows = []
    gl = [g for g in groups() if re.search(a.groups, g[0])]
    gl.sort(key=lambda g: g[1] != 'pair')           # pairs first: tight, small
    for name, kind, nets, tol in gl:
        routed = [n for n in nets if n in T.L and n not in open_nets]
        st = {'name': name, 'kind': kind, 'nets': nets, 'tol': tol, 'routed': routed,
              'open': [n for n in nets if n not in routed]}
        rows.append(st)
        if st['open'] and (kind == 'pair' or not a.partial or len(routed) < 2):
            st['skip'] = True
            continue
        target = max(T.L[n] for n in routed)
        st['target'] = target
        if kind == 'pair':
            long_, short = sorted(routed, key=lambda n: -T.L[n])
            if T.L[long_] - T.L[short] > tol:
                end = T.mismatch_end(short, long_)
                T.tune_net(short, target - tol / 2, target, a.bump_min * M.net_class(short)[0], end)
        else:
            for n in sorted(routed, key=lambda n: T.L[n]):
                if target - T.L[n] > tol:
                    T.tune_net(n, target - tol / 4, target)
        print(f'{name:14s} ' + ' '.join(f'{T.L[n] - L0[n]:+.2f}' for n in routed), flush=True)
    pcbnew.SaveBoard(a.out, b)
    shutil.copy(a.inp.replace('.kicad_pcb', '.kicad_pro'), a.out.replace('.kicad_pcb', '.kicad_pro'))
    json.dump(T.records, open(a.out + '.meanders.json', 'w'), indent=0)
    print(f'{len(T.records)} meanders, {sum(r["extra"] for r in T.records):.1f} mm added', flush=True)

    # verify with KiCad: no new clearance-type errors; revert meanders involved in any
    zl = {r['layer'] for r in T.records}
    if any(b.GetLayerName(l) in zl for z in b.Zones() if not z.GetIsRuleArea() for l in z.GetLayerSet().CuStack()):
        refill(a.out)
    c_in, reverted = counts(drc_in), set()
    for it in range(4):
        drc = run_drc(a.out, a.out + '.drc.json')
        c_out = counts(drc)
        if all(c_out[k] <= c_in[k] for k in BAD):
            break
        new = {u: i for i, r in enumerate(T.records) for u in r['new'] if i not in reverted}
        bad = {new[x['uuid']] for v in drc['violations'] if v['type'] in BAD for x in v['items'] if x['uuid'] in new}
        if not bad:
            break
        print(f'DRC: reverting {len(bad)} meander(s) in new violations', flush=True)
        r = subprocess.run([sys.executable, os.path.abspath(__file__), a.out, a.out, '--revert',
                            ','.join(map(str, sorted(bad)))], capture_output=True, text=True)
        print('\n'.join(x for x in (r.stdout + r.stderr).splitlines() if 'memory leak' not in x), flush=True)
        r.check_returncode()
        reverted |= bad
    after = measure(a.out)
    if after['unconnected'] > unc_in:
        print(f'WARNING: unconnected {unc_in} -> {after["unconnected"]}', flush=True)
    write_report(a, rows, L0, after['L'], c_in, c_out, unc_in, after['unconnected'], T.records, reverted)


def write_report(a, rows, L0, L1, c_in, c_out, unc_in, unc_out, recs, reverted):
    def spread(L, nets):
        v = [L[n] for n in nets if n in L]
        return max(v) - min(v) if len(v) > 1 else 0.0
    out = ['# Length tuning report', '',
           f'`tune_length.py {os.path.basename(a.inp)} -> {os.path.basename(a.out)}`: '
           f'{len(recs) - len(reverted)} meanders kept ({len(reverted)} reverted after DRC), '
           f'{sum(r["extra"] for i, r in enumerate(recs) if i not in reverted):.1f} mm of track added. '
           f'Meander gap {a.gap:g}w, amplitude 3w..{a.amax:g} mm, pair skew bumps >= {a.bump_min:g}w.', '',
           '## DRC (KiCad, input -> output)', '', '| check | before | after |', '|---|---:|---:|']
    out += [f'| {k} | {c_in[k]} | {c_out[k]} |' for k in BAD]
    out += [f'| unconnected (ratsnest) | {unc_in} | {unc_out} |', '',
            '## Groups', '', 'Spread = longest - shortest member (lanes), skew = |P - N| (pairs). '
            'Target = longest routed member.', '',
            '| group | routed | tol | before | after | status | notes |', '|---|---:|---:|---:|---:|---|---|']
    for g in rows:
        nets, r = g['nets'], g['routed']
        b0, b1 = f'{spread(L0, r):.2f}' if len(r) > 1 else '-', f'{spread(L1, r):.2f}'
        if g.get('skip'):
            status, note, b1 = 'skipped', 'not fully routed: ' + ', '.join(g['open']), '-'
        else:
            ok = spread(L1, r) <= g['tol'] + 1e-6 and not g['open']
            status = 'OK' if ok else ('partial' if g['open'] else 'OUT')
            short = [(n, g['target'] - L1[n]) for n in r if g['target'] - L1[n] > g['tol']]
            note = ''
            if short:
                rv = {recs[i]['net'] for i in reverted}
                note = 'still short by (mm): ' + ', '.join(
                    f'{n} {d:.2f}' + (' (meander reverted by DRC)' if n in rv else ' (no free space)')
                    for n, d in sorted(short, key=lambda x: -x[1]))
            if g['open']:
                note = ('--partial, open: ' + ', '.join(g['open']) + '. ' + note).strip()
        out.append(f'| {g["name"]} | {len(r)}/{len(nets)} | {g["tol"]:g} | {b0} | {b1} | {status} | {note} |')
    out += ['', '## Members (mm, before -> after, target)', '']
    for g in rows:
        if g.get('skip'):
            continue
        out.append(f'- **{g["name"]}** (target {g["target"]:.2f}): ' + ', '.join(
            f'{n} {L0[n]:.2f}->{L1[n]:.2f}' for n in g['routed'] if abs(L1[n] - L0[n]) > 0.005 or
            g['target'] - L1[n] > g['tol']))
    txt = '\n'.join(out) + '\n'
    if a.report:
        open(a.report, 'w').write(txt)
        print(f'wrote {a.report}')
    else:
        print(txt)


if __name__ == '__main__':
    main()
