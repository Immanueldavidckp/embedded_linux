# Week 1 — Advanced C: ring buffer

Hands-on for Phase 1 / Week 1 (SCRUM-31). A byte FIFO that deliberately exercises
the week's topics: **bit manipulation, struct alignment, `volatile`, `static`/`extern`,
and the GCC/binutils toolchain.**

## The task
Open `ringbuf.c` and implement the six `TODO`s. The file already compiles (stubs),
so the inspection targets work before you start. When you're done, `make run` is green.

```
make run        # build + run tests (red until you implement the TODOs)
make help       # list all targets
```

## The inspection targets ARE the lesson
Run each, then jot what you observed in `../LOG.md`:

| Command | What it teaches |
|---|---|
| `make layout` | `sizeof(ringbuf_t)` and field offsets → **struct padding/alignment**. Reorder fields, re-run: when does size change? |
| `make nm` | Symbol table. `is_pow2` is lowercase `t` (**static** = internal linkage); `rb_*` are uppercase `T` (**global**). |
| `make readelf` | ELF header (machine = x86-64 today; will be AArch64 after Week-3 cross-build), section headers, symbols. |
| `make asm` + `make asm-opt` | `vimdiff ringbuf.s ringbuf.opt.s` → see what `-O2` does vs `-O0`. Watch the bitmask wrap become a single `and`. |
| `make obj` | Disassembly with interleaved source — read your `rb_put` as actual instructions. |
| `make size` | `.text/.data/.bss` footprint — the embedded engineer's habit. |

## Design notes (the "why")
- **Power-of-2 capacity + `& mask`** replaces `% capacity`. Modulo is a divide; AND is one cycle. This is *the* embedded ring-buffer idiom.
- **Monotonic head/tail counters** never reset; the slot is `index & mask`. `count = head - tail` works through unsigned wraparound, so full-vs-empty is unambiguous **without wasting a slot**.
- **`volatile` ≠ thread-safe.** It stops register caching, nothing more — no atomicity, no ordering. For real cross-thread SPSC you need C11 `stdatomic.h` (acquire/release). `volatile` is for MMIO hardware registers. (This exact distinction is a common interview trap — see the note atop `ringbuf.c`.)

## Day-job parallel
This is the FIFO sitting under every UART RX path on your TCU — bytes arrive in an
ISR (producer), the main loop drains them (consumer). You've written this in bare
metal; here you'll see how the *same* structure compiles and how the toolchain shows
you its layout.

## Next in Week 1
Fixed-point math lib (Q-format) — same inspect-with-binutils workflow.
