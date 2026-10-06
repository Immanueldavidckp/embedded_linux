#!/usr/bin/env python3
"""Fan out a BGA late: clear its footprint, then via-in-pad every used ball.

    python3 fanout_region.py IN.kicad_pcb OUT.kicad_pcb REF [--via 0.25/0.15] [--margin 0.3]

fanout.py escaped the RK3576 and the LPDDR5 before routing, but not the eMMC
(U701, 0.5 mm pitch). The router then ran other nets across the eMMC's
footprint on the inner and bottom layers, after which the inner balls had
nowhere to drop a via: maze_diag.py showed each of them boxed into its own pad.
This removes every unlocked track/via that crosses the ball field (any net;
their connections re-open and are re-routed), then places a locked via-in-pad
(filled and capped, like the other BGAs) in each ball with a real net.
"""
import argparse, math, os, shutil, subprocess, sys
import pcbnew

MM, TOMM = pcbnew.FromMM, pcbnew.ToMM
GRAVE = []          # removed items must stay referenced (KiCad SWIG ownership bug)


def blocks(f, sites, dia, own_nets=True):
    """Does any pad of footprint f sit within a via's reach of a ball site of another net?"""
    r = MM(dia / 2 + 0.10)
    for q in f.Pads():
        bb = q.GetBoundingBox()
        for s in sites:
            if bb.GetLeft() - r < s.x < bb.GetRight() + r and bb.GetTop() - r < s.y < bb.GetBottom() + r:
                return True
    return False


