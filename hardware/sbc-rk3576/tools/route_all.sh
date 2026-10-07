#!/usr/bin/env bash
# Full routing pipeline, from a placed + fanned-out board to the routed board (rev A2, 10 layers).
# This is the sequence that produced the committed board (LOG.md #21-#35); each step is its own
# process because KiCad's Python API only handles one board per process reliably. Expect several
# hours on 4 cores; results vary a little from run to run. Run it on a copy, never on kicad/ directly.
#
#   tools/route_all.sh [WORKDIR]      (default /tmp/sbc-route)
#
# Result: $WORKDIR/final.kicad_pcb (+ .kicad_pro). Copy it over kicad/rk3576-sbc.kicad_pcb only if its
# DRC shows 0 clearance/hole/short errors and fewer unconnected items than the committed board.
set -euo pipefail
cd "$(dirname "$0")"
W=${1:-/tmp/sbc-route}
mkdir -p "$W"
SRC=../kicad/rk3576-sbc
cp "$SRC.kicad_pcb" "$W/in.kicad_pcb"; cp "$SRC.kicad_pro" "$W/in.kicad_pro"
# slow nets that may cross the power layers (pours are re-planned around them)
SLOW='^(PMIC_|PWRON_L|PHY_INT_L|PHY_LED|DBG_UART|PCIE0_WAKE_L|WIFI_PD|SD_DET_L|USB3_OTG0_REXT|ETH_MDIO|ETH_MDC|DDR_ZQ|HDMI_D[0-3]_TERM|VDD|VCC|VBUS|HDMI_5V)'
OPTS="--mg 1.25 --max-expand 30000000"

# 1. Unused via pads off, strip all routing back to fan-out + plane stitching.
python3 via_nfp.py "$W/in.kicad_pcb" "$W/nfp.kicad_pcb"
python3 strip_routes.py "$W/nfp.kicad_pcb" "$W/a.kicad_pcb"

# 2. eMMC fan-out (it was missed in rev A0/A1) with the bottom-side parts moved off its via sites.
python3 fanout_region.py "$W/a.kicad_pcb" "$W/f.kicad_pcb" U701 --relocate

# 3. Maze router, shortest first, plain passes (KiCad's DRC lists <= 499 open connections per pass).
python3 maze_ripup.py "$W/f.kicad_pcb" "$W/r.kicad_pcb" --rounds 6 --no-rip $OPTS

# 4. Power pours re-planned as one connected region per rail.
python3 pour_fix.py "$W/r.kicad_pcb" "$W/p.kicad_pcb"

# 5. Remaining connections: slow nets may use the power layers; small rip budget.
python3 maze_ripup.py "$W/p.kicad_pcb" "$W/q.kicad_pcb" --rounds 6 --max-rip 6 "--pwr-ok=$SLOW" $OPTS

# 6. Signal nets still open are usually stranded inside a BGA ball field (no new via fits there):
#    strip them and route them again from their pads, first, then plain passes.
kicad-cli pcb drc --format json --severity-all -o "$W/q.drc.json" "$W/q.kicad_pcb" >/dev/null || true
NETS=$(python3 - "$W/q.drc.json" <<'EOF'
import json, re, sys
d = json.load(open(sys.argv[1]))
nets = {u['items'][0]['description'].split('[')[1].split(']')[0] for u in d['unconnected_items']}
sig = sorted(n for n in nets if not re.match(r'^(GND$|VDD|VCC|VBUS)', n))
print('^(' + '|'.join(re.escape(n) for n in sig) + ')$' if sig else '^$')
EOF
)
python3 strip_routes.py "$W/q.kicad_pcb" "$W/s.kicad_pcb" --nets "$NETS"
python3 maze_ripup.py "$W/s.kicad_pcb" "$W/s.kicad_pcb" --rounds 6 --no-rip "--first=$NETS" "--pwr-ok=$SLOW" $OPTS

# 7. Debris clean-up, then length tuning of LPDDR5 lanes and differential pairs.
python3 cleanup.py "$W/s.kicad_pcb" "$W/c.kicad_pcb"
python3 tune_length.py "$W/c.kicad_pcb" "$W/final.kicad_pcb" --report "$W/tuning.md"
echo "routed board: $W/final.kicad_pcb (check: kicad-cli pcb drc --severity-all ...)"
