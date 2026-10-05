#!/usr/bin/env python3
"""Non-functional pad removal: drop via pads on layers where nothing connects.

    python3 via_nfp.py IN.kicad_pcb OUT.kicad_pcb

Under the 0.55 mm RK3576 every fan-out via carried a 0.25 mm pad on all eight
layers, which leaves no room for a 0.09 mm track between two vias on the inner
layers. With unconnected pads removed, only the drill (+0.12 mm hole clearance)
is in the way, and the planes get more copper too. Fabs do this routinely
(IPC "non-functional pad removal"); KiCad's DRC and Gerber output honour it.
"""
import subprocess, sys
import pcbnew


def main(src, dst):
    b = pcbnew.LoadBoard(src)
    n = 0
    for t in b.GetTracks():
        if t.GetClass() == 'PCB_VIA':
            t.Padstack().SetUnconnectedLayerMode(pcbnew.PADSTACK.UNCONNECTED_LAYER_MODE_REMOVE_ALL)
            n += 1
    pcbnew.SaveBoard(dst, b)
    print(f'{n} vias set to remove unconnected pads')
    subprocess.run([sys.executable, '-c', f'''
import pcbnew
b = pcbnew.LoadBoard({dst!r})
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
pcbnew.SaveBoard({dst!r}, b)
c = b.GetConnectivity(); c.RecalculateRatsnest(); print('unconnected', c.GetUnconnectedCount(False))
'''], check=True)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
