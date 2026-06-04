# Phase 1 — Systems C & Advanced Linux · LOG

> Interview-story bank. One entry per thing that broke + how I fixed it. Dates absolute.
> Jira: SCRUM-31 · Target 2026-06-02 → 2026-06-22

## Week 1 — Advanced C (pointers, memory layout, volatile, bit-ops, linker scripts, function pointers, struct alignment)
- Hands-on goal: fixed-point math lib + ring buffer, inspected with `objdump`/`readelf`.

## Week 2 — Linux process model & IPC (fork/exec, signals, pipes, shm, mqueue, sockets, /proc, /sys)
- Hands-on goal: producer/consumer over POSIX shared memory + semaphores.

## Week 3 — Toolchain & build (GCC pipeline, Make/CMake, static vs dynamic, gdb/strace/ltrace/valgrind)
- Hands-on goal: cross-build "hello" for aarch64, run on the Radxa (A527 / Cortex-A55).

---

## Entries

### 2026-06-01 · Day 0 — environment prep
- Host had binutils (objdump/readelf/nm) but **no gcc/make/gdb/cmake** and **no aarch64 cross-compiler**.
- Installing: build-essential gdb cmake gcc-aarch64-linux-gnu valgrind strace ltrace picocom sunxi-tools.
- Note: A527 is **aarch64** (64-bit Cortex-A55) → cross prefix is `aarch64-linux-gnu-`, NOT 32-bit `arm-linux-gnueabihf-`.
