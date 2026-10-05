#!/usr/bin/env python3
"""Write a copy of the board in which every power pour is replaced by one zone
per *filled island* (outline = real copper). Freerouting exports zones as plane
polygons from their outlines, so this gives the router the true connectivity of
the pours instead of an optimistic rectangle.

usage: islands_export.py <board_with_fills.kicad_pcb> <out.kicad_pcb>
"""
import sys
import pcbnew
import zones_strip


def main(src, dst):
    b = pcbnew.LoadBoard(src)
    blocks = []
    k = 0
    for z in b.Zones():
        if not z.GetZoneName().startswith('PWR_'):
            continue
        layer = z.GetLayer()
        polys = z.GetFilledPolysList(layer)
        for i in range(polys.OutlineCount()):
            ch = polys.Outline(i)
            pts = ' '.join(f'(xy {pcbnew.ToMM(ch.CPoint(j).x):.4f} {pcbnew.ToMM(ch.CPoint(j).y):.4f})'
                           for j in range(ch.PointCount()))
            k += 1
            blocks.append(
                f'\n\t(zone (net {z.GetNetCode()}) (net_name "{z.GetNetname()}") (layer "{b.GetLayerName(layer)}")'
                f' (uuid "{pcbnew.KIID().AsString()}") (name "ISL_{k}") (hatch edge 0.5)'
                f' (connect_pads yes (clearance 0)) (min_thickness 0.09) (filled_areas_thickness no)'
                f' (fill (thermal_gap 0.5) (thermal_bridge_width 0.5))'
                f' (polygon (pts {pts})))')
    zones_strip.strip(src, dst, ('PWR_',))
    txt = open(dst).read().rstrip()
    assert txt.endswith(')')
    open(dst, 'w').write(txt[:-1] + ''.join(blocks) + '\n)\n')
    print(f'{k} power islands exported as zones')


if __name__ == '__main__':
    main(*sys.argv[1:3])
