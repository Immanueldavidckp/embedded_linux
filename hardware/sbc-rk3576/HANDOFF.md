# HANDOFF: RK3576 SBC hardware project (read this first)

This file is for whoever (person or AI) picks the project up next. It says what exists, what state it
is in, how to rebuild it, and exactly what is left. Last updated **2026-10-07**, at commit `b0a8ded`
on branch `ccr-2ee6a8c6-02t1jx` (PR #1, draft, into `main`).

## 1. Status in one table

| Item | State |
|---|---|
| Schematic (14 sheets, 484 parts, 303 nets) | ✅ done, ERC 0 errors / 0 warnings |
| PCB placement (100 × 72 mm, **10 layers**, rev A2) | ✅ done, schematic↔PCB parity 0 issues |
| **Routing** | 🟡 **928 / 942 connections (98.5 %)**. **14 open**, listed in §7 |
| DRC | ✅ 0 errors apart from the 14 unconnected items (warnings only) |
| Length / skew tuning | 🟡 22 / 24 complete diff pairs in tolerance; LPDDR5 byte lanes still 8–11 mm apart |
| BOM / cost | ✅ ≈ $57 parts, ≈ $75 per built board at 1k units (≈ $89 for 8 GB / 64 GB) |
| Fab outputs | 🟡 drafts in `fab/gerbers-draft/` (Gerber X2 for all 10 copper layers, Excellon, CPL). **Not orderable** until §7 is done |
| Linux device tree | ✅ `software/rk3576-sbc.dts` compiles against mainline `rk3576.dtsi` |

## 2. What the user asked for

Immanuel David (firmware engineer learning embedded Linux; see the repo-root `CLAUDE.md`) asked for a
complete, manufacturable, low-cost SBC that can serve as his Linux PC:

- 8-core processor, LPDDR5 4–8 GB, eMMC, NVMe M.2 slot, 4K display output, UART, USB.
- Later additions he chose: Gigabit Ethernet, a USB hub, Wi-Fi/BT.
- Schematic, PCB, BOM, placement files, everything pushed to GitHub.
- "Complete all the routing" (repeatedly), with parallel agents allowed.
- When 8 layers turned out too few, he chose **10 layers** over re-placement or hand routing.

How he wants help: explain the *why*, concise, tie it to his telematics/ECU day job (see `CLAUDE.md`).

## 3. Where everything is

- Repo `Immanueldavidckp/embedded_linux`, branch **`ccr-2ee6a8c6-02t1jx`**, **PR #1** (draft). Nothing is
  merged into `main` yet. The user once looked at another repo, `Immanueldavidckp/Embedded_linux_`; the
  files are **not** there. He has not yet said whether to merge PR #1 or copy the files over.
- Project root: `hardware/sbc-rk3576/`

```
hardware/sbc-rk3576/
├── HANDOFF.md          ← this file
├── README.md           status table, requirements → implementation, how it was routed
├── LOG.md              35 numbered "what broke / root cause / fix / lesson" entries (read it!)
├── kicad/              KiCad 9 project: rk3576-sbc.kicad_pro / .kicad_sch (+14 sheets) / .kicad_pcb
│   └── sbc.pretty, sbc.kicad_sym   custom footprints + symbols (generated)
├── tools/              every generator / router / checker (Python + one C file)
├── data/               ball maps (RK3576 698, LPDDR5 315, eMMC 153, RK806), LCSC footprints
├── software/           rk3576-sbc.dts (board device tree)
├── fab/                BOM, JLCPCB BOM/CPL, cost, ERC/DRC reports, length + tuning reports, draft Gerbers
└── docs/               schematic PDF, assembly PDFs, renders, design_notes, layout_guide,
                        manufacturing, linux_pc_readiness
```

## 4. Environment setup (fresh Ubuntu 24.04 container)

```bash
# KiCad 9 (kicad-cli has ERC/DRC only from KiCad 8+). add-apt-repository was broken here, so by hand:
#   key for ppa:kicad/kicad-9.0-releases -> /etc/apt/trusted.gpg.d/kicad9.gpg
echo "deb https://ppa.launchpadcontent.net/kicad/kicad-9.0-releases/ubuntu noble main" \
  > /etc/apt/sources.list.d/kicad9.list
apt-get update && apt-get install -y kicad          # provides kicad-cli + the pcbnew Python module
# The system python3 here is 3.11 and pcbnew imports from it; apt's numpy is built for 3.12, so use pip:
python3 -m pip install --break-system-packages numpy scipy pillow
# The C A* core (tools/maze/astar.c) compiles itself on first use (gcc needed).
```

Checks: `kicad-cli version` → 9.0.x; `python3 -c "import pcbnew, numpy, scipy, PIL"`.
The machine had 4 cores and 15 GB RAM; a full-board raster is ~10 layers × 4040 × 2920 cells (~1.5 GB).

## 5. Design facts you need

- **SoC** RK3576 FCCSP698 (U401, 0.55/0.60/0.65 mm mixed pitch). **LPDDR5** x32 315-ball (U601).
  **eMMC** 153-ball 0.5 mm (U701). **PMIC** RK806S-5 (U201); rail map verified against mainline
  `rk3576-rock-4d.dts` (LOG #11). GbE PHY RTL8211F (U1301), hub FE1.1s, Wi-Fi BL-M8821CU1.
- **Stackup (rev A2, `tools/stackup.py`)**: L1 F sig · L2 In1 GND · L3 In2 sig · L4 In3 sig · L5 In4 PWR
  (core/DDR rails) · L6 In5 GND · L7 In6 sig · L8 In7 sig · L9 In8 PWR (5 V/3V3/1V8) · L10 B sig.
  Everything that cares about layers reads `stackup.py` (router, stitching, pours, gen_pcb, Gerber export).
- **Rules** (in `kicad/rk3576-sbc.kicad_pro`, written by `gen_pcb.py`): min clearance 0.09, min track 0.09,
  hole-to-hole 0.25, hole clearance 0.12, edge 0.3. Net classes: LPDDR5 0.09/0.09, HDMI 100 Ω, PCIe 85 Ω,
  USB 90 Ω, EMMC/SD, POWER (0.20 track). **The .kicad_pro must sit next to any board copy**, otherwise
  kicad-cli DRC silently uses defaults (0.2 mm) and reports hundreds of bogus errors (LOG #25).
- **Vias**: BGA fan-out vias are via-in-pad (filled + capped, POFV) and **locked**; all vias use
  "remove unconnected layer pads" (LOG #23, #30). Inside the 0.55 mm RK3576 ball field **no new via fits
  anywhere** (hole-to-hole), so a route there can only change layer at its own fan-out via (LOG #34).

## 6. How the files are produced

- `tools/design.py` is the single source of truth (parts, pins → nets, MPN, price).
- `tools/build.sh`: gen_lib → gen_schematic → gen_bom → ERC → DRC + parity → length report → draft
  Gerbers/drill/CPL → PDFs/renders. **It does not touch the routed PCB.**
- `REGEN_PCB=1 tools/build.sh` re-places the board from scratch and **throws away all routing**. Don't,
  unless you mean to re-route everything (≈ several hours, §8).
- Routing tools (all in `tools/`, each documented in its docstring):

| Tool | Does |
|---|---|
| `maze_route.py` + `maze/astar.c` | 25 µm grid, multi-layer A* in C. Takes the open connections from KiCad's DRC JSON, routes from all copper already connected to each end (lands on dangling fan-out vias), bridges pieces KiCad sees as separate. Options `--nets/--exclude/--pwr-ok/--max-expand` |
| `maze_ripup.py` | DRC-driven rounds around maze_route (each round in its own process): drops routed items in DRC errors, routes, optional rip-up (`--max-rip`, `--no-rip`), refills, stops on no progress |
| `maze_diag.py BOARD DRC.json NETREGEX` | flood-fills free space from both ends: "boxed in" vs "congested corridor" |
| `strip_routes.py IN OUT [--nets RE]` | strip all routing (re-stitch planes), or only some nets (to re-route them from their pads) |
| `fanout.py`, `fanout_region.py` | BGA via-in-pad; late fan-out of one BGA with `--relocate` (moves other-side parts off via sites) / `--only-missing` |
| `pour.py`, `pour_fix.py` | power pours; `pour_fix` re-plans each rail as one connected region (run after signal changes; refill ~3–15 min) |
| `stitch.py` | stub + via from every GND / rail pad into its plane |
| `cleanup.py` | removes dangling stubs/vias and hole-to-hole offenders, never raises the unconnected count |
| `tune_length.py` | accordion meanders / skew bumps where free space allows; reverts anything DRC rejects |
| `length_report.py` | `fab/length_report.md` (groups out of tolerance) |
| `via_nfp.py`, `to_10layer.py`, `stackup.py` | unused-pad removal; 8 → 10 layer move; the stackup |
| `route_all.sh` | the whole routing pipeline, in order |
| `route.py`, `import_ses.py`, `islands_export.py`, `ripup_power_layers.py`, `apply_patch.py` | earlier Freerouting / parallel-merge flow (kept for history) |

## 7. What is left (exact list, from `fab/drc.rpt`)

| # | Net | Between | Why it failed | Suggested fix |
|---|---|---|---|---|
| 1–3 | RGMII_RXD2, RXD3, TXCTL | U401 B12 / 1A10 / A11 → U1301 pins 23 / 22 / 19 (≈ 45 mm) | corridor SoC → PHY taken by the other RGMII lines | KiCad push-and-shove (X key, Shove mode), same layer as RXD0/RXD1; keep the RGMII group within ±1 mm |
| 4 | SD_D1 | J701 pin 8 (bottom) → U401 B25 | long run through the SoC area | follow SD_D0/D2 on L7/L8 |
| 5 | PCIE0_TXN | U401 P28 → C802 pin 1 | SoC ball boxed in on F.Cu | route as a diff pair with PCIE0_TXP (85 Ω), then `tune_length.py` |
| 6–9 | PMIC_PWRCTRL3, PWRON_L, PMIC_FB6, VDDA_DDR_PLL_S0 | U201 pins 16 / 4 / 31 / 12 → SoC / caps | PMIC (QFN) pins boxed by its own switch-node copper; no via site nearby | via-in-pad (0.25/0.15, POFV) on those U201 pins or a dog-bone, then L3/L4 (`--pwr-ok` also lets them use L5/L9) |
| 10 | LP5_DMI0_B | 2.2 mm gap near (33.9, 40.1) | stranded piece | join on L7 |
| 11 | VDD_NPU_S0 | 0.7 mm gap at (60, 30.5) | stranded piece | via from the B.Cu stub into the L5 pour |
| 12 | VCC_2V0_PLDO_S3 | C303 → C249 (≈ 26 mm) | power, crosses other pours | 0.25 mm track on L5/L9, then re-run `pour_fix.py` |
| 13–14 | VCCA_1V8_S0, VCC_1V8_S3 | zone filled as two islands (L5 / L9) | neck between the islands too thin | widen the zone outline at the neck or add a 0.2 mm track; refill |

Also open (not connectivity): LPDDR5 byte-lane length matching (A0/A1/B0/B1/CA spreads 8–11 mm,
`fab/tuning_report.md`); release checklist in `docs/manufacturing.md` (VCCIO bank voltages, M.2 socket
footprint check, impedance coupons, SI/PI/thermal, prototype bring-up order).

## 8. How to continue (step by step)

1. Read `LOG.md` (35 entries) and `docs/layout_guide.md`. Run `kicad-cli pcb drc --format json
   --severity-all -o /tmp/d.json kicad/rk3576-sbc.kicad_pcb` and confirm 14 `unconnected_items`, 0 errors.
2. **Work on copies** (copy `.kicad_pcb` **and** `.kicad_pro` into a scratch dir). Only copy a board back
   into `kicad/` when its DRC shows **0 clearance/hole/short errors** and fewer open connections.
3. Automated attempt (cheap to try): e.g.
   `python3 tools/maze_ripup.py W/b.kicad_pcb W/b.kicad_pcb --rounds 6 --no-rip --mg 1.25 --max-expand 30000000 --pwr-ok '^(PMIC_|PWRON_L|VDD|VCC|...)'`.
   Rip-up (`--max-rip`) beyond ~8 items cascades on this board (LOG #27, #31, #35); prefer: strip the
   stranded nets (`strip_routes.py --nets`) and re-route them with `--first`, then plain `--no-rip` rounds.
4. Interactive (what a layout engineer does now): open `kicad/rk3576-sbc.kicad_pro` in KiCad 9 and route
   §7 with push-and-shove. That is the fastest way to 0.
5. Then: `tools/cleanup.py` → `tools/tune_length.py IN OUT --report fab/tuning_report.md` → copy back →
   `tools/build.sh`. Done when `fab/drc.rpt` says **0 unconnected** and 0 errors.
6. Commit milestones with clear messages; push to the branch; keep PR #1's description current.

## 9. Pitfalls that cost hours (details in LOG.md)

- KiCad 9 Python: **one board per process** (use subprocesses); after `board.Remove(item)` keep the item
  referenced (`GRAVE` list) or SWIG frees it and later calls return bare `SwigPyObject`s (LOG #24);
  zone fill must run on a board freshly loaded from disk (LOG #7); `BOARD.Remove(zone)` is unsafe, strip
  zones as text (`zones_strip.py`).
- kicad-cli DRC lists at most **499** unconnected items and **199** items per violation type: these are
  caps, not counts (LOG #12). The true count: `board.GetConnectivity().GetUnconnectedCount(False)`.
- KiCad joins tracks only at end points: overlapping same-net copper can still be "unconnected" (LOG #34).
- A via with removed unused pads grows a pad when something later connects on that layer (a route or a
  re-planned pour); re-check DRC after `pour_fix.py` (LOG #23, #32).
- Parallel routers on one board + merge lose more than they gain (LOG #26); parallelise by problem instead
  (this project used agents for clean-up, pours and length tuning while one router ran).
- Freerouting (`route.py`) can hang after its job timeout; it was abandoned for the maze router (LOG #16-#21).

## 10. Numbers so far (for context)

1,789 open after placement → 482 (Freerouting + fan-out/stitching/pours) → strip to 942 → maze router
168 → eMMC fan-out + `pour_fix` 132 → rip-up/power-layer nets 72 (8 layers, plateau) → **10 layers** 21 →
bridges + stranded-net re-route **14**. 51 commits on the branch.
