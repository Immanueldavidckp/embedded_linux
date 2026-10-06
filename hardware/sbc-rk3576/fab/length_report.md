# Routed length report

Unrouted connections: **14**. Lengths are copper only (via barrels excluded), measured from the KiCad board.

## LPDDR5 byte lanes (target: DQ/DMI within ±0.5 mm of the lane mean)

| Lane | nets routed | min | max | spread | status |
|---|---:|---:|---:|---:|---|
| A0 | 9/9 | 18.68 | 38.97 | 20.29 | TUNE |
| A1 | 9/9 | 12.63 | 24.34 | 11.70 | TUNE |
| CA_A | 9/9 | 12.35 | 25.93 | 13.58 | TUNE |
| B0 | 9/9 | 11.90 | 32.12 | 20.22 | TUNE |
| B1 | 9/9 | 22.94 | 39.31 | 16.37 | TUNE |
| CA_B | 9/9 | 11.09 | 25.95 | 14.85 | TUNE |

## Differential pairs (intra-pair skew)

| Pair | P mm | N mm | skew | limit | status |
|---|---:|---:|---:|---:|---|
| LP5_CLKP_A / LP5_CLKN_A | 14.73 | 11.49 | 3.24 | 0.1 | TUNE |
| LP5_CLKP_B / LP5_CLKN_B | 19.81 | 16.27 | 3.54 | 0.1 | TUNE |
| LP5_WCK0P_A / LP5_WCK0N_A | 46.36 | 36.74 | 9.62 | 0.1 | TUNE |
| LP5_WCK0P_B / LP5_WCK0N_B | 18.61 | 19.64 | 1.02 | 0.1 | TUNE |
| LP5_WCK1P_A / LP5_WCK1N_A | 23.33 | 24.15 | 0.82 | 0.1 | TUNE |
| LP5_WCK1P_B / LP5_WCK1N_B | 28.05 | 38.95 | 10.90 | 0.1 | TUNE |
| LP5_RDQS0P_A / LP5_RDQS0N_A | 46.88 | 30.30 | 16.58 | 0.1 | TUNE |
| LP5_RDQS0P_B / LP5_RDQS0N_B | 15.67 | 16.50 | 0.83 | 0.1 | TUNE |
| LP5_RDQS1P_A / LP5_RDQS1N_A | 22.42 | 21.88 | 0.53 | 0.1 | TUNE |
| LP5_RDQS1P_B / LP5_RDQS1N_B | 36.22 | 32.96 | 3.26 | 0.1 | TUNE |
| HDMI_TX_D0P / HDMI_TX_D0N | 17.82 | 14.77 | 3.05 | 0.15 | TUNE |
| HDMI_TX_D1P / HDMI_TX_D1N | 14.62 | 13.09 | 1.53 | 0.15 | TUNE |
| HDMI_TX_D2P / HDMI_TX_D2N | 16.70 | 16.39 | 0.31 | 0.15 | TUNE |
| HDMI_TX_D3P / HDMI_TX_D3N | 16.41 | 18.27 | 1.87 | 0.15 | TUNE |
| PCIE0_TX | 20.82 | 0.00 | - | 0.15 | unrouted |
| PCIE0_RXP / PCIE0_RXN | 38.71 | 29.69 | 9.03 | 0.15 | TUNE |
| PCIE0_REFCLKP / PCIE0_REFCLKN | 35.51 | 36.08 | 0.57 | 0.15 | TUNE |
| USB3_TXP / USB3_TXN | 51.06 | 38.62 | 12.44 | 0.15 | TUNE |
| USB3_RXP / USB3_RXN | 41.48 | 41.51 | 0.03 | 0.15 | OK |
| USBC_DP / USBC_DM | 37.86 | 41.16 | 3.30 | 0.15 | TUNE |
| HUB_UP_DP / HUB_UP_DM | 31.69 | 37.42 | 5.73 | 0.15 | TUNE |
| ETH_MDI0_P / ETH_MDI0_N | 15.30 | 12.00 | 3.30 | 0.15 | TUNE |
| ETH_MDI1_P / ETH_MDI1_N | 16.15 | 22.50 | 6.35 | 0.15 | TUNE |
| ETH_MDI2_P / ETH_MDI2_N | 11.74 | 15.15 | 3.41 | 0.15 | TUNE |
| ETH_MDI3_P / ETH_MDI3_N | 18.76 | 14.75 | 4.02 | 0.15 | TUNE |

**30 groups need tuning.** Use KiCad PCB editor → Route → Tune length / skew on each TUNE row, then re-run `tools/length_report.py`.
