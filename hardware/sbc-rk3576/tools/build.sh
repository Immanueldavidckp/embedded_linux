#!/usr/bin/env bash
# Regenerate everything from tools/design.py and run the checks.
# Needs KiCad 9 (kicad-cli + pcbnew python module).  Usage: tools/build.sh
set -euo pipefail
cd "$(dirname "$0")"
ROOT=..
KI=$ROOT/kicad
FAB=$ROOT/fab
DOC=$ROOT/docs

python3 gen_lib.py
python3 gen_schematic.py
# The PCB carries routing now. Re-placing it from scratch throws that away, so
# only do it on request:  REGEN_PCB=1 tools/build.sh   (then route.py again)
if [ "${REGEN_PCB:-0}" = 1 ]; then
    python3 gen_pcb.py
    python3 fanout.py
fi
python3 gen_bom.py

echo "== ERC"
kicad-cli sch erc --severity-all --exit-code-violations -o "$FAB/erc.rpt" "$KI/rk3576-sbc.kicad_sch"
echo "== DRC + schematic parity"
kicad-cli pcb drc --schematic-parity --severity-all -o "$FAB/drc.rpt" "$KI/rk3576-sbc.kicad_pcb" || true
grep -E "^\*\* Found" "$FAB/drc.rpt"
if grep -qE "^\*\* Found [1-9][0-9]* Footprint errors" "$FAB/drc.rpt"; then
    echo "DRC/parity errors - see fab/drc.rpt"; exit 1
fi

python3 length_report.py || true
echo "== Fabrication outputs (DRAFT until DRC shows 0 unconnected and lengths are tuned)"
rm -rf "$FAB/gerbers-draft" && mkdir -p "$FAB/gerbers-draft"
CU=$(python3 -c "import stackup; print(','.join(stackup.COPPER))")   # all copper layers, from stackup.py
kicad-cli pcb export gerbers --layers "$CU",F.Paste,B.Paste,F.SilkS,B.SilkS,F.Mask,B.Mask,Edge.Cuts \
    --subtract-soldermask -o "$FAB/gerbers-draft/" "$KI/rk3576-sbc.kicad_pcb" >/dev/null
kicad-cli pcb export drill --format excellon --excellon-separate-th --generate-map --map-format pdf \
    -o "$FAB/gerbers-draft/" "$KI/rk3576-sbc.kicad_pcb" >/dev/null
kicad-cli pcb export pos --format csv --units mm --side both --exclude-dnp \
    -o "$FAB/cpl_kicad.csv" "$KI/rk3576-sbc.kicad_pcb" >/dev/null
python3 - "$FAB" <<'EOF'
import csv, sys, os
fab = sys.argv[1]
rows = list(csv.DictReader(open(os.path.join(fab, 'cpl_kicad.csv'))))
with open(os.path.join(fab, 'cpl_jlcpcb.csv'), 'w', newline='') as f:
    w = csv.writer(f)
    w.writerow(['Designator', 'Mid X', 'Mid Y', 'Layer', 'Rotation'])
    for r in rows:
        w.writerow([r['Ref'], r['PosX'] + 'mm', r['PosY'] + 'mm', 'Top' if r['Side'] == 'top' else 'Bottom', r['Rot']])
print(f'CPL: {len(rows)} placements')
EOF

echo "== Documentation exports"
mkdir -p "$DOC/img"
kicad-cli sch export pdf -o "$DOC/schematic.pdf" "$KI/rk3576-sbc.kicad_sch" >/dev/null
kicad-cli pcb export pdf --layers F.Fab,F.CrtYd,Edge.Cuts --mode-single -o "$DOC/assembly_top.pdf" "$KI/rk3576-sbc.kicad_pcb" >/dev/null
kicad-cli pcb export pdf --layers B.Fab,B.CrtYd,Edge.Cuts --mirror --mode-single -o "$DOC/assembly_bottom.pdf" "$KI/rk3576-sbc.kicad_pcb" >/dev/null
kicad-cli pcb render --side top --width 1600 --height 1100 --quality high -o "$DOC/img/pcb_top.png" "$KI/rk3576-sbc.kicad_pcb" >/dev/null
kicad-cli pcb render --side bottom --width 1600 --height 1100 --quality high -o "$DOC/img/pcb_bottom.png" "$KI/rk3576-sbc.kicad_pcb" >/dev/null
kicad-cli pcb render --side top --rotate "-35,0,25" --perspective --width 1600 --height 1100 --quality high \
    -o "$DOC/img/pcb_iso.png" "$KI/rk3576-sbc.kicad_pcb" >/dev/null || true
echo "done."
