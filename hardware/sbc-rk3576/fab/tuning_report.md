# Length tuning report

`tools/tune_length.py` on the routed board: 107 meanders kept (0 reverted after DRC), 286.5 mm of track added. Meander gap 3w, amplitude 3w..1 mm, pair skew bumps >= 1w.

## DRC (KiCad, input -> output)

| check | before | after |
|---|---:|---:|
| clearance | 0 | 0 |
| hole_clearance | 0 | 0 |
| shorting_items | 0 | 0 |
| tracks_crossing | 0 | 0 |
| copper_edge_clearance | 0 | 0 |
| hole_to_hole | 0 | 0 |
| unconnected (ratsnest) | 14 | 14 |

## Groups

Spread = longest - shortest member (lanes), skew = |P - N| (pairs). Target = longest routed member.

| group | routed | tol | before | after | status | notes |
|---|---:|---:|---:|---:|---|---|
| LP5_CLK_A | 2/2 | 0.1 | 3.24 | 0.05 | OK |  |
| LP5_CLK_B | 2/2 | 0.1 | 3.54 | 0.05 | OK |  |
| LP5_WCK0_A | 2/2 | 0.1 | 9.62 | 0.05 | OK |  |
| LP5_WCK0_B | 2/2 | 0.1 | 1.02 | 0.05 | OK |  |
| LP5_WCK1_A | 2/2 | 0.1 | 0.82 | 0.05 | OK |  |
| LP5_WCK1_B | 2/2 | 0.1 | 10.90 | 4.15 | OUT | still short by (mm): LP5_WCK1P_B 4.15 (no free space) |
| LP5_RDQS0_A | 2/2 | 0.1 | 16.58 | 2.19 | OUT | still short by (mm): LP5_RDQS0N_A 2.19 (no free space) |
| LP5_RDQS0_B | 2/2 | 0.1 | 0.83 | 0.05 | OK |  |
| LP5_RDQS1_A | 2/2 | 0.1 | 0.53 | 0.05 | OK |  |
| LP5_RDQS1_B | 2/2 | 0.1 | 3.26 | 0.05 | OK |  |
| HDMI_TX_D0 | 2/2 | 0.15 | 3.05 | 0.08 | OK |  |
| HDMI_TX_D1 | 2/2 | 0.15 | 1.53 | 0.07 | OK |  |
| HDMI_TX_D2 | 2/2 | 0.15 | 0.31 | 0.08 | OK |  |
| HDMI_TX_D3 | 2/2 | 0.15 | 1.27 | 0.08 | OK |  |
| PCIE0_TX | 1/2 | 0.15 | - | - | skipped | not fully routed: PCIE0_TXN |
| PCIE0_RX | 2/2 | 0.15 | 4.52 | 0.07 | OK |  |
| PCIE0_REFCLK | 2/2 | 0.15 | 6.19 | 0.07 | OK |  |
| USB3_TX | 2/2 | 0.15 | 12.44 | 0.07 | OK |  |
| USB3_RX | 2/2 | 0.15 | 0.03 | 0.03 | OK |  |
| USBC_D | 2/2 | 0.15 | 3.30 | 0.08 | OK |  |
| HUB_UP_D | 2/2 | 0.15 | 5.73 | 0.08 | OK |  |
| ETH_MDI0 | 2/2 | 0.15 | 3.30 | 0.07 | OK |  |
| ETH_MDI1 | 2/2 | 0.15 | 5.72 | 0.07 | OK |  |
| ETH_MDI2 | 2/2 | 0.15 | 3.41 | 0.08 | OK |  |
| ETH_MDI3 | 2/2 | 0.15 | 2.02 | 0.08 | OK |  |
| A0 | 9/9 | 1 | 20.29 | 11.28 | OUT | still short by (mm): LP5_DQ7_A 11.28 (no free space), LP5_DQ3_A 10.71 (no free space), LP5_DQ6_A 10.51 (no free space), LP5_DQ5_A 8.32 (no free space), LP5_DQ2_A 6.63 (no free space) |
| A1 | 9/9 | 1 | 11.70 | 8.32 | OUT | still short by (mm): LP5_DQ15_A 8.32 (no free space), LP5_DQ9_A 6.97 (no free space), LP5_DQ10_A 3.63 (no free space) |
| CA_A | 9/9 | 2 | 13.58 | 11.54 | OUT | still short by (mm): LP5_A3_A 11.54 (no free space), LP5_A5_A 9.63 (no free space), LP5_A2_A 8.19 (no free space), LP5_A6_A 7.68 (no free space), LP5_A4_A 7.44 (no free space) |
| B0 | 8/9 | 1 | 14.44 | - | skipped | not fully routed: LP5_DMI0_B |
| B1 | 9/9 | 1 | 16.37 | 7.85 | OUT | still short by (mm): LP5_DQ12_B 7.85 (no free space), LP5_DQ14_B 4.43 (no free space), LP5_DQ15_B 3.31 (no free space) |
| CA_B | 9/9 | 2 | 14.85 | 11.15 | OUT | still short by (mm): LP5_A1_B 11.15 (no free space), LP5_CSN0_B 10.39 (no free space), LP5_CSN1_B 8.61 (no free space), LP5_A4_B 4.82 (no free space) |

