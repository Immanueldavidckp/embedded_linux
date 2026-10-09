# Routed length report

Unrouted connections: **14**. Lengths are copper only (via barrels excluded), measured from the KiCad board.

## LPDDR5 byte lanes (target: DQ/DMI within ±0.5 mm of the lane mean)

| Lane | nets routed | min | max | spread | status |
|---|---:|---:|---:|---:|---|
| A0 | 9/9 | 27.69 | 38.97 | 11.28 | TUNE |
| A1 | 9/9 | 16.02 | 24.34 | 8.32 | TUNE |
| CA_A | 9/9 | 14.39 | 25.93 | 11.54 | TUNE |
| B0 | 9/9 | 11.90 | 29.92 | 18.02 | TUNE |
| B1 | 9/9 | 31.46 | 39.31 | 7.85 | TUNE |
| CA_B | 9/9 | 14.80 | 25.95 | 11.15 | TUNE |

## Differential pairs (intra-pair skew)

| Pair | P mm | N mm | skew | limit | status |
|---|---:|---:|---:|---:|---|
| LP5_CLKP_A / LP5_CLKN_A | 14.73 | 14.68 | 0.05 | 0.1 | OK |
| LP5_CLKP_B / LP5_CLKN_B | 19.81 | 19.76 | 0.05 | 0.1 | OK |
| LP5_WCK0P_A / LP5_WCK0N_A | 46.36 | 46.31 | 0.05 | 0.1 | OK |
| LP5_WCK0P_B / LP5_WCK0N_B | 19.59 | 19.64 | 0.05 | 0.1 | OK |
| LP5_WCK1P_A / LP5_WCK1N_A | 24.10 | 24.15 | 0.05 | 0.1 | OK |
| LP5_WCK1P_B / LP5_WCK1N_B | 34.80 | 38.95 | 4.15 | 0.1 | TUNE |
| LP5_RDQS0P_A / LP5_RDQS0N_A | 46.88 | 44.69 | 2.19 | 0.1 | TUNE |
| LP5_RDQS0P_B / LP5_RDQS0N_B | 16.45 | 16.50 | 0.05 | 0.1 | OK |
| LP5_RDQS1P_A / LP5_RDQS1N_A | 22.42 | 22.37 | 0.05 | 0.1 | OK |
| LP5_RDQS1P_B / LP5_RDQS1N_B | 36.22 | 36.17 | 0.05 | 0.1 | OK |
| HDMI_TX_D0P / HDMI_TX_D0N | 17.82 | 17.74 | 0.08 | 0.15 | OK |
| HDMI_TX_D1P / HDMI_TX_D1N | 14.62 | 14.55 | 0.07 | 0.15 | OK |
| HDMI_TX_D2P / HDMI_TX_D2N | 16.70 | 16.62 | 0.08 | 0.15 | OK |
| HDMI_TX_D3P / HDMI_TX_D3N | 17.60 | 17.67 | 0.08 | 0.15 | OK |
| PCIE0_TX | 20.82 | 0.00 | - | 0.15 | unrouted |
| PCIE0_RXP / PCIE0_RXN | 34.20 | 34.13 | 0.07 | 0.15 | OK |
| PCIE0_REFCLKP / PCIE0_REFCLKN | 35.51 | 35.44 | 0.07 | 0.15 | OK |
| USB3_TXP / USB3_TXN | 51.06 | 50.99 | 0.07 | 0.15 | OK |
| USB3_RXP / USB3_RXN | 41.48 | 41.51 | 0.03 | 0.15 | OK |
| USBC_DP / USBC_DM | 41.09 | 41.16 | 0.08 | 0.15 | OK |
| HUB_UP_DP / HUB_UP_DM | 37.34 | 37.42 | 0.08 | 0.15 | OK |
| ETH_MDI0_P / ETH_MDI0_N | 15.30 | 15.23 | 0.07 | 0.15 | OK |
| ETH_MDI1_P / ETH_MDI1_N | 21.79 | 21.87 | 0.07 | 0.15 | OK |
| ETH_MDI2_P / ETH_MDI2_N | 15.07 | 15.15 | 0.08 | 0.15 | OK |
| ETH_MDI3_P / ETH_MDI3_N | 16.76 | 16.69 | 0.08 | 0.15 | OK |

**9 groups need tuning.** Use KiCad PCB editor → Route → Tune length / skew on each TUNE row, then re-run `tools/length_report.py`.
