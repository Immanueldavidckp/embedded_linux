# Plans — deep learning plans, one per topic

Every topic gets one file here, always the same shape:
**Part 1** why we learn it → **Part 2** the concepts → **Part 3** concept-to-code map → **Part 4** the code line by line, every keyword justified (`void`, `typedef`, `static`, `const`, …) → cheat-sheet table → study flow with ladder + interview probes.

Visible in WSL at `~/embedded-linux/cowork-docs/plans/` (or `~/embedded-linux/plans` if you made the symlink).

| # | Plan | Code target | Status |
|---|------|-------------|--------|
| 03 | `03_binary_frames_plan.md` — padding, endianness, frame codec | `advanced-c/binary_frames/` | ◀ current |
| 04 | `04_pointers_deep_dive_plan.md` — `**`, ownership, linked-list registry | `advanced-c/pointers/` | queued |
| 05 | `05_linux_processes_plan.md` — fork/exec/wait, mini-shell | `linux-process-ipc/mini_shell/` | queued |
| 06 | `06_ipc_pipes_plan.md` — pipes, fds, telemetry pipeline (reuses your frame codec) | `linux-process-ipc/telemetry_pipe/` | queued |

Topics 1–2 (ring buffer, state machine) predate this format — their labs live in `../notes/advanced-c/`.
Next after 06: toolchain & cross-compilation → then the Radxa boot-flow phase begins.
