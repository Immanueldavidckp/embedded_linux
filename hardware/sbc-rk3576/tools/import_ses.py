#!/usr/bin/env python3
"""Import a Freerouting session (build/route/board.ses) into the board, refill
zones, report unrouted count. Runs in its own process: re-loading a board in the
same process that removed zones returns a broken SWIG object (KiCad 9.0)."""
import os, sys
import pcbnew

HERE = os.path.dirname(os.path.abspath(__file__))
PCB = os.path.join(HERE, '..', 'kicad', 'rk3576-sbc.kicad_pcb')
SES = os.path.join(HERE, '..', 'build', 'route', 'board.ses')


def main(ses=SES):
    b = pcbnew.LoadBoard(PCB)
    if not pcbnew.ImportSpecctraSES(b, ses):
        raise SystemExit('SES import failed')
    pcbnew.SaveBoard(PCB, b)
    b = pcbnew.LoadBoard(PCB)
    pcbnew.ZONE_FILLER(b).Fill(b.Zones())
    pcbnew.SaveBoard(PCB, b)
    c = b.GetConnectivity()
    c.RecalculateRatsnest()
    print(f'imported {ses}: unrouted connections now {c.GetUnconnectedCount(False)}; '
          f'tracks+vias {len(b.GetTracks())}')


if __name__ == '__main__':
    main(*sys.argv[1:])
