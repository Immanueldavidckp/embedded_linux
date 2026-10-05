# RK3576 SBC: low-cost 8-core Linux board (LPDDR5, eMMC, NVMe, 4K HDMI, GbE, Wi-Fi)

A KiCad 9 single-board computer. The circuit lives in one Python file (`tools/design.py`), and the schematic,
PCB, BOM and placement files are generated from it, so they cannot drift apart.

![top](docs/img/pcb_top.png)

| Requirement | Implementation |
|---|---|
| 8-core processor | **Rockchip RK3576**: 4× Cortex-A72 @ 2.2 GHz + 4× A53, Mali-G52 MC3, 6 TOPS NPU |
| LPDDR5, 4–8 GB | One LPDDR5 x32 315-ball package. 4 GB `MT62F1G32D2DS` or 8 GB `MT62F2G32D4DS`: **same footprint, BOM option** |
| eMMC | eMMC 5.1 HS400, 32 GB (64 GB option), boot device |
| NVMe M.2 | M.2 M-key 2230/2242, PCIe 2.1 ×1 |
| 4K display | HDMI 2.1 TX type-A: 4K@60 TMDS, 4K@120 FRL |
| UART | 3-pin debug UART0 header, **3.3 V**, 1 500 000 8N1 |
| USB | USB 3.0-A host + **2× USB 2.0-A** (FE1.1s hub) + USB-C (5 V in, OTG for maskrom/ADB) |
| Network (rev A1) | **Gigabit Ethernet** (RTL8211F + MagJack) and **Wi-Fi 5 + BT 4.2** (BL-M8821CU1, u.FL antenna) |
| Low price | **≈ $57 parts, ≈ $72 per built board** at 1k units (4 GB/32 GB); ≈ $86 for 8 GB/64 GB. See [fab/cost_summary.md](fab/cost_summary.md) |

Also on the board: microSD (recovery boot), MASKROM/POWER/RESET keys, LEDs. It is **100 × 72 mm** with an
8-layer 1.6 mm stackup (via-in-pad under the BGAs).

## Status

| Stage | State | Evidence |
|---|---|---|
| Architecture, parts, power tree | ✅ | [docs/design_notes.md](docs/design_notes.md) |
| Schematic: 14 sheets, 484 parts, 303 nets | ✅ ERC **0 errors / 0 warnings** | [docs/schematic.pdf](docs/schematic.pdf), [fab/erc.rpt](fab/erc.rpt) |
| RK3576 land pattern | ✅ real (LCSC C42388007): all 698 pad names = datasheet ball IDs | `kicad/sbc.pretty` |
| PMIC rail map | ✅ verified against mainline Linux `rk3576-rock-4d.dts` (same RK806S-5) | LOG.md #11 |
| Device tree | ✅ `software/rk3576-sbc.dts` compiles against mainline `rk3576.dtsi`; 7/7 GPIOs match the schematic | `tools/check_dts.sh` |
| Placement | ✅ all 484 footprints, 262 top / 222 bottom | renders in `docs/img/` |
| BGA fan-out | ✅ 818 via-in-pad escapes (RK3576 + LPDDR5) | `tools/fanout.py` |
| Planes / pours | ✅ GND on L2/L5 + 284 stitch vias; 36 power pours on L4/L7 + stitch vias | `tools/stitch.py`, `tools/pour.py` |
| **Routing** | 🟡 **76 % done**: 1,789 → **433** connections left (≈ 80 signal, ≈ 350 power-pour joins) | [fab/drc.rpt](fab/drc.rpt) |
| DRC | ✅ **0 errors** apart from the unrouted connections (219 warnings: pour islands, stubs) | [fab/drc.rpt](fab/drc.rpt) |
| Schematic ↔ PCB parity | ✅ 0 issues | [fab/drc.rpt](fab/drc.rpt) |
| Length / skew tuning | ❌ not done: 31 groups flagged | [fab/length_report.md](fab/length_report.md) |
| BOM, JLCPCB BOM, CPL | ✅ | `fab/` |
| Linux-PC readiness | ✅ on paper (Pi 4–5 class desktop) | [docs/linux_pc_readiness.md](docs/linux_pc_readiness.md) |

