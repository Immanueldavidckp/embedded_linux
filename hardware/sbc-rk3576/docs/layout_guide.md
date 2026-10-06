# Layout guide: placement done, routing rules for the next step

## Board

- 100 × 72 mm, R3 corners, 4× M2.5 holes 3.5 mm in from each corner (93 × 65 mm pattern).
- **10 layers** (rev A2; rev A1 was 8), 1.6 mm, ENIG. Stackup is defined in `tools/stackup.py` and in the
  PCB file (Board Setup → Physical Stackup):

| Layer | Use | Dielectric below |
|---|---|---|
| L1 F.Cu | BGA escape, HDMI/PCIe/USB3 pairs, eMMC | 3313 prepreg 0.0994 mm, εr 4.1 |
| L2 In1 | **solid GND** (reference for L1/L3) | core 0.15 mm |
| L3 In2 | LPDDR5 byte lanes (DQ/DMI/RDQS/WCK) | 2116 prepreg 0.13 mm |
| L4 In3 | signal (rev A2), routed orthogonal to L3 (dual stripline) | core 0.15 mm |
| L5 In4 | power: core and DDR rails (one connected pour per rail, `pour_fix.py`) | 7628 prepreg 0.32 mm |
| L6 In5 | **solid GND** | core 0.15 mm |
| L7 In6 | LPDDR5 CA/CK/CS, low-speed | 2116 prepreg 0.13 mm |
| L8 In7 | signal (rev A2), routed orthogonal to L7 (dual stripline) | core 0.15 mm |
| L9 In8 | power: 5 V, 3V3, 1V8 board-wide rails | 3313 prepreg 0.0994 mm |
| L10 B.Cu | BGA decoupling, M.2, microSD, short stubs | — |

