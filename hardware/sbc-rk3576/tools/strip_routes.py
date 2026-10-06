#!/usr/bin/env python3
"""Strip all routing back to the fixed base, ready for a full re-route.

    python3 strip_routes.py IN.kicad_pcb OUT.kicad_pcb [--nets REGEX]

With --nets, only those nets lose their routed tracks/vias (locked fan-out vias stay) and
nothing is re-stitched: used to re-route nets whose partial routes got stranded inside a
BGA ball field, where no new via fits and a route can only change layer at its own
fan-out via.

Keeps pads, the locked BGA fan-out vias, zones; removes every other track and
via (Freerouting's and the maze router's), then re-stitches GND and every power
rail pad to its plane/pour (stitch.py) so the planes are connected the same way
as before. What is left open is pure routing work for maze_ripup.py.
"""
import argparse, os, re, shutil, subprocess, sys
import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
GRAVE = []          # removed items must stay referenced (KiCad SWIG ownership bug)


def main(src, dst, nets=None):
    if os.path.abspath(src) != os.path.abspath(dst):
        shutil.copy(src.replace('.kicad_pcb', '.kicad_pro'), dst.replace('.kicad_pcb', '.kicad_pro'))
    b = pcbnew.LoadBoard(src)
    gone = [t for t in b.GetTracks() if not t.IsLocked() and (nets is None or re.search(nets, t.GetNetname()))]
    if nets is not None:
        for t in gone:
            b.Remove(t)
            GRAVE.append(t)
        pcbnew.SaveBoard(dst, b)
        print(f'stripped {len(gone)} tracks/vias of nets matching {nets!r}', flush=True)
        return
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
    ap = argparse.ArgumentParser()
    ap.add_argument('src'); ap.add_argument('dst')
    ap.add_argument('--nets', help='only strip these nets (regex), no re-stitching')
    a = ap.parse_args()
    main(a.src, a.dst, a.nets)
