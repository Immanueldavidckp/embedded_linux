#!/usr/bin/env python3
"""DRC hygiene: remove routing debris without losing a single connection.

    python3 cleanup.py IN.kicad_pcb OUT.kicad_pcb [--drc IN.drc.json] [--all] [--no-drc] [-v]

Freerouting chunks, stitch.py/pour.py and the maze router leave copper that
connects nothing: stubs with a free end, vias that touch copper on one layer
only (mostly rail stitch vias whose pour never reached them), floating bits,
vias drilled too close to another hole. KiCad reports them as track_dangling /
via_dangling / hole_to_hole, and on the inner layers they block the 0.09 mm
channels the maze router needs. NB: DRC stops listing a type at 199 items
(drc_engine ERROR_LIMIT), so "199 via_dangling" is a cap; the counts printed
here come from KiCad's own dangling test and are exact.

Removed (never locked items, never a via in a same-net pad or touching a
same-net zone fill: BGA fan-out vias stay for the router):
  * one via of each hole_to_hole / co-located pair, if either can go;
  * tracks KiCad calls dangling and vias connected on at most one layer,
    repeated until nothing changes (a removed via exposes its stub, ...),
    stopping where a chain's free end is the end of an open ratsnest line
    (KiCad DRC unconnected items; closest anchor pair of the two items). A
    half-routed net (e.g. cut by ripup_power_layers.py) is a dangling chain
    whose tip is where the router continues; stripping it would turn a 1 mm
    gap back into a full route. Chains pointing elsewhere are stripped back to
    where they are useful. --all strips partial routes too.
Every removal must not raise KiCad's unconnected count. Items are tried in
batches with at most one item per net, so a count that drops on one net (a
floating fragment gone) cannot hide a broken connection on another; a batch
that raises the count is bisected and the culprit kept. Zones are refilled in
a fresh process (LOG.md #7) and isolated zone islands are only reported.
"""
import argparse, json, math, os, shutil, subprocess, sys
from collections import Counter, defaultdict
import numpy as np
from scipy.spatial import cKDTree
import pcbnew

TOMM = pcbnew.ToMM
GRAVE = []          # removed items stay referenced (and un-owned) until exit


