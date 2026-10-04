#!/usr/bin/env python3
"""BGA escape (fan-out) before autorouting: one via-in-pad per used ball.

Fine-pitch BGAs (RK3576 FCCSP 0.55 mm, LPDDR5 0.8x0.7 mm) cannot be escaped by
a general-purpose autorouter: it never puts vias inside pads and there is no
room for dog-bones between 0.24 mm pads at 0.55 mm pitch. Layout engineers fan
these parts out first (via-in-pad, filled and capped = POFV), then route.

Rules used here:
  * via 0.25 mm / 0.15 mm drill (annular 0.05 mm) centred in each pad that has
    a real net; 0.55 mm pitch leaves 0.30 mm between vias = one 0.09 mm track
    with 0.09 mm clearance per channel on inner layers.
  * vias are locked so the router keeps them.
  * a via that would hit a bottom-side pad of another net (decoupling caps
    under the BGA) is skipped and left to the router.
"""
import os, sys
import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PCB = os.path.join(HERE, '..', 'kicad', 'rk3576-sbc.kicad_pcb')
MM = pcbnew.FromMM
PARTS = {'U401': (0.25, 0.15), 'U601': (0.30, 0.15)}
CLR = 0.09


def main(path=PCB):
    b = pcbnew.LoadBoard(path)
    for t in list(b.GetTracks()):           # idempotent: drop earlier fan-out vias
        if t.GetClass() == 'PCB_VIA' and t.IsLocked():
            b.Remove(t)
    bottom = [p for f in b.GetFootprints() if f.IsFlipped() for p in f.Pads()]
    placed = skipped = 0
    for ref, (dia, drill) in PARTS.items():
        fp = b.FindFootprintByReference(ref)
        for pad in fp.Pads():
            net = pad.GetNetname()
            if not net or net.startswith('unconnected-'):
                continue
            pos = pad.GetPosition()
            r = MM(dia / 2 + CLR)
            hit = False
            for q in bottom:
                if q.GetNetname() == net:
                    continue
                bb = q.GetBoundingBox()
                if (bb.GetLeft() - r < pos.x < bb.GetRight() + r and
                        bb.GetTop() - r < pos.y < bb.GetBottom() + r):
                    hit = True
                    break
            if hit:
                skipped += 1
                continue
            v = pcbnew.PCB_VIA(b)
            v.SetPosition(pos)
            v.SetViaType(pcbnew.VIATYPE_THROUGH)
            v.SetWidth(MM(dia))
            v.SetDrill(MM(drill))
            v.SetNet(pad.GetNet())
            v.SetLocked(True)
            b.Add(v)
            placed += 1
    pcbnew.SaveBoard(path, b)
    b = pcbnew.LoadBoard(path)              # zone fill needs a board loaded from disk
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(path, b)
    print(f'fan-out: {placed} via-in-pad placed, {skipped} skipped (bottom-side pad conflict)')


if __name__ == '__main__':
    main(*sys.argv[1:])
