#!/usr/bin/env python3
"""Merge routing patches (JSON from maze_route.py --patch) into a board.

    python3 apply_patch.py BASE.kicad_pcb OUT.kicad_pcb patch1.json [patch2.json ...]

Several router workers route disjoint net groups on copies of the same base
board; each returns only the tracks/vias it added. This applies them in order,
refills the zones, runs KiCad DRC, and drops every patch connection that is
involved in a clearance/hole/short violation with copper it did not create
itself (first patch wins). Dropped connections are listed so they can be
re-routed on the merged board. Prints the unconnected count at the end.
"""
import json, subprocess, sys
from collections import defaultdict
import pcbnew

MM = pcbnew.FromMM
BAD = {'clearance', 'hole_clearance', 'hole_to_hole', 'shorting_items', 'tracks_crossing',
       'copper_edge_clearance', 'track_width', 'via_diameter', 'annular_width', 'drill_out_of_range'}


def add_items(b, patches):
    owner = {}                     # uuid -> (patch index, conn)
    for pi, patch in enumerate(patches):
        for e in patch:
            net = b.FindNet(e['net'])
            if e['type'] == 'track':
                t = pcbnew.PCB_TRACK(b)
                t.SetStart(pcbnew.VECTOR2I(MM(e['start'][0]), MM(e['start'][1])))
                t.SetEnd(pcbnew.VECTOR2I(MM(e['end'][0]), MM(e['end'][1])))
                t.SetWidth(MM(e['width']))
                t.SetLayer(b.GetLayerID(e['layer']))
            else:
                t = pcbnew.PCB_VIA(b)
                t.SetPosition(pcbnew.VECTOR2I(MM(e['pos'][0]), MM(e['pos'][1])))
                t.SetViaType(pcbnew.VIATYPE_THROUGH)
                t.SetWidth(MM(e['size']))
                t.SetDrill(MM(e['drill']))
                t.Padstack().SetUnconnectedLayerMode(pcbnew.PADSTACK.UNCONNECTED_LAYER_MODE_REMOVE_ALL)
            t.SetNet(net)
            b.Add(t)
            owner[t.m_Uuid.AsString()] = (pi, e['conn'])
    return owner


def fill(path):
    subprocess.run([sys.executable, '-c', f'''
import pcbnew
b = pcbnew.LoadBoard({path!r})
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
pcbnew.SaveBoard({path!r}, b)
c = b.GetConnectivity(); c.RecalculateRatsnest(); print('unconnected', c.GetUnconnectedCount(False))
'''], check=True)


def drc(path):
    out = path + '.drc.json'
    subprocess.run(['kicad-cli', 'pcb', 'drc', '--format', 'json', '--severity-all', '-o', out, path],
                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return json.load(open(out))


def main(base, out, patch_files):
    patches = [json.load(open(p)) for p in patch_files]
    for rnd in range(4):
        b = pcbnew.LoadBoard(base)
        owner = add_items(b, patches)
        pcbnew.SaveBoard(out, b)
        fill(out)
        d = drc(out)
        drop = defaultdict(set)
        for v in d['violations']:
            if v['type'] not in BAD:
                continue
            mine = [owner[i['uuid']] for i in v['items'] if i['uuid'] in owner]
            if not mine:
                continue
            # keep the earlier patch (and within a patch the earlier connection)
            loser = max(mine) if len(mine) > 1 and len(set(mine)) > 1 else mine[0]
            drop[loser[0]].add(loser[1])
        if not drop:
            print(f'merge clean after {rnd} drop round(s); unconnected {len(d["unconnected_items"])}')
            return
        for pi, conns in drop.items():
            print(f'patch {patch_files[pi]}: dropping {len(conns)} connection(s) {sorted(conns)[:20]}')
            patches[pi] = [e for e in patches[pi] if e['conn'] not in conns]
    print('warning: violations remain after 4 rounds')


if __name__ == '__main__':
    main(sys.argv[1], sys.argv[2], sys.argv[3:])