## Members (mm, before -> after, target)

- **LP5_CLK_A** (target 14.73): LP5_CLKN_A 11.49->14.68
- **LP5_CLK_B** (target 19.81): LP5_CLKN_B 16.27->19.76
- **LP5_WCK0_A** (target 46.36): LP5_WCK0N_A 36.74->46.31
- **LP5_WCK0_B** (target 19.64): LP5_WCK0P_B 18.61->19.59
- **LP5_WCK1_A** (target 24.15): LP5_WCK1P_A 23.33->24.10
- **LP5_WCK1_B** (target 38.95): LP5_WCK1P_B 28.05->34.80
- **LP5_RDQS0_A** (target 46.88): LP5_RDQS0N_A 30.30->44.69
- **LP5_RDQS0_B** (target 16.50): LP5_RDQS0P_B 15.67->16.45
- **LP5_RDQS1_A** (target 22.42): LP5_RDQS1N_A 21.88->22.37
- **LP5_RDQS1_B** (target 36.22): LP5_RDQS1N_B 32.96->36.17
- **HDMI_TX_D0** (target 17.82): HDMI_TX_D0N 14.77->17.74
- **HDMI_TX_D1** (target 14.62): HDMI_TX_D1N 13.09->14.55
- **HDMI_TX_D2** (target 16.70): HDMI_TX_D2N 16.39->16.62
- **HDMI_TX_D3** (target 17.67): HDMI_TX_D3P 16.41->17.60
- **PCIE0_RX** (target 34.20): PCIE0_RXN 29.69->34.13
- **PCIE0_REFCLK** (target 35.51): PCIE0_REFCLKN 29.32->35.44
- **USB3_TX** (target 51.06): USB3_TXN 38.62->50.99
- **USB3_RX** (target 41.51): 
- **USBC_D** (target 41.16): USBC_DP 37.86->41.09
- **HUB_UP_D** (target 37.42): HUB_UP_DP 31.69->37.34
- **ETH_MDI0** (target 15.30): ETH_MDI0_N 12.00->15.23
- **ETH_MDI1** (target 21.87): ETH_MDI1_P 16.15->21.79
- **ETH_MDI2** (target 15.15): ETH_MDI2_P 11.74->15.07
- **ETH_MDI3** (target 16.76): ETH_MDI3_N 14.75->16.69
- **A0** (target 38.97): LP5_DQ0_A 28.69->38.72, LP5_DQ1_A 31.25->38.72, LP5_DQ2_A 25.62->32.34, LP5_DQ3_A 18.68->28.26, LP5_DQ4_A 37.05->38.72, LP5_DQ5_A 28.38->30.66, LP5_DQ6_A 24.36->28.46, LP5_DQ7_A 24.46->27.69
- **A1** (target 24.34): LP5_DQ8_A 12.63->24.09, LP5_DQ9_A 16.78->17.36, LP5_DQ10_A 14.64->20.71, LP5_DQ11_A 21.34->24.09, LP5_DQ12_A 20.86->24.15, LP5_DQ13_A 23.14->24.09, LP5_DQ15_A 14.80->16.02, LP5_DMI1_A 22.91->24.23
- **CA_A** (target 25.93): LP5_A1_A 20.64->25.21, LP5_A2_A 17.25->17.74, LP5_A3_A 12.57->14.39, LP5_A4_A 15.28->18.49, LP5_A5_A 12.35->16.30, LP5_A6_A 13.73->18.25, LP5_CSN0_A 20.49->25.43
- **B1** (target 39.31): LP5_DQ8_B 33.95->39.06, LP5_DQ9_B 31.46->39.06, LP5_DQ11_B 32.15->39.06, LP5_DQ12_B 22.94->31.46, LP5_DQ13_B 32.50->38.85, LP5_DQ14_B 29.32->34.88, LP5_DQ15_B 26.41->36.00, LP5_DMI1_B 32.82->39.06
- **CA_B** (target 25.95): LP5_A0_B 11.09->24.03, LP5_A1_B 11.82->14.80, LP5_A2_B 16.17->25.45, LP5_A3_B 17.88->25.17, LP5_A4_B 19.22->21.12, LP5_CSN0_B 14.47->15.55, LP5_CSN1_B 13.80->17.34