> **Do not order from `fab/gerbers-draft/` yet.** The board needs: the remaining 433 connections, a
> power-plane clean-up (L4 is shared by signals and power pours, which islands the pours), and length
> tuning of LPDDR5/HDMI/PCIe/USB3. That last stage is interactive layout work in KiCad
> (Route → Tune length). See [docs/layout_guide.md](docs/layout_guide.md).

### What stopped full auto-routing (and what to do next)

1. **Power on L4 got sliced by signals.** The early router passes used L4 for signals before the power pours
   existed, so the pours are fragmented (83 isolated islands). Fix: reserve L4 (and L7) for power only, rip up
   the L4 signal traces and re-route them on L1/L3/L6/L8, then re-pour.
2. **LPDDR5 needs constrained routing**: byte lanes on one layer, matched to ±0.5 mm. No open-source
   autorouter does this. Route DDR by hand first, then let Freerouting fill in low-speed nets.
3. The tooling to continue is in place: `tools/route.py` runs Freerouting in saved chunks and
   `tools/import_ses.py` imports a session. `tools/length_report.py` regenerates the tuning list.

## Repository layout

```
hardware/sbc-rk3576/
├── tools/
│   ├── design.py           # THE CIRCUIT: every part, pin→net, MPN, price
│   ├── gen_lib.py          # symbols + footprints (custom + verified LCSC land patterns)
│   ├── gen_schematic.py    # 14-sheet hierarchical KiCad schematic
│   ├── gen_pcb.py          # stackup, outline, net classes, placement, planes
│   ├── fanout.py           # BGA via-in-pad escape
│   ├── stitch.py, pour.py  # GND stitching, power pours + stitching
│   ├── route.py, import_ses.py   # Freerouting in chunks (Specctra DSN/SES)
│   ├── length_report.py    # DDR/HS length + skew report
│   ├── gen_bom.py          # BOM, JLCPCB BOM, cost summary
│   ├── check_dts.sh        # compile the board device tree against mainline Linux
│   └── build.sh            # regenerate + ERC + DRC/parity + exports (REGEN_PCB=1 to re-place)
├── data/                   # ball maps (RK3576 698, LPDDR5 315, eMMC 153, RK806) + LCSC footprints
├── kicad/                  # KiCad 9 project (open rk3576-sbc.kicad_pro)
├── software/rk3576-sbc.dts # Linux device tree for this board
├── fab/                    # BOM, CPL, cost, ERC/DRC reports, length report, draft Gerbers
└── docs/                   # schematic PDF, assembly drawings, renders, design notes, guides
```

`tools/build.sh` regenerates the schematic and outputs **without** touching the routed PCB.
`REGEN_PCB=1 tools/build.sh` re-places the board from scratch, which throws away all routing.

## Sources

- RK3576 datasheet (pin list, package): [Rockchip RK3576 Datasheet V1.1](https://files.luckfox.com/wiki/Omni3576/PDF/Rockchip_RK3576_Datasheet_V1.1-20240430.pdf)
- Reference design: [Radxa ROCK 4D schematic V1.11](https://dl.radxa.com/rock4/4d/docs/hw/Radxa_ROCK_4D_SCH_V1.11.pdf) and mainline `arch/arm64/boot/dts/rockchip/rk3576-rock-4d.dts`
- eMMC 153b ballout: [Alliance Memory ASFC8G31M-51BIN](https://www.alliancememory.com/wp-content/uploads/AllianceMemory_8GB_ASFC8G31M-51BIN_eMMCdatasheet_November2022_v1.3.pdf)
- LPDDR5 315b package: [Micron 315b LPDDR5](https://www.mouser.com/datasheet/2/671/Micron_05092023_315b_y4bm_ddp_qdp_8dp_auto_lpddr5_-3175609.pdf)
- FE1.1s: [Terminus datasheet Rev 1.0](https://cdn-shop.adafruit.com/product-files/2991/FE1.1s+Data+Sheet+(Rev.+1.0).pdf)
- Land patterns: LCSC/EasyEDA C42388007 (RK3576), C187932 (RTL8211F), C9359 (FE1.1s), C50933 (HR911130C), C9900166844 (Wi-Fi module family)