class Cleaner:
    def __init__(self, b, anchors=None):
        self.b, self.anchors, self.kept, self.gone, self.log = b, anchors or {}, {}, set(), []
        self.cu = list(b.GetEnabledLayers().CuStack())
        self.pads, self.zones = defaultdict(list), defaultdict(list)
        for f in b.GetFootprints():
            for p in f.Pads():
                self.pads[p.GetNetCode()].append(p)
        for z in b.Zones():
            if not z.GetIsRuleArea():
                self.zones[z.GetNetCode()].append(z)
        self.live = Counter(k for t in list(b.GetTracks()) + [p for ps in self.pads.values() for p in ps]
                            for k in points(t))         # copper anchor points; pads never go
        self.n = self.unconnected()

    def unconnected(self):
        self.b.BuildConnectivity()
        self.c = self.b.GetConnectivity()
        self.c.RecalculateRatsnest()
        return self.c.GetUnconnectedCount(False)

    def protected(self, t):
        """Locked, or a via in/on a same-net pad or touching a same-net zone fill."""
        if t.IsLocked():
            return True
        if t.GetClass() != 'PCB_VIA':
            return False
        pos, r = t.GetPosition(), t.GetWidth(pcbnew.F_Cu) // 2
        return (any(p.HitTest(pos) for p in self.pads[t.GetNetCode()]) or len(self.c.GetConnectedPads(t)) > 0
                or any(z.HasFilledPolysForLayer(l) and z.GetFilledPolysList(l).Collide(pos, r)
                       for z in self.zones[t.GetNetCode()] for l in z.GetLayerSet().CuStack()))

    def attached(self, t):
        return any(self.c.IsConnectedOnLayer(t, l) for l in self.cu if t.IsOnLayer(l))

    def describe(self, t, why):
        if t.GetClass() == 'PCB_VIA':
            lay = [self.b.GetLayerName(l) for l in self.cu if self.c.IsConnectedOnLayer(t, l)]
            what = f'via {TOMM(t.GetWidth(pcbnew.F_Cu)):.2f}/{TOMM(t.GetDrillValue()):.2f} on {",".join(lay) or "-"}'
        else:
            what = f'track {TOMM(t.GetWidth()):.2f}x{TOMM(t.GetLength()):.3f} mm {t.GetLayerName()}'
        p = t.GetPosition() if t.GetClass() == 'PCB_VIA' else t.GetStart()
        return (why, t.GetClass(), t.GetNetname(), what, (round(TOMM(p.x), 3), round(TOMM(p.y), 3)))

    def trial(self, items, why):
        """Remove items if the unconnected count does not rise; bisect otherwise."""
        desc = [self.describe(t, why) for t in items]
        for t in items:
            self.b.Remove(t)
        n = self.unconnected()
        if n <= self.n:
            self.n = n
            for t in items:
                t.thisown = 0           # never let SWIG free them; KiCad may still point at them
                self.gone.add(t.m_Uuid.AsString())
                self.live.subtract(points(t))
            GRAVE.extend(items)
            self.log += desc
            return len(items)
        for t in items:
            self.b.Add(t)
        self.unconnected()
        if len(items) == 1:
            self.kept[items[0].m_Uuid.AsString()] = 'needed for connectivity'
            return 0
        h = len(items) // 2
        return self.trial(items[:h], why) + self.trial(items[h:], why)

    def dangling(self):
        """(item, free end) for every track/via KiCad's DRC would call dangling."""
        out = []
        for t in self.b.GetTracks():
            p = pcbnew.VECTOR2I(0, 0)
            if self.c.TestTrackEndpointDangling(t, True, p):
                out.append((t, p))
        return out

    def hole_pairs(self):
        """(via, other) pairs closer than the hole-to-hole minimum, as KiCad's DRC tests them."""
        ds = self.b.GetDesignSettings()
        lim = ds.m_HoleToHoleMin - ds.GetDRCEpsilon()
        holes = [(t, t.GetDrillValue() / 2) for t in self.b.GetTracks() if t.GetClass() == 'PCB_VIA']
        holes += [(p, p.GetDrillSize().x / 2) for ps in self.pads.values() for p in ps
                  if p.GetDrillSize().x and p.GetDrillSize().x == p.GetDrillSize().y]
        xy = np.array([(h.GetPosition().x, h.GetPosition().y) for h, _r in holes], float)
        rmax = max(r for _h, r in holes)
        out = []
        for i, j in sorted(cKDTree(xy).query_pairs(2 * rmax + lim)):
            (a, ra), (b, rb) = holes[i], holes[j]
            if a.GetClass() != 'PCB_VIA' and b.GetClass() != 'PCB_VIA':
                continue
            d = math.dist(xy[i], xy[j])
            if d < ds.GetDRCEpsilon() or d - ra - rb < lim:
                out.append((a, b, TOMM(max(0, d - ra - rb))))
        return out

    def fix_holes(self):
        unresolved = []
        for a, b, gap in self.hole_pairs():
            if a.m_Uuid.AsString() in self.gone or b.m_Uuid.AsString() in self.gone:
                continue
            opts = [t for t in (a, b) if t.GetClass() == 'PCB_VIA' and not self.protected(t)]
            opts.sort(key=lambda t: (not self.c.TestTrackEndpointDangling(t, True),
                                     sum(self.c.IsConnectedOnLayer(t, l) for l in self.cu)))
            if not any(self.trial([t], 'hole_to_hole') for t in opts):
                unresolved.append((a, b, gap))
        return unresolved

    def tip(self, t, end):
        """A partial route's tip: a ratsnest line ends here and its far end still has copper
        (if that was a floating fragment we removed, the line is gone and so is the reason to keep)."""
        far = self.anchors.get((t.GetNetCode(), end.x, end.y), ())
        return self.attached(t) and any(k is None or self.live[k] > 0 for k in far)

    def strip_dangling(self):
        while True:
            cand = []
            for t, end in self.dangling():
                u = t.m_Uuid.AsString()
                if u not in self.kept and self.protected(t):
                    self.kept[u] = 'locked/in-pad/zone vias'
                if u not in self.kept and not self.tip(t, end):
                    cand.append(t)
            if not cand:
                return
            # items touching nothing cannot split anything; the rest go one per net per batch
            loose = [t for t in cand if not self.attached(t)]
            batch = list({t.GetNetCode(): t for t in cand if self.attached(t)}.values())
            if loose:
                self.trial(loose, 'floating')
            if batch:
                self.trial(batch, 'dangling')


