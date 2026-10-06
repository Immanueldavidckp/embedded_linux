#!/usr/bin/env python3
"""Rip-up and reroute rounds on top of maze_route.py.

    python3 maze_ripup.py IN.kicad_pcb OUT.kicad_pcb [--rounds 8] [--pen 12] [--nets REGEX]

A maze router that routes nets one at a time eventually walls in the late
ones: the RK3576 balls in the middle of the field find every channel out of
the BGA taken by routes laid earlier (maze_diag.py shows a closed pocket). A
layout engineer then moves a few existing tracks. This does the same, in the
PathFinder spirit:

  * a connection that fails normally is searched again where routed copper
    (tracks, unlocked vias) is crossable at a price per cell; pads, locked
    fan-out vias, keepouts and the board edge stay hard;
  * whatever routed copper the new path really collides with (exact KiCad
    shapes, clearances and drill rules) is removed, which re-opens those
    connections as short gaps;
  * each round re-reads the open connections from KiCad's DRC and routes them
    again, with the price rising for nets that keep getting ripped, until
    nothing is open or a round makes no progress.
Every round ends with a zone refill and a DRC; routed copper involved in a
clearance/drill violation is removed and re-routed in the next round.
"""
import argparse, json, math, os, re, subprocess, sys, time
import pcbnew
import maze_route as M

MM, TOMM = pcbnew.FromMM, pcbnew.ToMM
HERE = os.path.dirname(os.path.abspath(__file__))
# board.Remove() hands ownership to Python; if the wrapper is then garbage-collected the
# C++ object is freed while KiCad still references it and the SWIG runtime falls apart.
# Keep every removed item alive until the process ends.
GRAVE = []
BAD = {'clearance', 'hole_clearance', 'hole_to_hole', 'shorting_items', 'tracks_crossing',
       'copper_edge_clearance'}


class RipRouter(M.Router):
    def __init__(self, board, res, margin, pen, history):
        super().__init__(board, res, margin)
        self.rip, self.rip_pen, self.history = False, pen, history
        self.max_rip = 8
        self.removed, self.gone_ids = 0, set()

    def route_conn(self, k, A, B, pa, pb, allow_rip):
        res = self.route(k, A, B, pa, pb)
        if res == 'ok' or not allow_rip:
            return res
        self.rip = True
        try:
            n0 = len(self.added)
            res = self.route(k, A, B, pa, pb, max_margin=6.0)
            if res == 'ok':
                new = [it for cid, it in self.added[n0:] if cid == k]
                tw, clr, _ = M.net_class(A.GetNetname())
                ripped = self.resolve(new, A.GetNetCode(), clr)
                res = f'ok-rip{ripped}' if ripped >= 0 else 'fail-toomanyrips'
        finally:
            self.rip = False
        return res

    @staticmethod
    def shape(it, layer):
        # explicit SHAPE_SEGMENTs: the only shape whose Collide(SHAPE, clearance) is fully wrapped
        if it.GetClass() == 'PCB_VIA':      # treat a via as flashed everywhere (conservative)
            return pcbnew.SHAPE_SEGMENT(it.GetPosition(), it.GetPosition(), it.GetWidth(pcbnew.F_Cu))
        if it.GetClass() == 'PCB_TRACK':
            return pcbnew.SHAPE_SEGMENT(it.GetStart(), it.GetEnd(), it.GetWidth())
        return it.GetEffectiveShape(layer)

    def collides(self, new, other, clr):
        for l in M.LAYERS:
            if not (new.IsOnLayer(l) and other.IsOnLayer(l)):
                continue
            c = max(clr, TOMM(other.GetOwnClearance(l)))
            # vias count as padded on every layer: FlashLayer() is stale for copper added this round
            if self.shape(new, l).Collide(self.shape(other, l), MM(c) - 1000):
                return True
        for h_it, o_it in ((new, other), (other, new)):
            if h_it.GetClass() != 'PCB_VIA':
                continue
            hole = h_it.GetEffectiveHoleShape()
            if o_it.GetClass() == 'PCB_VIA':
                d = (h_it.GetPosition() - o_it.GetPosition()).EuclideanNorm()
                if TOMM(d) < TOMM(h_it.GetDrill() + o_it.GetDrill()) / 2 + M.HOLE2HOLE + 0.005:
                    return True
            for l in M.LAYERS:
                if o_it.IsOnLayer(l) and self.shape(o_it, l).Collide(hole, MM(M.HOLE_CLR) - 1000):
                    return True
        return False

    def resolve(self, new_items, net, clr):
        """Remove routed copper of other nets that the new path collides with. If that would
        take more than max_rip items, undo the new path instead and return -1."""
        R, gone = self.R, []
        for it in new_items:
            bb = it.GetBoundingBox()
            for o in R.query(TOMM(bb.GetLeft()) - 0.5, TOMM(bb.GetTop()) - 0.5,
                             TOMM(bb.GetRight()) + 0.5, TOMM(bb.GetBottom()) + 0.5):
                if o.GetNetCode() == net or not R.removable(o) or any(o is g for g in gone):
                    continue
                if self.collides(it, o, clr):
                    gone.append(o)
        if len(gone) > self.max_rip:
            for it in new_items:
                self.b.Remove(it)
                GRAVE.append(it)
            R.unstamp(new_items)
            return -1
        for o in gone:
            self.gone_ids.add(o.m_Uuid.AsString())
            self.history[o.GetNetname()] = self.history.get(o.GetNetname(), 0) + 1
            self.b.Remove(o)
            GRAVE.append(o)
        if gone:
            R.unstamp(gone)
        self.removed += len(gone)
        return len(gone)


