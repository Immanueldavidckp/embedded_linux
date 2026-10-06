# Routed length report

Unrouted connections: **72**. Lengths are copper only (via barrels excluded), measured from the KiCad board.

## LPDDR5 byte lanes (target: DQ/DMI within ±0.5 mm of the lane mean)

| Lane | nets routed | min | max | spread | status |
|---|---:|---:|---:|---:|---|
| A0 | 5/9 | 24.36 | 38.97 | 14.61 | TUNE |
| A1 | 9/9 | 12.63 | 24.34 | 11.70 | TUNE |
| CA_A | 9/9 | 12.35 | 25.93 | 13.58 | TUNE |
| B0 | 8/9 | 11.90 | 45.90 | 34.00 | TUNE |
| B1 | 4/9 | 26.41 | 39.31 | 12.91 | TUNE |
| CA_B | 4/9 | 11.09 | 14.47 | 3.38 | TUNE |

## Differential pairs (intra-pair skew)

| Pair | P mm | N mm | skew | limit | status |
|---|---:|---:|---:|---:|---|
| LP5_CLKP_A / LP5_CLKN_A | 14.73 | 11.49 | 3.24 | 0.1 | TUNE |
| LP5_CLKP_B / LP5_CLKN_B | 19.81 | 16.27 | 3.54 | 0.1 | TUNE |
| LP5_WCK0P_A / LP5_WCK0N_A | 46.36 | 36.74 | 9.62 | 0.1 | TUNE |
| LP5_WCK0P_B / LP5_WCK0N_B | 18.61 | 19.64 | 1.02 | 0.1 | TUNE |
| LP5_WCK1P_A / LP5_WCK1N_A | 23.33 | 24.15 | 0.82 | 0.1 | TUNE |
| LP5_WCK1P_B | 0.00 | 38.92 | - | 0.1 | unrouted |
| LP5_RDQS0P_A / LP5_RDQS0N_A | 46.88 | 30.30 | 16.58 | 0.1 | TUNE |
| LP5_RDQS0P_B / LP5_RDQS0N_B | 15.67 | 16.50 | 0.83 | 0.1 | TUNE |
| LP5_RDQS1P_A / LP5_RDQS1N_A | 22.42 | 21.88 | 0.53 | 0.1 | TUNE |
| LP5_RDQS1P_B | 0.00 | 0.00 | - | 0.1 | unrouted |
| HDMI_TX_D0 | 0.00 | 14.77 | - | 0.15 | unrouted |
| HDMI_TX_D1P / HDMI_TX_D1N | 14.62 | 13.09 | 1.53 | 0.15 | TUNE |
| HDMI_TX_D2P / HDMI_TX_D2N | 16.70 | 16.39 | 0.31 | 0.15 | TUNE |
| HDMI_TX_D3P / HDMI_TX_D3N | 16.41 | 18.27 | 1.87 | 0.15 | TUNE |
| PCIE0_TXP / PCIE0_TXN | 20.82 | 33.42 | 12.60 | 0.15 | TUNE |
| PCIE0_RXP / PCIE0_RXN | 35.08 | 29.69 | 5.39 | 0.15 | TUNE |
| PCIE0_REFCLKP / PCIE0_REFCLKN | 32.80 | 30.76 | 2.04 | 0.15 | TUNE |
| USB3_TXP / USB3_TXN | 51.06 | 38.62 | 12.44 | 0.15 | TUNE |
| USB3_RXP / USB3_RXN | 41.45 | 11.77 | 29.68 | 0.15 | TUNE |
| USBC_DP / USBC_DM | 37.86 | 41.16 | 3.30 | 0.15 | TUNE |
| HUB_UP_D | 0.00 | 37.39 | - | 0.15 | unrouted |
| ETH_MDI0_P / ETH_MDI0_N | 15.30 | 12.00 | 3.30 | 0.15 | TUNE |
| ETH_MDI1_P / ETH_MDI1_N | 16.15 | 21.96 | 5.81 | 0.15 | TUNE |
| ETH_MDI2_P / ETH_MDI2_N | 11.74 | 15.15 | 3.41 | 0.15 | TUNE |
| ETH_MDI3_P / ETH_MDI3_N | 18.76 | 14.75 | 4.02 | 0.15 | TUNE |

**31 groups need tuning.** Use KiCad PCB editor → Route → Tune length / skew on each TUNE row, then re-run `tools/length_report.py`.