def relocate(b, fp, sites, dia, gone, keep_clear=None):
    """Move other-side footprints off the via sites: nearest spot (spiral, 0.25 mm steps, <= 6 mm)
    whose pads clear every site (and every keep_clear point) and whose body clears every other
    footprint on that side."""
    keep_clear = sites if keep_clear is None else keep_clear
    side = [f for f in b.GetFootprints() if f.IsFlipped() != fp.IsFlipped()]
    edge = b.GetBoardEdgesBoundingBox()
    extra = []
    for f in side:
        if not blocks(f, sites, dia):
            continue
        home = f.GetPosition()
        others = [g for g in side if g is not f]
        best = None
        for ring in range(1, 25):
            d = MM(0.25 * ring)
            n = 8 * ring
            for k in range(n):
                ang = 2 * math.pi * k / n
                f.SetPosition(pcbnew.VECTOR2I(int(home.x + d * math.cos(ang)), int(home.y + d * math.sin(ang))))
                bb = f.GetBoundingBox(False, False)
                bb.Inflate(MM(0.1))
                if not edge.Contains(bb) or blocks(f, keep_clear, dia):
                    continue
                if any(bb.Intersects(g.GetBoundingBox(False, False)) for g in others):
                    continue
                best = f.GetPosition()
                break
            if best is not None:
                break
        if best is None:
            f.SetPosition(home)
            print(f'  {f.GetReference()}: no free spot found, left in place', flush=True)
            continue
        f.SetPosition(best)
        # routes that ended on the part's old pads are stale now, and routed copper of other
        # nets under its new pads must go
        nets = {p.GetNetname() for p in f.Pads()}
        body = f.GetBoundingBox(False, False)
        body.Inflate(MM(0.15))
        layer = pcbnew.B_Cu if f.IsFlipped() else pcbnew.F_Cu
        for t in b.GetTracks():
            if t.IsLocked() or any(t is g for g in extra) or t.GetNetname() in nets:
                continue
            if (t.GetClass() == 'PCB_VIA' or t.GetLayer() == layer) and body.Intersects(t.GetBoundingBox()):
                extra.append(t)
        for t in b.GetTracks():
            if t.IsLocked() or t.GetNetname() not in nets or any(t is g for g in extra):
                continue
            if (t.GetPosition() - home).EuclideanNorm() < MM(2.0) or \
                    (t.GetClass() != 'PCB_VIA' and ((t.GetStart() - home).EuclideanNorm() < MM(1.5) or
                                                   (t.GetEnd() - home).EuclideanNorm() < MM(1.5))):
                extra.append(t)
        print(f'  moved {f.GetReference()} by {TOMM((best - home).EuclideanNorm()):.2f} mm', flush=True)
    for t in extra:
        b.Remove(t)
        GRAVE.append(t)
    gone += extra


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('src'); ap.add_argument('dst'); ap.add_argument('ref')
    ap.add_argument('--via', default='0.25/0.15')
    ap.add_argument('--margin', type=float, default=0.3)
    ap.add_argument('--only-missing', action='store_true',
                    help='keep the routing; only add the balls that have no via-in-pad yet')
    ap.add_argument('--relocate', action='store_true',
                    help='slide other-side parts that sit on a ball\'s via site to the nearest free spot')
    a = ap.parse_args()
    dia, drill = (float(x) for x in a.via.split('/'))
    if os.path.abspath(a.src) != os.path.abspath(a.dst):
        shutil.copy(a.src.replace('.kicad_pcb', '.kicad_pro'), a.dst.replace('.kicad_pcb', '.kicad_pro'))
    b = pcbnew.LoadBoard(a.src)
    fp = b.FindFootprintByReference(a.ref)
    pads = list(fp.Pads())
    x0 = min(TOMM(p.GetBoundingBox().GetLeft()) for p in pads) - a.margin
    x1 = max(TOMM(p.GetBoundingBox().GetRight()) for p in pads) + a.margin
    y0 = min(TOMM(p.GetBoundingBox().GetTop()) for p in pads) - a.margin
    y1 = max(TOMM(p.GetBoundingBox().GetBottom()) for p in pads) + a.margin
    gone = []
    used = [p for p in pads if p.GetNetname() and not p.GetNetname().startswith('unconnected-')]
    vias = [t for t in b.GetTracks() if t.GetClass() == 'PCB_VIA']
    if a.only_missing:
        has = lambda p: any(v.GetNetname() == p.GetNetname() and
                            (v.GetPosition() - p.GetPosition()).EuclideanNorm() < MM(0.05) for v in vias)
        pads = [p for p in used if not has(p)]
        print(f'{a.ref}: {len(pads)} used balls without via-in-pad', flush=True)
    else:
        for t in b.GetTracks():
            if t.IsLocked():
                continue
            bb = t.GetBoundingBox()
            if TOMM(bb.GetRight()) >= x0 and TOMM(bb.GetLeft()) <= x1 and \
                    TOMM(bb.GetBottom()) >= y0 and TOMM(bb.GetTop()) <= y1:
                gone.append(t)
        for t in gone:
            b.Remove(t)
            GRAVE.append(t)
    sites = [p.GetPosition() for p in pads if p.GetNetname() and not p.GetNetname().startswith('unconnected-')]
    if a.relocate:
        relocate(b, fp, sites, dia, gone, keep_clear=[p.GetPosition() for p in used])
    other_side = [p for f in b.GetFootprints() if f.IsFlipped() != fp.IsFlipped() for p in f.Pads()]
    placed, skipped = 0, []
    for pad in pads:
        net = pad.GetNetname()
        if not net or net.startswith('unconnected-'):
            continue
        pos = pad.GetPosition()
        r = MM(dia / 2 + 0.10)
        if any(q.GetNetname() != net and q.GetBoundingBox().GetLeft() - r < pos.x < q.GetBoundingBox().GetRight() + r
               and q.GetBoundingBox().GetTop() - r < pos.y < q.GetBoundingBox().GetBottom() + r for q in other_side):
            skipped.append(pad.GetNumber())
            continue
        v = pcbnew.PCB_VIA(b)
        v.SetPosition(pos)
        v.SetViaType(pcbnew.VIATYPE_THROUGH)
        v.SetWidth(MM(dia))
        v.SetDrill(MM(drill))
        v.SetNet(pad.GetNet())
        v.SetLocked(True)
        v.Padstack().SetUnconnectedLayerMode(pcbnew.PADSTACK.UNCONNECTED_LAYER_MODE_REMOVE_ALL)
        b.Add(v)
        placed += 1
        if a.only_missing:            # routed copper of other nets too close to the new via
            reach = MM(dia / 2 + 0.25)
            for t in list(b.GetTracks()):
                if t is v or t.IsLocked() or t.GetNetname() == net:
                    continue
                if t.GetClass() == 'PCB_VIA':
                    hit = (t.GetPosition() - pos).EuclideanNorm() < reach + t.GetWidth(pcbnew.F_Cu) // 2
                else:
                    hit = pcbnew.SHAPE_SEGMENT(t.GetStart(), t.GetEnd(), t.GetWidth()).Collide(
                        pcbnew.SHAPE_SEGMENT(pos, pos, 2 * reach), 0)
                if hit:
                    b.Remove(t)
                    GRAVE.append(t)
                    gone.append(t)
    pcbnew.SaveBoard(a.dst, b)
    print(f'{a.ref}: removed {len(gone)} routed items in the ball field, placed {placed} via-in-pad, '
          f'skipped {len(skipped)} {skipped[:10]} (other-side pad)', flush=True)
    subprocess.run([sys.executable, '-c', f'''
import pcbnew
b = pcbnew.LoadBoard({a.dst!r})
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
pcbnew.SaveBoard({a.dst!r}, b)
c = b.GetConnectivity(); c.RecalculateRatsnest(); print('unconnected', c.GetUnconnectedCount(False))
'''], check=True)


if __name__ == '__main__':
    main()
