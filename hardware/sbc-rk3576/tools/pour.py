#!/usr/bin/env python3
"""Power pours on L4 (In3.Cu) + stitch vias for every power rail.

Each rail gets a zone on the power layer covering the area its pads span (+1 mm).
Overlaps are resolved by priority: the smaller (more local) rail wins, so core
rails under the SoC and DDR rails around the LPDDR5 get solid copper and the
large 5 V / 3.3 V rails fill what remains. Every rail pad then gets a stub+via
into the pour (stitch.py), exactly like the GND planes.
"""
import os, re, sys
import pcbnew
import stitch

HERE = os.path.dirname(os.path.abspath(__file__))
PCB = os.path.join(HERE, '..', 'kicad', 'rk3576-sbc.kicad_pcb')
MM, TOMM = pcbnew.FromMM, pcbnew.ToMM
RAIL = re.compile(r'^(VDD|VCC|VBUS)')
W, H = 100.0, 72.0
# board-wide rails get their own layer (L7) so local pours on L4 can't island them
BIG = {'VCC5V0_SYS_S5': pcbnew.In6_Cu, 'VCC_3V3_S3': pcbnew.In6_Cu, 'VCC_3V3_S0': pcbnew.In6_Cu,
       'VCC_1V8_S3': pcbnew.In6_Cu}


def main(path=PCB):
    b = pcbnew.LoadBoard(path)
    for z in list(b.Zones()):                       # idempotent; L7 becomes the big-rail layer
        if z.GetZoneName().startswith('PWR_') or z.GetZoneName() == 'GND_In6.Cu':
            b.Remove(z)
    rails = {}
    for f in b.GetFootprints():
        for p in f.Pads():
            n = p.GetNetname()
            if RAIL.match(n):
                rails.setdefault(n, []).append(p.GetPosition())
    boxes = []
    for n, pts in rails.items():
        if len(pts) < 2:
            continue
        x0 = max(0.5, min(TOMM(q.x) for q in pts) - 1.0)
        x1 = min(W - 0.5, max(TOMM(q.x) for q in pts) + 1.0)
        y0 = max(0.5, min(TOMM(q.y) for q in pts) - 1.0)
        y1 = min(H - 0.5, max(TOMM(q.y) for q in pts) + 1.0)
        boxes.append(((x1 - x0) * (y1 - y0), n, (x0, y0, x1, y1)))
    boxes.sort()
    netinfo = b.GetNetsByName()
    for prio, (_a, n, (x0, y0, x1, y1)) in enumerate(reversed(boxes)):
        z = pcbnew.ZONE(b)
        z.SetLayer(BIG.get(n, pcbnew.In3_Cu))
        z.SetNet(netinfo[n])
        z.SetZoneName(f'PWR_{n}')
        z.SetAssignedPriority(prio + 1)             # smallest box = highest priority
        z.SetLocalClearance(MM(0.15))
        z.SetMinThickness(MM(0.15))
        z.SetPadConnection(pcbnew.ZONE_CONNECTION_FULL)
        z.SetIslandRemovalMode(pcbnew.ISLAND_REMOVAL_MODE_AREA)
        z.SetMinIslandArea(int(MM(1.0) * MM(1.0)))
        o = z.Outline()
        o.NewOutline()
        for x, y in ((x0, y0), (x1, y0), (x1, y1), (x0, y1)):
            o.Append(MM(x), MM(y))
        b.Add(z)
    pcbnew.SaveBoard(path, b)
    print(f'pours: {len(boxes)} power zones ({len(BIG)} board-wide on In6.Cu, rest on In3.Cu)')
    stitch.main(path, [n for _a, n, _b in boxes])


if __name__ == '__main__':
    main(*sys.argv[1:])
