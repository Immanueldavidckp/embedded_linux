# Routed length report

Unrouted connections: **433**. Lengths are copper only (via barrels excluded), measured from the KiCad board.

## LPDDR5 byte lanes (target: DQ/DMI within ±0.5 mm of the lane mean)

| Lane | nets routed | min | max | spread | status |
|---|---:|---:|---:|---:|---|
| A0 | 6/9 | 17.85 | 32.38 | 14.53 | TUNE |
| A1 | 6/9 | 13.26 | 34.78 | 21.52 | TUNE |
| CA_A | 7/9 | 5.93 | 25.87 | 19.94 | TUNE |
| B0 | 9/9 | 11.94 | 44.04 | 32.10 | TUNE |
| B1 | 9/9 | 19.42 | 31.87 | 12.45 | TUNE |
| CA_B | 6/9 | 8.52 | 28.93 | 20.41 | TUNE |

## Differential pairs (intra-pair skew)

| Pair | P mm | N mm | skew | limit | status |
|---|---:|---:|---:|---:|---|
| LP5_CLKP_A / LP5_CLKN_A | 21.35 | 15.66 | 5.69 | 0.1 | TUNE |
| LP5_CLKP_B | 15.97 | 0.00 | - | 0.1 | unrouted |
| LP5_WCK0P_A | 30.72 | 0.00 | - | 0.1 | unrouted |
| LP5_WCK0P_B / LP5_WCK0N_B | 19.34 | 23.07 | 3.74 | 0.1 | TUNE |
| LP5_WCK1P_A / LP5_WCK1N_A | 8.69 | 18.07 | 9.38 | 0.1 | TUNE |
| LP5_WCK1P_B / LP5_WCK1N_B | 31.46 | 30.45 | 1.01 | 0.1 | TUNE |
| LP5_RDQS0P_A / LP5_RDQS0N_A | 20.72 | 26.39 | 5.67 | 0.1 | TUNE |
| LP5_RDQS0P_B / LP5_RDQS0N_B | 15.12 | 14.86 | 0.26 | 0.1 | TUNE |
| LP5_RDQS1P_A / LP5_RDQS1N_A | 26.18 | 44.18 | 18.00 | 0.1 | TUNE |
| LP5_RDQS1P_B / LP5_RDQS1N_B | 31.44 | 35.76 | 4.32 | 0.1 | TUNE |
| HDMI_TX_D0P / HDMI_TX_D0N | 19.39 | 15.36 | 4.03 | 0.15 | TUNE |
| HDMI_TX_D1P / HDMI_TX_D1N | 15.40 | 13.57 | 1.83 | 0.15 | TUNE |
| HDMI_TX_D2P / HDMI_TX_D2N | 16.96 | 18.11 | 1.15 | 0.15 | TUNE |
| HDMI_TX_D3P / HDMI_TX_D3N | 14.77 | 18.87 | 4.10 | 0.15 | TUNE |
| PCIE0_TX | 24.09 | 0.00 | - | 0.15 | unrouted |
| PCIE0_RX | 0.00 | 29.02 | - | 0.15 | unrouted |
| PCIE0_REFCLK | 0.00 | 0.00 | - | 0.15 | unrouted |
| USB3_TXP / USB3_TXN | 1.02 | 40.35 | 39.33 | 0.15 | TUNE |
| USB3_RXP / USB3_RXN | 45.97 | 51.48 | 5.51 | 0.15 | TUNE |
| USBC_DP / USBC_DM | 51.62 | 48.95 | 2.67 | 0.15 | TUNE |
| HUB_UP_DP / HUB_UP_DM | 33.38 | 32.45 | 0.93 | 0.15 | TUNE |
| ETH_MDI0_P / ETH_MDI0_N | 16.75 | 14.55 | 2.19 | 0.15 | TUNE |
| ETH_MDI1_P / ETH_MDI1_N | 19.66 | 16.46 | 3.20 | 0.15 | TUNE |
| ETH_MDI2_P / ETH_MDI2_N | 16.64 | 18.30 | 1.66 | 0.15 | TUNE |
| ETH_MDI3_ | 0.00 | 14.80 | - | 0.15 | unrouted |

**31 groups need tuning.** Use KiCad PCB editor → Route → Tune length / skew on each TUNE row, then re-run `tools/length_report.py`.
