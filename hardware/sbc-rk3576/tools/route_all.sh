#!/usr/bin/env bash
# Full routing pipeline, from a placed + fanned-out board to the routed board.
# This is the order that worked (LOG.md #21-#29); each step is its own process
# because KiCad's Python API only handles one board per process reliably.
#
#   tools/route_all.sh [WORKDIR]      (default /tmp/sbc-route; takes a few hours)
#
# Result: $WORKDIR/final.kicad_pcb (copy it over kicad/rk3576-sbc.kicad_pcb once DRC is clean).
set -euo pipefail
cd "$(dirname "$0")"
W=${1:-/tmp/sbc-route}
mkdir -p "$W"
SRC=../kicad/rk3576-sbc
cp "$SRC.kicad_pcb" "$W/in.kicad_pcb"; cp "$SRC.kicad_pro" "$W/in.kicad_pro"

# 1. Unused via pads off (opens the inner layers between BGA fan-out vias),
#    then strip every routed track/via back to fan-out + plane stitching.
python3 via_nfp.py "$W/in.kicad_pcb" "$W/nfp.kicad_pcb"
python3 strip_routes.py "$W/nfp.kicad_pcb" "$W/a.kicad_pcb"

# 2. Grid maze router, shortest connection first, in DRC-driven passes
#    (KiCad's DRC lists at most 499 open connections per pass).
python3 maze_ripup.py "$W/a.kicad_pcb" "$W/a.kicad_pcb" --rounds 2 --no-rip

# 3. Late fan-out of the eMMC ball field (moves bottom-side parts off its via sites).
python3 fanout_region.py "$W/a.kicad_pcb" "$W/f.kicad_pcb" U701 --relocate

# 4. Power pours rebuilt as one connected region per rail (closes most power connections).
python3 pour_fix.py "$W/f.kicad_pcb" "$W/p.kicad_pcb"

# 5. Remaining connections: maze router with rip-up and reroute.
python3 maze_ripup.py "$W/p.kicad_pcb" "$W/r.kicad_pcb" --rounds 6

# 6. Debris clean-up, then length tuning of LPDDR5 lanes and differential pairs.
python3 cleanup.py "$W/r.kicad_pcb" "$W/c.kicad_pcb"
python3 tune_length.py "$W/c.kicad_pcb" "$W/final.kicad_pcb" --report "$W/tuning.md"
echo "routed board: $W/final.kicad_pcb"
