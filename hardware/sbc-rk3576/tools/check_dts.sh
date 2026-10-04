#!/usr/bin/env bash
# Compile software/rk3576-sbc.dts against a mainline kernel tree (default: a sparse
# clone in $LINUX). Usage: LINUX=~/src/linux tools/check_dts.sh
set -euo pipefail
cd "$(dirname "$0")/.."
LINUX=${LINUX:-/tmp/claude-0/linux}
DTS=$LINUX/arch/arm64/boot/dts/rockchip
OUT=build/dts && mkdir -p "$OUT"
cpp -nostdinc -undef -D__DTS__ -x assembler-with-cpp -I "$DTS" -I "$LINUX/include" \
    -o "$OUT/rk3576-sbc.pre.dts" software/rk3576-sbc.dts
dtc -I dts -O dtb -W no-unit_address_vs_reg -o "$OUT/rk3576-sbc.dtb" "$OUT/rk3576-sbc.pre.dts"
echo "OK: $OUT/rk3576-sbc.dtb ($(stat -c %s "$OUT/rk3576-sbc.dtb") bytes)"
