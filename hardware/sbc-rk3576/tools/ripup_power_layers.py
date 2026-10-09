#!/usr/bin/env python3
"""Remove signal tracks from the power layers L4 (In3.Cu) and L7 (In6.Cu).

Early autorouter passes ran before the power pours existed and used L4/L7 for
signals, which later cut the pours into islands. This clears those layers for
power so the pours become contiguous; route.py then re-routes the removed
signals on L1/L3/L6/L8 only (L4/L7 are marked 'power' in the DSN).
"""
import os, re, sys
import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PCB = os.path.join(HERE, '..', 'kicad', 'rk3576-sbc.kicad_pcb')
POWER = re.compile(r'^(GND|VDD|VCC|VBUS)')
LAYERS = (pcbnew.In3_Cu, pcbnew.In6_Cu)


def main(path=PCB):
    b = pcbnew.LoadBoard(path)
    gone = [t for t in b.GetTracks() if t.GetClass() in ('PCB_TRACK', 'PCB_ARC')
            and t.GetLayer() in LAYERS and not POWER.match(t.GetNetname())]
    nets = {t.GetNetname() for t in gone}
    for t in gone:
        b.Remove(t)
    pcbnew.SaveBoard(path, b)
    print(f'removed {len(gone)} signal track segments from L4/L7 ({len(nets)} nets)')


if __name__ == '__main__':
    main(*sys.argv[1:])
