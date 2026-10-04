# LOG: what broke, how it was fixed

Interview-story bank for the RK3576 SBC hardware generation.

| # | What broke | Root cause | Fix / lesson |
|---|---|---|---|
| 1 | Datasheet pin table parsed 693/698 balls; five came out "duplicated" as `1AD2` | `pdftotext` wrapped long ball IDs: `1AD2` + `0` on the next line | Treat a lone digit on a continuation line as part of the ball ID. **Lesson:** verify a count against a known total (698) before trusting extracted data. |
| 2 | The reverse-polarity P-FET on the USB-C input had source and drain swapped | Wrote S=VBUS, D=SYS. The body diode then points the wrong way | Removed the FET instead: USB-C can't present reversed polarity, and SOT-23 would burn ~0.5 W at 3 A. **Lesson:** every protection part should answer "what failure does this prevent?" |
| 3 | KiCad 7 `kicad-cli` has no `sch erc` / `pcb drc` | ERC/DRC CLI arrived in KiCad 8 | Installed KiCad 9 from the official PPA. `add-apt-repository` was broken (python `apt_pkg`), so the key and sources list were added by hand. |
| 4 | 472 ERC "errors" on the first run | No global/project library tables (no `.kicad_pro` yet) | Added a project file plus `sym-lib-table`/`fp-lib-table` with `${KIPRJMOD}`. 1 real issue remained: RK806 `CS` typed bidirectional on a GND/PWR_FLAG net, changed to input. |
| 5 | `Connector_HDMI` library not found | KiCad 9 renamed it `Connector_Video` | Added a footprint-existence check over the whole design. |
| 6 | Duplicate references C501–C505 | Sheet 04 has >99 capacitors, so `sn*100+k` ran into sheet 05's range | Overflow to `C4100+`, plus a hard uniqueness assert in `build()`. |
| 7 | `pcbnew` segfault in `ZONE_FILLER.Fill()` | Filling zones on a board built in memory (not loaded from disk) crashes in 9.0 | Save, `LoadBoard()`, fill, save again. |
| 8 | DRC: "board outline not closed", holes at 0 mm from the edge | Corner arcs were drawn backwards (start/angle convention) | Use `SetArcGeometry(start, mid, end)`: explicit and unambiguous. |
| 9 | 199 parity warnings: pads missing `unconnected-(…)` nets | KiCad 9 gives every NC pin its own net; the PCB set no net | The PCB now takes nets from the schematic's exported netlist (like Update PCB from Schematic) and cross-checks them against `design.py`. |
| 10 | 6.3 V caps on 5 V rails | Default voltage in the cap helper | The helper forces ≥10 V on any 5 V net (MLCC DC-bias derating). |
| 11 | **PMIC rail map wrong in rev A0**: 8 of 10 bucks and 4 of 5 NLDOs on the wrong rail | Mapping was inferred from the reference schematic's text order; that text order is not the pin order | Wrote the board device tree from mainline `rk3576-rock-4d.dts` (same RK806S-5) and compared regulator by regulator. **Lesson:** cross-check hardware against the software description (DTS) of a shipping board. The two have to agree, and the DTS is machine-readable. |
| 12 | DRC said "499 unconnected" on two quite different boards | KiCad's report stops listing unconnected items at 499 | Read the true count from `board.GetConnectivity().GetUnconnectedCount()`: 1,789. **Lesson:** a suspiciously round or unchanged number is a cap, not a result. |
| 13 | LCSC FE1.1s symbol marks pins 12/13/28 as NC | Library symbol error. The datasheet has VD18_O / VD33 / VD18 there | Built the symbol from the Terminus datasheet pin table. **Lesson:** a downloaded footprint can be trusted for geometry; a downloaded symbol must be checked against the datasheet. |
| 14 | Passives placed on top of hub/Wi-Fi pins | EasyEDA courtyards outline only the body | Recompute courtyards from pad extents + 0.25 mm when importing LCSC footprints. |
