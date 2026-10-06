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
