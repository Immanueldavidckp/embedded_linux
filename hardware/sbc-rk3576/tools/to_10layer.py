#!/usr/bin/env python3
"""Move the routed 8-layer board (rev A1) onto the 10-layer stackup (rev A2) in place.

    python3 to_10layer.py IN.kicad_pcb OUT.kicad_pcb

Two signal layers are inserted (In3 and In7, see stackup.py), so the old inner layers
shift: In3 (core pours) -> In4, In4 (GND) -> In5, In5 (signal) -> In6, In6 (big-rail
pours) -> In8. In1 and In2 keep their roles. All routing survives: tracks and zones change
layer, through vias simply pass the new layers (no pad there; unused pads are removed),
and all-layer keepouts are widened to the new layers. The stackup block is rewritten from
stackup.py, then the zones are refilled in a fresh process and the unconnected count is
checked so nothing was lost.
"""
import os, re, shutil, subprocess, sys
import pcbnew
import stackup

MOVE = {pcbnew.In3_Cu: pcbnew.In4_Cu, pcbnew.In4_Cu: pcbnew.In5_Cu,
        pcbnew.In5_Cu: pcbnew.In6_Cu, pcbnew.In6_Cu: pcbnew.In8_Cu}


def unconnected(path):
    out = subprocess.run([sys.executable, '-c', f'''
import pcbnew
b = pcbnew.LoadBoard({path!r})
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
pcbnew.SaveBoard({path!r}, b)
c = b.GetConnectivity(); c.RecalculateRatsnest(); print(c.GetUnconnectedCount(False))
'''], capture_output=True, text=True, check=True).stdout.split()[-1]
    return int(out)


def main(src, dst):
    if os.path.abspath(src) != os.path.abspath(dst):
        shutil.copy(src.replace('.kicad_pcb', '.kicad_pro'), dst.replace('.kicad_pcb', '.kicad_pro'))
    b = pcbnew.LoadBoard(src)
    if b.GetCopperLayerCount() != 8:
        raise SystemExit(f'expected an 8-layer board, got {b.GetCopperLayerCount()}')
    old_all = pcbnew.LSET.AllCuMask(8)
    b.SetCopperLayerCount(stackup.LAYER_COUNT)
    moved = {'track': 0, 'zone': 0, 'keepout': 0}
    for t in b.GetTracks():
        if t.GetClass() != 'PCB_VIA' and t.GetLayer() in MOVE:
            t.SetLayer(MOVE[t.GetLayer()])
            moved['track'] += 1
    zones = list(b.Zones()) + [z for f in b.GetFootprints() for z in f.Zones()]
    for z in zones:
        ls = z.GetLayerSet()
        if z.GetIsRuleArea() and all(ls.Contains(l) for l in old_all.CuStack()):
            z.SetLayerSet(pcbnew.LSET.AllCuMask(stackup.LAYER_COUNT))
            moved['keepout'] += 1
        elif not z.GetIsRuleArea() and z.GetLayer() in MOVE:
            z.SetLayer(MOVE[z.GetLayer()])
            name = z.GetZoneName()
            if name.startswith('GND_'):
                z.SetZoneName('GND_' + b.GetLayerName(z.GetLayer()))
            moved['zone'] += 1
    pcbnew.SaveBoard(dst, b)
    # the stackup description (thicknesses, dielectrics) comes from stackup.py
    txt = open(dst).read()
    start = txt.index('\t\t(stackup')
    depth, i = 0, start
    while True:
        if txt[i] == '(':
            depth += 1
        elif txt[i] == ')':
            depth -= 1
            if depth == 0:
                break
        i += 1
    txt = txt[:start] + stackup.stackup_sexp() + txt[i + 1:]
    txt = re.sub(r'\(board_thickness [0-9.]+\)', '(board_thickness 1.6)', txt)
    open(dst, 'w').write(txt)
    print(f'{stackup.LAYER_COUNT} copper layers; moved {moved}', flush=True)
    print('unconnected after refill:', unconnected(dst), flush=True)


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2])
