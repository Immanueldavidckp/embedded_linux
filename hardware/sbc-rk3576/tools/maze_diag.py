#!/usr/bin/env python3
"""Explain why maze_route.py cannot route a connection.

    python3 maze_diag.py BOARD.kicad_pcb DRC.json NETREGEX [--margin 4] [--png out.png]

For each matching open connection, flood-fills the free space (same rules as the
router: clearance-dilated obstacles, through vias where drill and pads fit) from
each end separately and reports how much room each end has. A tiny region at one
end means that end is boxed in (escape problem: needs a via-in-pad, a narrower
track or a neighbour moved); two large regions that never meet mean the corridor
between them is congested (needs rip-up of other routes or another layer).
Optionally renders the regions per layer to a PNG.
"""
import argparse, json, math, re
import numpy as np
from scipy import ndimage
import pcbnew
import maze_route as M


def flood(free, via_ok, seed):
    """free[L,h,w], via_ok[h,w] (layer change allowed), seed[L,h,w] -> reachable[L,h,w]."""
    reach = seed & free
    st = np.ones((3, 3), bool)
    while True:
        prev = reach.sum()
        for li in range(reach.shape[0]):
            # grow inside the connected free component that touches the current set
            lab, n = ndimage.label(free[li], structure=st)
            ids = np.unique(lab[reach[li]])
            ids = ids[ids > 0]
            reach[li] = np.isin(lab, ids)
        anyl = (reach & via_ok[None]).any(axis=0)
        reach |= anyl[None] & free & via_ok[None]
        if reach.sum() == prev:
            return reach


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('board'); ap.add_argument('drc'); ap.add_argument('nets')
    ap.add_argument('--margin', type=float, default=4.0)
    ap.add_argument('--png')
    a = ap.parse_args()
    b = pcbnew.LoadBoard(a.board)
    d = json.load(open(a.drc))
    r = M.Router(b, 0.025, a.margin)
    captured = {}

    def fake_search(self, conn_id, net, name, tw, clr, vd, vdr, allowed, src, dst, deff, wx0, wy0, w, h):
        captured.update(locals())
        return 'stop'
    M.Router.search = fake_search
    for k, u in enumerate(d['unconnected_items']):
        ia, ib = u['items']
        A, B = r.byuuid.get(ia['uuid']), r.byuuid.get(ib['uuid'])
        if A is None or not re.search(a.nets, A.GetNetname()):
            continue
        if A.GetClass() == 'ZONE' and B.GetClass() != 'ZONE':
            A, B, ia, ib = B, A, ib, ia
        captured.clear()
        r.margin = a.margin
        r.route(k, A, B, (ia['pos']['x'], ia['pos']['y']), (ib['pos']['x'], ib['pos']['y']), max_margin=a.margin)
        if not captured:
            print(k, A.GetNetname(), 'no cells'); continue
        c = captured
        tw, vd, vdr, deff, allowed = c['tw'], 0.30, 0.15, c['deff'], c['allowed']
        L, h, w = len(M.LAYERS), c['h'], c['w']
        mg = 0.025
        free = np.zeros((L, h, w), bool)
        padok = np.zeros((L, h, w), bool)
        for li in allowed:
            free[li] = deff[li][1] >= tw / 2 + mg
            padok[li] = deff[li][0] >= vd / 2 + mg
        he, dh, nv = deff['hole']
        via_ok = (he >= vdr / 2 + mg) & (dh >= vdr / 2 + mg) & nv & padok[list(allowed)].all(axis=0)
        seeds = []
        for cells in (c['src'], c['dst']):
            s = np.zeros((L, h, w), bool)
            for li, (m, ctr, need) in cells.items():
                s[li] |= m
                free[li] |= m
            seeds.append(s)
        ra, rb = flood(free, via_ok, seeds[0]), flood(free, via_ok, seeds[1])
        meet = (ra & rb).any()
        area = lambda x: x.sum() * 0.025 ** 2
        print(f'#{k} {A.GetNetname():20s} {A.GetClass()}->{B.GetClass()} '
              f'{math.dist((ia["pos"]["x"], ia["pos"]["y"]), (ib["pos"]["x"], ib["pos"]["y"])):5.1f} mm  '
              f'A-room {area(ra):7.2f} mm2  B-room {area(rb):7.2f} mm2  meet={meet}  '
              f'A-layers {[b.GetLayerName(M.LAYERS[l]) for l in range(L) if ra[l].any()]}  '
              f'B-layers {[b.GetLayerName(M.LAYERS[l]) for l in range(L) if rb[l].any()]}')
        if a.png:
            from PIL import Image
            tiles = []
            for li in range(L):
                img = np.zeros((h, w, 3), np.uint8)
                img[~free[li]] = (60, 60, 60)
                img[ra[li]] = (220, 60, 60)
                img[rb[li]] = (60, 120, 220)
                img[seeds[0][li]] = (255, 255, 0)
                img[seeds[1][li]] = (0, 255, 255)
                tiles.append(img)
            Image.fromarray(np.concatenate(tiles, axis=1)).save(a.png.replace('.png', f'_{k}.png'))


if __name__ == '__main__':
    main()
