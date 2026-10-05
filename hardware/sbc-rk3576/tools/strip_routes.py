#!/usr/bin/env python3
"""Strip all routing back to the fixed base, ready for a full re-route.

    python3 strip_routes.py IN.kicad_pcb OUT.kicad_pcb

Keeps pads, the locked BGA fan-out vias, zones; removes every other track and
via (Freerouting's and the maze router's), then re-stitches GND and every power
rail pad to its plane/pour (stitch.py) so the planes are connected the same way
as before. What is left open is pure routing work for pathfinder.py.
"""
import os, re, shutil, subprocess, sys
import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
GRAVE = []          # removed items must stay referenced (KiCad SWIG ownership bug)


def main(src, dst):
    if os.path.abspath(src) != os.path.abspath(dst):
        shutil.copy(src.replace('.kicad_pcb', '.kicad_pro'), dst.replace('.kicad_pcb', '.kicad_pro'))
    b = pcbnew.LoadBoard(src)
    gone = [t for t in b.GetTracks() if not t.IsLocked()]
    for t in gone:
        b.Remove(t)
        GRAVE.append(t)
    rails = sorted({z.GetNetname() for z in b.Zones() if z.GetZoneName().startswith('PWR_')})
    pcbnew.SaveBoard(dst, b)
    print(f'stripped {len(gone)} tracks/vias; re-stitching GND + {len(rails)} rails', flush=True)
    subprocess.run([sys.executable, os.path.join(HERE, 'stitch.py'), dst, 'GND'], check=True)
    subprocess.run([sys.executable, os.path.join(HERE, 'stitch.py'), dst, *rails], check=True)
    subprocess.run([sys.executable, '-c', f'''
import pcbnew
b = pcbnew.LoadBoard({dst!r})
for t in b.GetTracks():
    if t.GetClass() == 'PCB_VIA':
        t.Padstack().SetUnconnectedLayerMode(pcbnew.PADSTACK.UNCONNECTED_LAYER_MODE_REMOVE_ALL)
pcbnew.SaveBoard({dst!r}, b)
'''], check=True)
    subprocess.run([sys.executable, '-c', f'''
import pcbnew
b = pcbnew.LoadBoard({dst!r})
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
pcbnew.SaveBoard({dst!r}, b)
c = b.GetConnectivity(); c.RecalculateRatsnest(); print('unconnected', c.GetUnconnectedCount(False))
'''], check=True)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