def points(t):
    """(net, x, y) anchors of a track/via, as KiCad's ratsnest uses them."""
    ps = [t.GetStart(), t.GetEnd()] if t.GetClass() in ('PCB_TRACK', 'PCB_ARC') else [t.GetPosition()]
    return [(t.GetNetCode(), p.x, p.y) for p in ps]


def ratsnest_ends(b, drc):
    """{(net, x, y): far ends}: where KiCad's open ratsnest lines end (closest anchor pair of the
    two DRC items). A zone end is not resolved: None, and all anchors of the other item count."""
    items = {t.m_Uuid.AsString(): t for t in b.GetTracks()}
    items.update((p.m_Uuid.AsString(), p) for f in b.GetFootprints() for p in f.Pads())

    out = defaultdict(set)
    for u in drc['unconnected_items']:
        a, z = (items.get(i['uuid']) for i in u['items'])
        pa, pz = (points(t) if t is not None else [] for t in (a, z))
        if pa and pz:
            pa, pz = map(list, zip(min(((p, q) for p in pa for q in pz), key=lambda e: math.dist(e[0][1:], e[1][1:]))))
        for mine, far in ((pa, pz), (pz, pa)):
            for k in mine:
                out[k] |= set(far) or {None}
    return out


def refill(path):
    r = subprocess.run([sys.executable, '-c', f'''
import pcbnew
b = pcbnew.LoadBoard({path!r})
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
pcbnew.SaveBoard({path!r}, b)
c = b.GetConnectivity(); c.RecalculateRatsnest(); print(c.GetUnconnectedCount(False))
'''], check=True, capture_output=True, text=True)
    return int(r.stdout.split()[-1])


