# CLAUDE.md — Embedded Linux Mastery Project

## Who I am
Immanuel David (WSL user: `david`). Firmware engineer by trade — telematics / TCU, ATPL firmware — with solid Linux fundamentals and real bare-metal/embedded experience. Goal: become a high-tier (~50 LPA) **embedded Linux** engineer over 6 months. I learn best when the *why* is explained, not just the commands.

## How I want help
- **Teach as we go.** Explain the reasoning, the failure modes, and what an interviewer would probe — not just working commands. I'm here to master this, not to copy-paste.
- **Concise and direct.** Minimal fluff.
- **Tie it to my day-job** wherever natural: the Radxa board is the "ECU/Linux gateway," the EC200U is the "TCU modem," the Pico is the "sensor MCU." Framing it this way makes it stick.
- When you give shell commands, assume WSL Ubuntu unless I say otherwise, and flag anything that must run on the target board vs. the host.

## My hardware (we master Linux ON these — no abstract toy examples)
| Device | What it is | Role in this project |
|---|---|---|
| **Radxa Cubie A5E** | Allwinner **A527/T527** octa-core Cortex-A55 SBC (sunxi family), Mali-G57 GPU, RISC-V + NPU, LPDDR4, eMMC/SD, GbE×2, USB3, 40-pin GPIO | **Primary Linux target.** Boot flow, U-Boot, kernel, device tree, drivers, Yocto/BSP all happen here. |
| **USB–TTL (serial) converter** | 3.3V UART-to-USB adapter | Serial console to the Radxa debug UART — primary boot/debug channel. Also talks to EC200U / Pico UART. |
| **16GB microSD + card reader** | Boot media | Flash U-Boot + kernel + rootfs / Yocto images here and boot the Radxa from SD. |
| **Raspberry Pi Pico** | RP2040 dual Cortex-M0+, **no MMU** | Bare-metal / RTOS contrast to Linux. Acts as an **I²C/SPI sensor peripheral** the Radxa talks to in the driver phase. Pico C/C++ SDK. |
| **Quectel EC200U-CN** | LTE Cat-1bis cellular modem. UART×3, USB2.0, PPP/QMI/ECM/RNDIS, AT commands, QuecOpen SDK | **Cellular connectivity** for the networking phase — bring the Radxa online over cellular via PPP/QMI. Direct telematics/TCU parallel. |

## Layout & path map
- **Dev root (WSL native ext4):** `~/embedded-linux/` ← all code & builds live here. Run Claude Code from here.
- **Cowork docs (symlink):** `~/embedded-linux/cowork-docs/` → Windows `C:\home\Embeded`
  - Roadmap: `cowork-docs/Embedded_Linux_Roadmap.md`
- From Windows, this WSL dir is `\\wsl.localhost\Ubuntu\home\david\embedded-linux`
- Per-phase work in its own subfolder: `phase1-systems-c/`, `phase2-boot/`, `phase4-drivers/`, etc.

## HARD RULES
- **Never build kernel / U-Boot / Yocto / Buildroot trees under `/mnt/c/...` (the Windows filesystem).** It breaks on permissions, case-sensitivity, and symlinks, and is painfully slow. All build trees stay in WSL native fs (`~/embedded-linux/...`).
- **Always have the serial console attached** when bringing up the Radxa. If something "doesn't boot," the answer is almost always in the UART log.
- **microSD is disposable** — assume any flashing command can wipe it. Always confirm the device node (`lsblk`) before `dd`/`bmaptool`, never guess `/dev/sdX`.
- For the Radxa, **start from Radxa's official image** to confirm hardware works, *then* progressively replace U-Boot → kernel → rootfs with self-built pieces. Don't try to mainline-build everything on day one.

## Board-specific notes (Allwinner A527 / sunxi)
- Boot chain: **BROM → SPL (boot0/U-Boot SPL) → U-Boot → kernel → init**. Learn this order cold — it's the #1 interview topic.
- **FEL mode** (USB recovery) + `sunxi-tools` (`sunxi-fel`) let you recover a bricked board over USB-OTG without removing the SD. Know this before you start flashing.
- Community/reference: **linux-sunxi.org** (has a Radxa Cubie A5E page), Radxa Docs (`docs.radxa.com/en/cubie/a5e`), and the A527 datasheet on Radxa's CDN.
- A527 is **new (2025)**, so mainline kernel/U-Boot and Yocto support are still maturing — use Radxa's BSP / vendor layer where mainline gaps exist, and treat closing those gaps as bonus portfolio material.
- Serial console: connect TTL GND/TX/RX to the debug-UART header (check Radxa docs for exact pins/baud; sunxi commonly 115200 8N1). **Never connect the converter's VCC** — power the board separately.

## Hardware → roadmap phase mapping
1. **Systems C & Advanced Linux** (SCRUM-31) — C on the host; cross-compile a "hello" for ARM and run it on the Radxa. Pico optional for bare-metal contrast.
2. **Boot Flow & Foundations** (SCRUM-32) — Radxa + serial console: capture the full boot log, interrupt U-Boot, hand-build a BusyBox rootfs, boot from SD.
3. **Kernel Internals** (SCRUM-33) — build the sunxi kernel for the Radxa; write/load modules on the real board.
4. **Device Drivers & Device Tree** (SCRUM-34) — char + platform drivers on the Radxa; write a DT overlay; **I²C/SPI driver talking to the Pico (or a sensor) as the slave device**. Highest-value artifact.
5. **Yocto & BSP** (SCRUM-35) — build a custom Yocto/Buildroot image for the Radxa with your own app + a kernel-config change.
6. **Networking, RT, Debugging, Optimization** (SCRUM-36) — **EC200U-CN**: bring the Radxa online over cellular (PPP/QMI), AT-command bring-up; then PREEMPT_RT, cyclictest, boot-time/size optimization. This phase is your telematics showcase.
7. **Portfolio, System Design, Interview Prep** (SCRUM-37) — capstone: a Radxa "telematics gateway" combining your driver + Yocto image + EC200U cellular link + Pico sensor. Polish GitHub, prep interviews.

## Jira (project SCRUM, epic SCRUM-30)
Each phase above maps to a Jira task (SCRUM-31 … SCRUM-37). Move each to Done as its milestone artifact lands. A daily scheduled task surfaces that day's topic from the roadmap.

## Conventions
- Keep a `LOG.md` in each phase folder: what broke, how I fixed it. This becomes my interview-story bank.
- Commit milestones to git; the repo is the portfolio that goes to GitHub.
- Prefer mainline/upstream approaches where they exist; note where I had to use vendor BSP and why.
