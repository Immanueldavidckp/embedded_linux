# Will this board work as my Linux PC?

**Short answer:** yes for a light-to-medium desktop (terminal, coding, docs, web, 4K desktop), roughly
Raspberry Pi 4–5 class. That holds **once the board is built and brought up**. Nothing here replaces
powering a real board. This page lists what was checked, how, and what is still open.

## 1. Hardware checklist for a desktop

| PC need | On the board | Verdict |
|---|---|---|
| CPU | RK3576: 4× Cortex-A72 @ 2.2 GHz + 4× A53 | ✅ Pi 4–5 class. Fine for desktop, IDE, compiling small projects |
| RAM | LPDDR5 4 GB or **8 GB (recommended for a desktop + browser)** | ✅ BOM option, same PCB |
| Boot storage | eMMC 5.1 HS400 (32/64 GB) | ✅ |
| Fast storage | M.2 NVMe 2230/2242, PCIe 2.1 ×1 (~400 MB/s) | ✅ put `/home` or the whole rootfs here |
| Display | HDMI 2.1 TX, 4K@60 (TMDS) | ✅ 1080p/1440p/4K desktop |
| Keyboard / mouse / USB disks | 1× USB 3.0-A + 2× USB 2.0-A (FE1.1s hub) | ✅ |
| Wired network | Gigabit Ethernet (RTL8211F + MagJack) | ✅ |
| Wireless | Wi-Fi 5 dual-band + BT 4.2 (BL-M8821CU1, USB) + u.FL antenna | ✅ |
| Audio | HDMI audio only | ⚠️ no 3.5 mm jack: use HDMI monitor speakers, USB or BT headphones |
| Power | USB-C 5 V / **3 A max** (no PD controller) | ⚠️ see the power budget below |
| Debug / recovery | 3.3 V UART header, MASKROM key, microSD boot | ✅ |
| RTC battery | none | ⚠️ time comes from NTP after boot (add an RTC in rev B if needed) |

## 2. Software support (mainline, as of Oct 2026)

| Block | Linux driver | Status for this board |
|---|---|---|
| CPU DVFS, thermal | cpufreq-dt, rockchip thermal | ✅ mainline |
| RK806 PMIC | `rk806` (MFD + regulators) | ✅ mainline since 6.12 |
| LPDDR5 init | Rockchip TPL blob (`rkbin`), used by mainline U-Boot | ✅ (binary blob, as on every RK board) |
| eMMC / microSD | `sdhci-of-dwcmshc` / `dw_mmc-rockchip` | ✅ |
| NVMe on PCIe0 | `pcie-dw-rockchip` + `nvme` | ✅ |
| HDMI 4K | VOP2 + `dw-hdmi-qp` + HDPTX PHY | ✅ 4K@60 TMDS mainline; FRL 4K@120 still landing |
| GPU Mali-G52 | Panfrost (kernel) + Mesa | ✅ OpenGL ES 3.1 / desktop GL; GNOME/KDE run |
| Video decode | VDPU381/383 (H.264/HEVC) | ✅ merged upstream in 2026 |
| Video encode, NPU | — | ❌ vendor 6.1 BSP kernel only |
| Ethernet | `dwmac-rk` + `realtek` PHY | ✅ |
| USB 3 / USB 2 hub | `dwc3` + `usbdp`/`combphy` + generic hub | ✅ |
| Wi-Fi 5 / BT | `rtw88_8821cu` + `btusb`/`btrtl` | ✅ mainline (6.2+); needs `linux-firmware` |
| HDMI audio | `sai6` + hdmi-codec | ✅ |

Distro path: **Armbian or Radxa's Debian images for the ROCK 4D** boot on this board with our DTB, because
the SoC, PMIC rail map, DDR type and boot storage match. Mainline U-Boot supports RK3576. Expect
"just works" desktop behaviour, minus NPU and hardware video encoding.

## 3. What was checked, and how

| Check | Method | Result |
|---|---|---|
| Schematic electrical rules | KiCad 9 ERC, all severities | 0 errors, 0 warnings |
| PCB vs schematic | KiCad 9 DRC `--schematic-parity` | 0 parity errors |
| SoC land pattern | LCSC C42388007 footprint: 698 pad names == 698 datasheet balls | exact match |
| **PMIC rail map** | Compared sheet 02 against mainline `rk3576-rock-4d.dts` (same RK806S-5) | **found and fixed 12 wrong buck/LDO assignments** |
| **Device tree** | `software/rk3576-sbc.dts` compiled against mainline `rk3576.dtsi` (`tools/check_dts.sh`) | compiles, no warnings |
| DT GPIOs vs schematic | every `gpioN RK_Pxy` in the DTS mapped to its RK3576 ball and checked against the net in `design.py` | 7/7 match |
| Interface choices vs a shipping board | HDMI M0 DDC/HPD, GMAC0-M0 RGMII, PCIe0 + combphy0, OTG1 host + combphy1, SDMMC0 rails compared with the ROCK 4D DTS | consistent |

## 4. Power budget (5 V input)

| Load | Typical desktop | Worst case |
|---|---:|---:|
| RK3576 (CPU + GPU, NPU off) | 3.0 W | 7.0 W |
| LPDDR5 + eMMC | 0.7 W | 1.5 W |
| NVMe SSD (2242) | 0.5 W | 4.5 W |
| Ethernet + hub + Wi-Fi/BT | 1.0 W | 2.0 W |
| USB devices (keyboard, mouse, flash drive) | 0.5 W | 7.0 W (USB3 0.9 A + 2× 0.5 A) |
| Regulator losses (~85 %) | 1.0 W | 3.5 W |
| **Total** | **≈ 6.7 W** | **≈ 25 W** |

A 5 V/3 A USB-C supply (15 W) covers normal desktop use comfortably. Heavy CPU load, a busy NVMe and a
power-hungry USB3 disk *at the same time* can trip it. **Rev B fix:** add a USB-PD sink (CH224K, ~$0.30)
to negotiate 9 V or 12 V, plus a 5 V/5 A buck, or add a 12 V barrel jack. Until then, use bus-powered USB
disks sparingly, or a powered hub.

## 5. Still open (only real hardware or a layout engineer can close these)

1. Routing quality: the autorouted copper is *connected*, but LPDDR5 (6400 MT/s), HDMI, PCIe and USB3 need
   **length/skew tuning and impedance review**. See the length report in `fab/length_report.md`. Until that is
   done, expect DDR training to fail or fall back to low speed.
2. Signal/power integrity simulation, thermal (RK3576 needs a heatsink for sustained load).
3. First-article bring-up: rails → UART log → maskrom → DDR training → eMMC flash → Linux.
4. RTL8211F strap levels and FE1.1s straps are taken from datasheets and the reference design. Confirm
   them on the first board (MDIO read of PHY ID `0x001cc916` at address 1).