def refill(path):
    subprocess.run([sys.executable, '-c', f'''
import pcbnew
b = pcbnew.LoadBoard({path!r})
pcbnew.ZONE_FILLER(b).Fill(b.Zones())
pcbnew.SaveBoard({path!r}, b)
'''], check=True)


def drop_violations(b, drc):
    """Remove routed copper (unlocked tracks/vias) involved in clearance/drill errors."""
    byid = {t.m_Uuid.AsString(): t for t in b.GetTracks()}
    gone = set()
    for v in drc['violations']:
        if v['type'] not in BAD:
            continue
        cand = [byid[i['uuid']] for i in v['items'] if i['uuid'] in byid and not byid[i['uuid']].IsLocked()]
        if cand:
            # the shorter piece goes (a short new stub rather than a long established route)
            victim = min(cand, key=lambda t: t.GetLength() if t.GetClass() != 'PCB_VIA' else 0.3e6)
            gone.add(victim.m_Uuid.AsString())
    for u in gone:
        b.Remove(byid[u])
        GRAVE.append(byid[u])
    return gone


def one_round(a, rnd):
    """One rip-up round in this process (KiCad's Python API only loads one board reliably)."""
    work = a.out
    drc = json.load(open(work + '.drc.json'))
    hist_file = work + '.history.json'
    history = json.load(open(hist_file)) if os.path.exists(hist_file) else {}
    b = pcbnew.LoadBoard(work)
    gone = drop_violations(b, drc)
    if gone:
        print(f'round {rnd}: removed {len(gone)} routed item(s) in DRC violations', flush=True)
    r = RipRouter(b, a.res, a.margin, a.pen * (1 + 0.5 * rnd), history)
    r.mg_cells = a.mg
    r.gone_ids |= gone
    conns = []
    for k, u in enumerate(drc['unconnected_items']):
        ia, ib = u['items']
        A, B = r.byuuid.get(ia['uuid']), r.byuuid.get(ib['uuid'])
        if A is None or B is None or not re.search(a.nets, A.GetNetname()) or re.search(a.exclude, A.GetNetname()):
            continue
        pa, pb = (ia['pos']['x'], ia['pos']['y']), (ib['pos']['x'], ib['pos']['y'])
        if math.dist(pa, pb) > a.max_len:
            continue
        if A.GetClass() == 'ZONE' and B.GetClass() != 'ZONE':
            A, B, pa, pb = B, A, pb, pa
        conns.append((math.dist(pa, pb), k, A, B, pa, pb))
    # priority groups first (e.g. LPDDR5 between the two BGAs), each shortest first
    pri = [re.compile(p) for p in a.first.split(',') if p]
    rank = lambda name: next((i for i, p in enumerate(pri) if p.search(name)), len(pri))
    conns.sort(key=lambda c: (rank(c[2].GetNetname()), c[0]))
    stats, t0 = {}, time.time()
    for n, (dist, k, A, B, pa, pb) in enumerate(conns):
        if A.m_Uuid.AsString() in r.gone_ids or B.m_Uuid.AsString() in r.gone_ids:
            continue                      # an end was ripped earlier this round; next round has it
        try:
            res = r.route_conn(k, A, B, pa, pb, allow_rip=not a.no_rip)
        except Exception as e:
            res = f'error:{type(e).__name__}:{e}'
        key = res.split('-rip')[0] if res.startswith('ok') else res
        stats[key] = stats.get(key, 0) + 1
        print(f'  [{n + 1}/{len(conns)}] {A.GetNetname():22s} {dist:6.2f} mm {res} ({time.time() - t0:.0f} s)',
              flush=True)
    print(f'round {rnd}: {stats}, ripped {r.removed} item(s)', flush=True)
    pcbnew.SaveBoard(work, b)
    json.dump(history, open(hist_file, 'w'))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('inp'); ap.add_argument('out')
    ap.add_argument('--rounds', type=int, default=8)
    ap.add_argument('--pen', type=float, default=60.0, help='cost per cell of crossing routed copper')
    ap.add_argument('--nets', default='.')
    ap.add_argument('--exclude', default='^$')
    ap.add_argument('--res', type=float, default=0.025)
    ap.add_argument('--margin', type=float, default=2.5)
    ap.add_argument('--max-len', type=float, default=1e9, help='skip connections longer than this (mm)')
    ap.add_argument('--first', default='', help='comma-separated net regexes routed first, in this order')
    ap.add_argument('--no-rip', action='store_true', help='plain multi-pass routing (no rip-up)')
    ap.add_argument('--mg', type=float, default=1.0, help='clearance safety margin in grid cells')
    ap.add_argument('--one-round', type=int, default=-1, help=argparse.SUPPRESS)
    a = ap.parse_args()
    if a.one_round >= 0:
        return one_round(a, a.one_round)
    if os.path.abspath(a.inp) != os.path.abspath(a.out):
        import shutil
        shutil.copy(a.inp, a.out)
        # the design rules and net classes live in the project file next to the board
        shutil.copy(a.inp.replace('.kicad_pcb', '.kicad_pro'), a.out.replace('.kicad_pcb', '.kicad_pro'))
    best = None
    for rnd in range(a.rounds):
        drc = M.run_drc(a.out, a.out + '.drc.json')
        open_n = len(drc['unconnected_items'])
        errs = sum(1 for v in drc['violations'] if v['type'] in BAD)
        print(f'round {rnd}: {open_n} open connections, {errs} clearance/drill errors', flush=True)
        if open_n == 0 and errs == 0:
            break
        if best is not None and open_n + errs >= best and rnd >= 3:
            print('no progress; stopping', flush=True)
            break
        best = open_n + errs if best is None else min(best, open_n + errs)
        subprocess.run([sys.executable, os.path.abspath(__file__), a.out, a.out, '--one-round', str(rnd),
                        '--pen', str(a.pen), '--nets', a.nets, '--res', str(a.res), '--margin', str(a.margin),
                        '--max-len', str(a.max_len), '--first', a.first, '--exclude', a.exclude, '--mg', str(a.mg)] + (['--no-rip'] if a.no_rip else []),
                       check=True)
        refill(a.out)
    print('done', flush=True)


if __name__ == '__main__':
    main()
