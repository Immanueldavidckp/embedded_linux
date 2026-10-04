#!/usr/bin/env python3
"""Autoroute the placed board with Freerouting (Specctra DSN -> SES round trip).

    python3 route.py [--passes N] [--threads N] [--jar path/to/freerouting.jar]

Writes kicad/rk3576-sbc.kicad_pcb in place (keeps a copy of the unrouted board
as kicad/rk3576-sbc.unrouted.kicad_pcb.bak) and prints the remaining unrouted
connection count. Freerouting does not length-match, so DDR/HDMI/PCIe/USB3
still need interactive tuning in KiCad afterwards (see length_report.py).
"""
import argparse, os, shutil, subprocess, time
import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
KICAD = os.path.join(HERE, '..', 'kicad')
PCB = os.path.join(KICAD, 'rk3576-sbc.kicad_pcb')
WORK = os.path.join(HERE, '..', 'build', 'route')


def unrouted(board):
    c = board.GetConnectivity()
    c.RecalculateRatsnest()
    return c.GetUnconnectedCount(False)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--passes', type=int, default=40)
    ap.add_argument('--threads', type=int, default=os.cpu_count() or 2)
    ap.add_argument('--jar', default=os.environ.get('FREEROUTING_JAR', '/tmp/claude-0/fr/fr.jar'))
    ap.add_argument('--timeout', default='01:40:00', help='freerouting job timeout (hh:mm:ss); result is saved')
    a = ap.parse_args()
    os.makedirs(WORK, exist_ok=True)
    dsn, ses = os.path.join(WORK, 'board.dsn'), os.path.join(WORK, 'board.ses')

    board = pcbnew.LoadBoard(PCB)
    before = unrouted(board)
    shutil.copy(PCB, PCB.replace('.kicad_pcb', '.before-route.kicad_pcb.bak'))
    if not pcbnew.ExportSpecctraDSN(board, dsn):
        raise SystemExit('DSN export failed')
    # L2/L5/L7 are solid GND planes: mark them 'power' so the router only drops
    # vias into them and never cuts the reference plane with a signal trace.
    txt = open(dsn).read()
    for lyr in ('In1.Cu', 'In4.Cu', 'In6.Cu'):
        txt = txt.replace(f'(layer {lyr}\n      (type signal)', f'(layer {lyr}\n      (type power)')
    open(dsn, 'w').write(txt)
    t0 = time.time()
    cmd = ['java', '-Xmx12g', '-jar', a.jar, '-de', dsn, '-do', ses, '-mp', str(a.passes),
           '-mt', str(a.threads), '--gui.enabled=false', f'--router.job_timeout={a.timeout}',
           '--profile.allow_telemetry=false', '--usage_and_diagnostic_data.disable_analytics=true',
           '--api_server.enabled=false']
    print('running:', ' '.join(cmd), flush=True)
    if os.path.exists(ses):
        os.remove(ses)
    subprocess.run(cmd, check=False)
    if not os.path.exists(ses):
        raise SystemExit('freerouting produced no session file')
    print(f'freerouting finished in {(time.time() - t0) / 60:.1f} min', flush=True)

    board = pcbnew.LoadBoard(PCB)
    if not pcbnew.ImportSpecctraSES(board, ses):
        raise SystemExit('SES import failed')
    pcbnew.ZONE_FILLER(board).Fill(board.Zones())
    pcbnew.SaveBoard(PCB, board)
    board = pcbnew.LoadBoard(PCB)
    after = unrouted(board)
    print(f'unrouted connections: {before} -> {after}; tracks+vias: {len(board.GetTracks())}')


if __name__ == '__main__':
    main()
