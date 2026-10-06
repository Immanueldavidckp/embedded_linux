# Manufacturing package and release checklist

## Fabrication spec (send this with the Gerbers)

| Item | Value |
|---|---|
| Layers | 10 (rev A2; see `tools/stackup.py`) |
| Thickness | 1.6 mm ±10 % |
| Stackup | 10-layer 1.6 mm, symmetric (see layout_guide.md / `tools/stackup.py`) |
| Impedance control | yes: 40/50 Ω SE, 80/85/90/100 Ω diff (see net classes) |
| Min track / space | 0.09 / 0.09 mm (3.5/3.5 mil) |
| Min via | 0.20 mm drill / 0.35 mm pad (0.15/0.25 allowed) |
| Via-in-pad | **yes**: epoxy filled + copper capped (POFV) under the BGAs |
| Surface finish | ENIG (flat pads for 0.5–0.65 mm pitch BGAs) |
| Solder mask / silk | green / white, both sides |
| Copper | 1 oz outer (finished), 0.5 oz inner |
| Outline | 100 × 72 mm, R3 corners; panelize 2×2 with V-score + 5 mm rails and fiducials |

## Assembly spec

| Item | Value |
|---|---|
| Sides | double-sided SMT (bottom first: decaps, M.2, microSD) + 4 THT parts (USB-C shell, HDMI shell, USB-A, debug header) |
| Placements | 468 (see `fab/cpl_jlcpcb.csv`); DNP footprints are excluded |
| Fine pitch | RK3576 FCCSP (0.55 mm), eMMC (0.5 mm), LPDDR5 (0.8 × 0.7 mm), 0201 passives |
| Inspection | **X-ray all BGAs** (SoC, LPDDR5, eMMC). AOI both sides |
| Stencil | 0.10 mm, step-down to 0.08 mm at the FCCSP if the land pattern needs it |
| Moisture | LPDDR5/eMMC/SoC are MSL3: bake per J-STD-033 if open beyond floor life |

## Files

| File | Use |
|---|---|
| `fab/bom.csv` | engineering BOM: qty, refs, value, footprint, MPN, maker, LCSC#, price |
| `fab/bom_jlcpcb.csv` | JLCPCB upload format (Comment, Designator, Footprint, LCSC Part #) |
| `fab/cpl_jlcpcb.csv` / `fab/cpl_kicad.csv` | pick-and-place (centroid, rotation, side) |
| `fab/gerbers-draft/` | Gerber X2 + Excellon (PTH/NPTH) + job file. **Draft only: unrouted.** |
| `fab/cost_summary.md` | per-variant cost roll-up |
| `docs/assembly_top.pdf`, `docs/assembly_bottom.pdf` | assembly drawings (fab layer, refs) |

Rotations in the CPL are KiCad's. JLCPCB's preview sometimes needs ±90° on SOT-23/USON parts. Check
every IC in their 3D preview before you pay.

## Release checklist (rev A0 → rev A1, orderable)

- [x] Real RK3576 land pattern (LCSC C42388007, 698/698 ball IDs match). Cross-check against Rockchip's HDK drawing.
- [x] RK806S-5 BUCK/LDO→rail mapping verified against mainline `rk3576-rock-4d.dts` (rev A1).
- [ ] Confirm the VCCIO bank voltages (sheet 04 `pwr_map`) against the RK3576 HW design guide, especially
      VCCIO1 (SDMMC0), VCCIO4/5, and the GPIO4_C bank used for HDMI DDC/HPD.
- [ ] Check the M.2 socket footprint against the chosen part (LOTES APCI0026 / Amphenol MDT420M),
      including standoff distances for 2230/2242.
- [ ] Route everything; DRC must report 0 unconnected items.
- [ ] Impedance coupons on the panel. Fab confirms the stackup in writing.
- [ ] SI check on LPDDR5 byte lanes (at least length/skew reports). PI check on CPU_BIG (target < 10 mΩ to 20 MHz).
- [ ] Thermal: RK3576 needs a heatsink or thermal pad above about 3 W sustained. Leave space and holes
      around the SoC for a clip-on heatsink.
- [ ] Order 5 prototypes. Bring-up order: power rails (no SoC load) → UART log → maskrom → DDR training → eMMC flash.

## Bring-up plan (first boards)

1. **No-load power-up:** before fitting the SoC load (or with RESET held), power from a bench supply at 5 V with a 0.5 A
   current limit, and check that every rail on sheets 02/03 is at its nominal voltage ±3 %.
2. **Serial console on J501** (GND/TX/RX, 3.3 V, 1 500 000 8N1). The BROM prints DDR training results from
   the SPL. No log at all → check SYS_RESET_L (NPOR), the 24 MHz crystal, and PMIC I²C.
3. **Maskrom:** hold MASKROM, tap RESET, and connect USB-C to the PC. `rkdeveloptool ld` shows the device.
   Load the RK3576 loader and flash a Radxa ROCK 4D image as the first known-good OS.
4. Then follow the CLAUDE.md order: confirm hardware with a vendor image, then replace U-Boot → kernel → rootfs
   with your own builds.