def run_drc(path, out):
    subprocess.run(['kicad-cli', 'pcb', 'drc', '--format', 'json', '--severity-all', '-o', out, path],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return json.load(open(out))


def drc_report(path):
    """Summarise KiCad's DRC of the result; list isolated zone islands (reported, never deleted)."""
    out = path + '.drc.json'
    d = run_drc(path, out)
    cnt = Counter(v['type'] for v in d['violations'])
    print(f'DRC {out}: unconnected_items {len(d["unconnected_items"])}, '
          + ', '.join(f'{k} {n}{" (list capped)" if n >= 199 else ""}' for k, n in cnt.most_common()))
    b = pcbnew.LoadBoard(path)                  # loading (not filling) a board is safe here
    zones = {z.m_Uuid.AsString(): z for z in b.Zones()}
    isl = Counter((v['items'][0]['uuid'], v['items'][0]['description'].split(' on ')[1].split(',')[0])
                  for v in d['violations'] if v['type'] == 'isolated_copper')
    for (zu, ln), k in sorted(isl.items(), key=lambda e: zones[e[0][0]].GetZoneName()):
        z, lay = zones[zu], b.GetLayerID(ln)
        poly = z.GetFilledPolysList(lay)
        # the filler flags kept islands; a zone that is all islands is left unflagged
        idx = [i for i in range(poly.OutlineCount()) if z.IsIsland(lay, i)] or list(range(poly.OutlineCount()))
        for i in idx:
            o = poly.Outline(i)
            c = o.BBox().Centre()
            print(f'  island: {z.GetZoneName()} [{z.GetNetname()}] {ln} {abs(o.Area()) / 1e12:6.2f} mm2 '
                  f'@({TOMM(c.x):.1f},{TOMM(c.y):.1f})')
        if len(idx) != k:
            print(f'    (DRC reports {k} island(s) on this zone/layer, file flags {len(idx)})')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('inp'); ap.add_argument('out')
    ap.add_argument('--drc', help='existing DRC json for INP (else run kicad-cli)')
    ap.add_argument('--all', action='store_true', help='also strip partial routes ending at a ratsnest line')
    ap.add_argument('--no-drc', action='store_true', help='skip the DRC summary of OUT')
    ap.add_argument('-v', action='store_true', help='list every removed item')
    a = ap.parse_args()

    anchors = {}
    if not a.all:
        d = json.load(open(a.drc)) if a.drc else run_drc(a.inp, a.out + '.drc_in.json')
        if len(d['unconnected_items']) >= 499:
            sys.exit('DRC lists at most 499 unconnected items, so ratsnest ends are unknown; use --all or route first')
    b = pcbnew.LoadBoard(a.inp)
    if not a.all:
        anchors = ratsnest_ends(b, d)
    cl = Cleaner(b, anchors)
    n0 = cl.n
    d0 = Counter(t.GetClass() for t, _p in cl.dangling())
    unresolved = cl.fix_holes()
    cl.strip_dangling()
    left = cl.dangling()
    d1 = Counter(t.GetClass() for t, _p in left)
    pcbnew.SaveBoard(a.out, b)
    pro = os.path.splitext(a.inp)[0] + '.kicad_pro'
    if os.path.exists(pro) and os.path.abspath(a.inp) != os.path.abspath(a.out):   # DRC rules live here
        shutil.copy(pro, os.path.splitext(a.out)[0] + '.kicad_pro')
    n1 = refill(a.out)

    by = Counter((w, k) for w, k, *_ in cl.log)
    print('removed:', ', '.join(f'{n} {k[4:].lower()} ({w})' for (w, k), n in sorted(by.items())) or 'nothing')
    nets = Counter(net for _w, _k, net, *_ in cl.log)
    if nets:
        print('  by net:', ', '.join(f'{k} {n}' for k, n in nets.most_common(20)), '...' if len(nets) > 20 else '')
    if a.v:
        for e in cl.log:
            print('   ', *e)
    print(f'dangling (exact; DRC lists at most 199): vias {d0["PCB_VIA"]} -> {d1["PCB_VIA"]}, '
          f'tracks {d0["PCB_TRACK"] + d0["PCB_ARC"]} -> {d1["PCB_TRACK"] + d1["PCB_ARC"]}; kept: '
          + ', '.join(f'{n} {w}' for w, n in Counter(cl.kept.get(t.m_Uuid.AsString(), 'partial-route tips at a ratsnest end')
                                                     for t, _p in left).most_common()))
    for x, y, gap in unresolved:
        print(f'  hole_to_hole unresolved ({gap:.4f} mm): ' + ' | '.join(
            f'{"locked " if t.IsLocked() else ""}{t.GetClass()[4:].lower()} [{t.GetNetname()}] '
            f'@({TOMM(t.GetPosition().x):.3f},{TOMM(t.GetPosition().y):.3f})' for t in (x, y)))
    print(f'unconnected: {n0} before, {n1} after refill')
    if n1 > n0:
        sys.exit(f'ERROR: unconnected count rose after refill; do not use {a.out}')
    if not a.no_drc:
        drc_report(a.out)


if __name__ == '__main__':
    main()
