# Cost summary (budgetary, USD @ 1k units, Oct 2026)

397 placed parts, 10 DNP footprints, 70 BOM lines.

| Category | USD |
|---|---:|
| SoC | 22.00 |
| Memory (LPDDR5) | 14.50 |
| Storage (eMMC) | 5.80 |
| PMIC + regulators | 4.03 |
| Connectors | 2.02 |
| Other active / protection / mech | 1.69 |
| Passives (R/C/L/FB) | 1.10 |
| **Parts total (4GB LPDDR5 / 32GB eMMC)** | **51.14** |

| Build cost per board | 4GB / 32GB | 8GB / 64GB |
|---|---:|---:|
| Parts | 51.14 | 65.34 |
| PCB (8L, ENIG, POFV, impedance) | 6.50 | 6.50 |
| Assembly (2-sided, BGA X-ray) | 7.50 | 7.50 |
| Test / flashing | 1.00 | 1.00 |
| **Total** | **66.14** | **80.34** |

Variant parts (same footprints): U601 -> LPDDR5 8GB MT62F2G32D4DS-026 WT:B; U701 -> eMMC 64GB FEMDNN064G-A3A55

Cost drivers: SoC (~40%) and LPDDR5 (~25-40%). The 8-layer PCB with via-in-pad is the next biggest line; a 6-layer stackup is possible for LPDDR5 x32 only with 1-step HDI (laser microvias), which costs about the same - 8L through-via was chosen for wider fab choice.

Prototype quantities (5 boards) cost far more per board: expect roughly USD 150-250 each including PCB/stencil/BGA assembly setup fees.
