# Design notes: why each choice was made

## 1. SoC choice: RK3576

| Candidate | Cores | LPDDR5 | 4K out | PCIe for NVMe | Cost | Verdict |
|---|---|---|---|---|---|---|
| **Rockchip RK3576** | 4×A72 + 4×A53 | ✅ LP4/4X/5/5X, 32-bit | HDMI 2.1 4K@120 | PCIe 2.1 ×1 (×2 ports) | ~$22 | **chosen** |
| Rockchip RK3588S | 4×A76 + 4×A55 | ✅ 64-bit | 8K | PCIe 2.1 ×1 only on S | ~$40+ | 2× cost, larger PI problem |
| Allwinner A527/T527 (your Radxa A5E) | 8×A55 | ❌ LPDDR4/4X only | 4K | PCIe 2.1 ×1 | ~$12 | fails the LPDDR5 requirement |
| MediaTek Genio 510/700 | 2×A78 + 4×A55 | ✅ | 4K | ✅ | NDA-only | not available to hobby/portfolio builds |

RK3576 is the cheapest octa-core part that does LPDDR5 natively and has a public reference design to copy
from (Radxa ROCK 4D). **Trade-off to know:** NVMe runs on PCIe 2.1 ×1, about 400 MB/s real-world. That is
still around 4× eMMC and fine for a gateway. If you need Gen3 ×4, you need an RK3588 board at roughly twice
the cost.

## 2. Memory: one LPDDR5 x32 package

- RK3576's DDR PHY is 32 bits wide, as two 16-bit channels A/B. One x32 315-ball package covers it, so there
  is a single BGA to route instead of two x16 parts.
- 4 GB (`MT62F1G32D2DS`, 2 dies) and 8 GB (`MT62F2G32D4DS`, 4 dies) share the 315b footprint and ballout.
  **The RAM size is a BOM choice, not a PCB respin.** The DDR init blob (`rk3576_ddr_*.bin`) sizes it at boot.
- Clocking: LPDDR5 has a **CK** command clock (≤ 800 MHz) plus per-byte **WCK** write clocks at 4× CK, and
  **RDQS** read strobes. Those three timing domains are why LPDDR5 layout rules are stricter than LPDDR4.
- Rails: VDD1 1.8 V, VDD2H 1.05 V, VDD2L 0.9 V, VDDQ 0.5 V. ZQ uses 240 Ω to VDDQ on the DRAM side and
  240 Ω to GND on the SoC side.

## 3. Power tree

Input: USB-C 5 V/3 A (5.1 kΩ Rd on CC1/CC2, no PD) → 6 A fuse → 5 V TVS → `VCC5V0_SYS_S5`.

| Rail | Source | V | Feeds |
|---|---|---|---|
| VDD_CPU_BIG_S0 | RK806 BUCK1 (6.5 A, 0.24 µH) | 0.55–0.95 (DVFS) | A72 cluster |
| VDD_NPU_S0 | BUCK2 (5 A) | 0.55–0.95 | NPU |
| VDD_CPU_LIT_S0 | BUCK3 (5 A) | 0.55–0.95 | A53 cluster |
| VCC_3V3_S3 | BUCK4 (5 A) | 3.3 | always-on 3.3 V: PMUIO1 (debug UART), Ethernet PHY, Wi-Fi |
| VDD_GPU_S0 | BUCK5 | 0.55–0.90 | Mali-G52 |
| VDDQ_DDR_S0 | BUCK6 | 0.5 | LPDDR5 VDDQ + DDR PHY VDDQ |
| VDD_LOGIC_S0 | BUCK7 | 0.55–0.80 | logic, memories |
| VCC_1V8_S3 | BUCK8 | 1.8 | PMUIO0, VCCIO0/4/5/7, eMMC VCCQ, RGMII, LPDDR5 VDD1 (through a bead) |
| VDD2H_DDR_S3 | BUCK9 | 1.05 | LPDDR5 VDD2H |
| VDD_DDR_S0 | BUCK10 | 0.55–1.2 | DDR PHY digital |
| VCC_2V0_PLDO_S3 | TPS562201 | 2.0 | PLDO1–3 pre-regulator (keeps LDO loss low) |
| VCC_1V1_NLDO_S3 | TPS562201 | 1.1 | NLDO1–5 pre-regulator |
| VDD2L_DDR_S3 | TPS562201 | 0.9 | LPDDR5 VDD2L |
| VCC3V3_PCIE | TPS563201 (3 A) | 3.3 | M.2 SSD (up to 2.5 A peaks), enabled by VCC_3V3_S0 |
| VCC_3V3_S0 | AP2171W from 3V3_S3, EN = PMIC EXT_EN | 3.3 | VCCIO2/3/6, eMMC VCC |
| PLDO1..5 | RK806 | 1.8/1.8/1.2/3.3/SD | PHY analog 1.8 V, HDMI 1.8 V, DCPHY 1.2 V, USB 3.3 V, SD IO |
| NLDO1..5 | RK806 | 0.75/0.85/0.8375/0.85/0.75 | PMU logic, DDR PLL, HDMI PHY, PHY 0.85 V, PLL/USB2 0.75 V |

