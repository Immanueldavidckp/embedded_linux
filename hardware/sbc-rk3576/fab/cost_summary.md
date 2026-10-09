# Cost summary (budgetary, USD @ 1k units, Oct 2026)

465 placed parts, 12 DNP footprints, 86 BOM lines.

| Category | USD |
|---|---:|
| SoC | 22.00 |
| Memory (LPDDR5) | 14.50 |
| Other active / protection / mech | 5.96 |
| Storage (eMMC) | 5.80 |
| PMIC + regulators | 4.03 |
| Connectors | 3.37 |
| Passives (R/C/L/FB) | 1.29 |
| **Parts total (4GB LPDDR5 / 32GB eMMC)** | **56.95** |

| Build cost per board | 4GB / 32GB | 8GB / 64GB |
|---|---:|---:|
| Parts | 56.95 | 71.15 |
| PCB (10L, ENIG, POFV, impedance) | 9.50 | 9.50 |
| Assembly (2-sided, BGA X-ray) | 7.50 | 7.50 |
| Test / flashing | 1.00 | 1.00 |
| **Total** | **74.95** | **89.15** |

Variant parts (same footprints): U601 -> LPDDR5 8GB MT62F2G32D4DS-026 WT:B; U701 -> eMMC 64GB FEMDNN064G-A3A55

Cost drivers: SoC (~40%) and LPDDR5 (~25-40%). The 10-layer PCB with via-in-pad is the next biggest line (rev A1 was 8 layers, ~USD 3 cheaper, but could not be fully routed: LOG.md #31-#33). 1-step HDI (laser microvias) on 8 layers is the alternative at similar cost.

Prototype quantities (5 boards) cost far more per board: expect roughly USD 150-250 each including PCB/stencil/BGA assembly setup fees.
