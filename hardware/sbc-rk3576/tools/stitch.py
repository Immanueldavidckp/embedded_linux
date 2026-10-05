#!/usr/bin/env python3
"""Plane stitching: give every SMD pad on a plane net its own via to the plane.

Autorouters are poor at "connect to plane" for hundreds of small pads; layout
engineers drop a short stub + via next to each GND pad instead. This does that
for GND (planes on L2/L5/L7), choosing the first nearby spot that clears every
other copper item.
"""
import math, os, sys
import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PCB = os.path.join(HERE, '..', 'kicad', 'rk3576-sbc.kicad_pcb')
MM, TOMM = pcbnew.FromMM, pcbnew.ToMM
VIA_D, VIA_DRILL, TRACK_W, CLR = 0.35, 0.20, 0.20, 0.135   # 0.12 rule + margin
PLANE_LAYERS = {pcbnew.In1_Cu, pcbnew.In4_Cu}
NETS = ('GND',)
SKIP_REFS = ('U401', 'U601')     # fanned out via-in-pad already


def main(path=PCB, nets=NETS):
    nets = set(nets)
    b = pcbnew.LoadBoard(path)
    w, h = b.GetBoardEdgesBoundingBox().GetWidth(), b.GetBoardEdgesBoundingBox().GetHeight()
    tracks = [t for t in b.GetTracks()]
    pads = [p for f in b.GetFootprints() for p in f.Pads()]
    vias = [t for t in tracks if t.GetClass() == 'PCB_VIA']
    keepouts = [z for z in b.Zones() if z.GetIsRuleArea()] + \
               [z for f in b.GetFootprints() for z in f.Zones() if z.GetIsRuleArea()]
    added, failed = 0, []

    def blocked(pt, radius, layer, net, through):
        """True if a disk at pt (radius incl. clearance) hits other-net copper."""
        acc = MM(radius)
        for p in pads:
            if p.GetNetname() == net:
                continue
            if (through or p.IsOnLayer(layer)) and p.HitTest(pt, acc):
                return True
            if p.GetDrillSize().x and p.HitTest(pt, acc + MM(0.1)):
                return True
        for t in tracks:
            if t.GetNetname() == net:
                continue
            if t.GetClass() == 'PCB_VIA':
                if t.HitTest(pt, acc):
                    return True
            elif (through and t.GetLayer() not in PLANE_LAYERS or t.GetLayer() == layer) and t.HitTest(pt, acc):
                return True
        if through:
            for v in vias:                       # drilled-hole spacing to any net
                if (v.GetPosition() - pt).EuclideanNorm() < MM(VIA_D / 2 + 0.30):
                    return True
        for z in keepouts:                       # footprint/board keepouts block stubs too
            if z.Outline().Contains(pt):
                return True
        # keep off the board edge and out of the BGA via fields
        x, y = TOMM(pt.x), TOMM(pt.y)
        return not (0.8 < x < TOMM(w) - 0.8 and 0.8 < y < TOMM(h) - 0.8)

    for fp in b.GetFootprints():
        if fp.GetReference() in SKIP_REFS:
            continue
        for pad in fp.Pads():
            net = pad.GetNetname()
            if net not in nets or pad.GetAttribute() != pcbnew.PAD_ATTRIB_SMD:
                continue
            c = pad.GetPosition()
            if any(v.GetNetname() == net and (v.GetPosition() - c).EuclideanNorm() < MM(1.2) for v in vias):
                continue
            layer = pcbnew.B_Cu if fp.IsFlipped() else pcbnew.F_Cu
            half = max(pad.GetBoundingBox().GetWidth(), pad.GetBoundingBox().GetHeight()) / 2
            done = False
            for dist in (0.45, 0.65, 0.9, 1.2, 1.6):
                for k in range(16):
                    a = 2 * math.pi * k / 16
                    r = half + MM(dist)
                    pt = pcbnew.VECTOR2I(int(c.x + r * math.cos(a)), int(c.y + r * math.sin(a)))
                    if blocked(pt, VIA_D / 2 + CLR, layer, net, True):
                        continue
                    steps = 6
                    if any(blocked(pcbnew.VECTOR2I(int(c.x + (pt.x - c.x) * i / steps),
                                                   int(c.y + (pt.y - c.y) * i / steps)),
                                   TRACK_W / 2 + CLR, layer, net, False) for i in range(1, steps)):
                        continue
                    v = pcbnew.PCB_VIA(b)
                    v.SetPosition(pt)
                    v.SetViaType(pcbnew.VIATYPE_THROUGH)
                    v.SetWidth(MM(VIA_D))
                    v.SetDrill(MM(VIA_DRILL))
                    v.SetNet(pad.GetNet())
                    b.Add(v)
                    t = pcbnew.PCB_TRACK(b)
                    t.SetStart(c)
                    t.SetEnd(pt)
                    t.SetWidth(MM(TRACK_W))
                    t.SetLayer(layer)
                    t.SetNet(pad.GetNet())
                    b.Add(t)
                    tracks += [v, t]
                    vias.append(v)
                    added += 1
                    done = True
                    break
                if done:
                    break
            if not done:
                failed.append(f'{fp.GetReference()}.{pad.GetNumber()}')
    pcbnew.SaveBoard(path, b)
    b = pcbnew.LoadBoard(path)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(path, b)
    print(f'stitching: {added} vias added on {len(nets)} net(s), {len(failed)} pads left to the router {failed[:12]}')


if __name__ == '__main__':
    main(sys.argv[1] if len(sys.argv) > 1 else PCB, sys.argv[2:] or NETS)