**Sequencing:** the **RK806S-5** variant has an OTP slot table preset for RK3576, so each buck/LDO must
carry the rail that OTP expects. The mapping above is **verified against mainline Linux
`rk3576-rock-4d.dts`** (same PMIC variant + SoC). Rev A0 got 12 of these assignments wrong; the
device-tree cross-check caught it (see LOG.md #11).

**Power budget:** ~15 W from USB-C 5 V/3 A. An RK3576 under full CPU+NPU load (~6–7 W), plus an NVMe SSD
(up to ~8 W peak), plus USB3 VBUS (4.5 W) can exceed that. Use a 5 V/4 A supply, or add a PD sink
controller in rev B (e.g. CH224K, about $0.30) and take 9 V.

## 4. Interfaces and pin mapping (selected)

| Function | RK3576 ball(s) | Net(s) | Notes |
|---|---|---|---|
| Debug UART0_M0 | 1U24 TX, AA28 RX | DBG_UART_TX/RX | PMUIO1 = 3.3 V, 1 500 000 baud |
| PMIC I²C1_M0 | 1T22 SCL, 1T23 SDA | PMIC_SCL/SDA | 2.2 kΩ to 1.8 V |
| Boot mode | A25 SARADC_IN0_BOOT | — | 10 kΩ pull-up; MASKROM key pulls low → USB download on USB-C |
| eMMC | EMMC_D0..7, CMD, CLK, STRB, RSTN | EMMC_* | HS400 at 1.8 V VCCQ |
| microSD | SDMMC0_D0..3, CMD, CLK, DETN, PWREN | SD_* | VCCIO_SD from PLDO5 (3.3 V / 1.8 V UHS) |
| NVMe | PCIE0_TX/RX/REFCLK (P28/P29/R28/R29/1N22/1N23) | PCIE0_* | 220 nF TX AC caps; PERST# GPIO4_C7, CLKREQ# GPIO4_C6 |
| HDMI | HDMI_TX_D0..3 P/N | HDMI_TX_D* | D3 = TMDS clock lane in TMDS mode; 220 nF AC + switched 590 Ω termination (per ROCK 4D) |
| HDMI DDC/CEC/HPD | AL2, 1AE2, AK3, AK2 | HDMI_SCL/SDA/CEC/HPD | BSS138 level shifters to 5 V; HPD divider |
| USB-C OTG0 | USB2_OTG0_DP/DM | USBC_DP/DM | maskrom/ADB, VBUSDET divider |
| USB3 host | USB3_OTG1_SS* + USB2_OTG1 | USB3_*, USB3A_* | 100 nF TX AC caps, 0.5 pF ESD, AP2171W VBUS switch |

Unused SoC balls are no-connect: MIPI CSI/DSI, UFS, the second Ethernet MAC,
audio, SPI and spare GPIO. Sheet 11 shows every free ball by name.

## 5. Known simplifications in rev A0 (decided on purpose)

- VDDQ is an S0 rail, so DDR self-refresh across deep suspend is not supported.
- PHY REXT resistors are DNP. The reference leaves them NC; the footprints are there in case the RK3576
  hardware guide says otherwise.
- RK806 FB pins use 0 Ω remote sense (internal reference via OTP). Divider footprints are DNP.
- No 40-pin header, analog audio, RTC battery or camera/display connectors. These were cut for cost.
  Gigabit Ethernet, a USB hub with 2 extra USB-A ports and Wi-Fi 5/BT were added in rev A1 for desktop use.
- No reverse-polarity FET: a USB-C source can't present reversed polarity, and a SOT-23 FET would dissipate
  about 0.5 W at 3 A.

## Interview questions this board answers

1. *Walk me through the boot chain.* BROM → (MASKROM if no boot media, or if SARADC_IN0 is pulled low) →
   SPL/TPL with the Rockchip DDR blob training LPDDR5 → TF-A BL31 → U-Boot → kernel + DTB → init. eMMC is
   tried before SD.
2. *Why AC-couple PCIe TX on the host but not RX?* Each transmitter carries its own coupling caps. The
   SSD's TX caps sit on the SSD.
3. *Why put decoupling under the BGA on the bottom side?* The via length from ball to cap sets the loop
   inductance. Bottom-side 0201/0402 directly under the power balls is the lowest-inductance path, and the
   bulk caps go around it.
4. *Why switch the HDMI termination with FETs?* So the source doesn't back-power a sink that is powered off,
   and so the PHY only sees the termination when HDMI is enabled.
5. *What does the S0/S3/S5 suffix tell the software team?* Which rails survive suspend. That decides what the
   kernel must save and restore, and which GPIO banks keep their state.