Why 10: with 4 signal layers the area between the RK3576 and the LPDDR5 was full and 72 connections could
not be placed (LOG.md #31-#33); two more signal layers took that to the low tens in one pass.
Slow nets (PMIC feedback/control, GPIO, UART) may also cross the power layers (`maze_ripup.py --pwr-ok`).

Get the fab's impedance calculator result (JLCPCB 10-layer 1.6 mm stack) **before** routing. The net-class
widths below are starting values for this stackup.

## Net classes (set in `kicad/rk3576-sbc.kicad_pro`)

| Class | Nets | Target | Track / gap (mm) |
|---|---|---|---|
| LPDDR5 | `LP5_*`, `DDR_RESET_L` | 40 Ω SE, 80 Ω diff (CK/WCK/RDQS) | 0.09 / 0.12 |
| HDMI_100R | `HDMI_TX_D*`, `HDMI_D*` | 100 Ω diff | 0.10 / 0.16 |
| PCIE_85R | `PCIE0_*`, `M2_PET*` | 85 Ω diff | 0.13 / 0.15 |
| USB_90R | `USBC_D*`, `USB3*`, `USB3A_*` | 90 Ω diff | 0.11 / 0.15 |
| EMMC_SD | `EMMC_*`, `SD_*` | 50 Ω SE | 0.10 |
| POWER | `VDD*`, `VCC*`, `VBUS*`, buck SW nodes | — | 0.30 min, use pours |

Design rules: 0.09 mm min track and clearance; via 0.35/0.20 mm (min 0.25/0.15); blind vias and microvias
allowed; 0.3 mm copper-to-edge.

## Placement rationale (what is on the board now)

```
 top edge:   [2V0][MASKROM POWER RESET]                   [3V3_S0 sw]
             [1V1]   PMIC RK806 + 10 inductors              eMMC (U701)
 left:       [VDD2L] LPDDR5 (U601) <-5 mm-> RK3576 (U401)   USB-VBUS sw     -> USB3-A (right edge)
             LEDs                    HDMI term FETs  24 MHz   USB3 ESD
 bottom:     USB-C(J101)  ESD  HDMI(J901) + ESD   M.2 3V3 buck   DEBUG UART(J501)
 underside:  microSD (left edge), SoC + DRAM + eMMC decoupling under each BGA,
             M.2 socket (J801, x=66) with the card lying over the SoC area, M2 standoffs for 2230/2242
```

- **LPDDR5 sits 5 mm left of the SoC** because the RK3576 DDR balls are on its column-1 (left) edge.
  The goal is the shortest possible byte lanes, with no lane crossing another.
- **PMIC sits directly above the SoC.** The 5–6.5 A core rails get the shortest, widest path on L4, and the
  BUCK1 inductor (0.24 µH, 8 A) belongs next to the CPU_BIG balls (tighten this once the real land pattern is in).
- **High-speed connectors are on the right and bottom edges,** where RK3576 brings out HDMI/PCIe/USB3
  (columns 26–29, rows AK/AL).
- 222 parts are on the bottom: BGA decaps under the balls, the M.2 socket, microSD and the SD power switch.
  Components under the M.2 card must be ≤ 1.5 mm tall (a 4.2 mm socket leaves about 2.5 mm).

## Routing rules for the next step

**LPDDR5 (do this first, everything else routes around it)**
- Route each byte lane (DQ[7:0] + DMI + RDQS_t/c + WCK_t/c) on one layer (L3) with one via transition
  at most. Match DQ to its RDQS within ±0.5 mm. Match WCK to RDQS within the byte.
- CA[6:0], CS, CK on L6, referenced to L5 GND. Match CA to CK within ±1 mm.
- Keep 3W spacing between byte lanes. Never route across a split in L4.
- Total length of 15–25 mm is ideal at this spacing. Run the Rockchip DDR training tool on the first boards.

**HDMI 2.1 / PCIe / USB3**
- Intra-pair skew ≤ 0.1 mm (HDMI/PCIe) and ≤ 0.15 mm (USB3). Put the AC caps close to the connector side
  of each lane. Place ESD between connector and caps, directly in line (TPD4E05U06 is flow-through).
- No stubs. If you change layer, add a GND stitching via within 1 mm of each signal via.

**Power**
- Each buck's hot loop (VIN cap → IC → GND) on the same layer as the IC, under 5 mm.
- Under the BGA, use via-in-pad (filled and capped, POFV). The 0.55 mm pitch areas of the FCCSP need it.

## Order of work

1. Swap in the real RK3576 land pattern (same pad names).
2. Fan out the SoC and DRAM (dog-bone or via-in-pad) and lock the escape vias.
3. Route LPDDR5 → HDMI → PCIe → USB3 → eMMC/SD → power → low speed.
4. Pour L4 power islands. Stitch GND every 2–3 mm along high-speed routes and the board edge.
5. Run DRC to zero unconnected items, then get SI/PI review (or at least the Rockchip HW checklist).

## Finishing the last 14 connections

Everything else is routed and DRC-clean. These 14 are where the automatic router stopped (pockets walled in
by neighbouring routes; rip-up beyond a few items cascades). In KiCad: open `kicad/rk3576-sbc.kicad_pro`,
press **X** (Route Single Track) with **Shove** mode on (Route → Interactive Router Settings), and click the
ratsnest line of each. `tools/maze_diag.py BOARD DRC.json NETREGEX` shows the free space at each end.

| Net | From → to | What is in the way / how to finish |
|---|---|---|
| RGMII_RXD2, RXD3, TXCTL | U401 B12 / 1A10 / A11 → U1301 pins 23 / 22 / 19 (≈ 45 mm) | the other RGMII lines took the corridor; shove them aside on L3/L4, route on the same layer as RXD0/RXD1 (keep the group within ±1 mm, `length_report.py`) |
| SD_D1 | J701 pin 8 (bottom) → U401 B25 (≈ 45 mm) | follow SD_D0/D2 on L7/L8; one via near J701 |
| PCIE0_TXN | U401 P28 → C802 pin 1 (≈ 28 mm) | route next to PCIE0_TXP as a pair (Route → Differential Pair, 85 Ω class); then `tune_length.py` |
| PMIC_PWRCTRL3, PWRON_L, PMIC_FB6, VDDA_DDR_PLL_S0 | U201 (PMIC) pins 16 / 4 / 31 / 12 → SoC / caps | the PMIC's pin fan-out on F.Cu is boxed by its own switch-node copper; drop a via right at each pin (0.25/0.15) and run on L3/L4 (slow signals; L5/L9 are allowed for them too) |
| LP5_DMI0_B | 2.2 mm gap between two pieces near (33.9, 40.1) | join on L7 (In6) |
| VDD_NPU_S0 | 0.7 mm gap at (60, 30.5) | a 0.3 mm via from the B.Cu stub into the L5 pour |
| VCC_2V0_PLDO_S3 | C303 → C249 (≈ 26 mm) | one 0.25 mm track on L5/L9 (cuts through other pours; re-run `tools/pour_fix.py` after) |
| VCCA_1V8_S0, VCC_1V8_S3 | zone split into islands (L5 / L9) | widen the neck between the islands in the zone outline, or add a short 0.2 mm track across it; refill |

After the last connection: `tools/cleanup.py` → `tools/tune_length.py` → `tools/build.sh` and DRC must report
0 unconnected items before the Gerbers leave `fab/gerbers-draft/`.
