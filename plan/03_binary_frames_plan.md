# Learning Plan — Binary Frames (Advanced C · Topic 3)
**Code target:** `~/embedded-linux/advanced-c/binary_frames/` · **Lab code:** `notes/advanced-c/03_binary_frames.md`

---

# Part 1 — WHY we are learning this

Your TCU's entire job is moving structured data: GPS fix + battery voltage + status flags, packed into bytes, pushed through the EC200U to a server. Every embedded product does this — over UART, CAN, BLE, TCP, flash storage. The naive approach is:

```c
send(socket, &my_struct, sizeof(my_struct));   /* DO NOT DO THIS */
```

It compiles. It works on your desk. It fails in the field, **silently**, for two reasons the compiler never warns about:

1. **Padding** — the compiler inserts invisible bytes inside your struct. Your ARM firmware and the x86 server compute *different layouts for the same struct definition*. Fields land in the wrong place; battery voltage reads as garbage.
2. **Endianness** — ARM (little-endian here) stores `0x12345678` as `78 56 34 12`. A big-endian reader sees your device ID byte-reversed. Nothing crashes. The data is just *wrong*.

Why this matters for your career: serialization bugs are among the most expensive in embedded — they pass all unit tests on one machine and corrupt data only in mixed-architecture deployments. Interviewers probe this hard because it separates people who've *shipped* cross-platform systems from people who've only compiled on one. And in Phase 4 (drivers), the same discipline applies to hardware register maps — a register block is a wire format the silicon defines, not a C struct you trust the compiler with.

**The goal of this topic:** never trust the compiler's memory layout at any boundary (wire, flash, registers). Place every byte yourself.

---

# Part 2 — The concepts, before any code

## 2.1 Memory alignment & struct padding
CPUs fetch memory in aligned chunks. A `uint32_t` at address 0x1003 (not divisible by 4) needs two bus reads on many cores — and on some ARM cores it's a **fault**, not a slowdown. So the compiler aligns every struct member to its natural boundary (a 4-byte type sits at an address divisible by 4), inserting **padding bytes** to make that true, plus tail padding so arrays of the struct stay aligned.

Consequences you must own:
- `sizeof(struct)` ≥ sum of members. The holes are real bytes containing garbage.
- **Member order changes struct size.** `{u8, u32, u16, u8}` = 12 bytes; `{u32, u16, u8, u8}` = 8.
- `offsetof(type, member)` is the truth-teller — it shows where each member actually sits.

## 2.2 Endianness
Endianness = the order a multi-byte value's bytes are stored in memory. Little-endian (your x86 WSL, most ARM configs): least-significant byte first. Big-endian: most-significant first — and by convention, **network byte order** is big-endian. Two machines exchanging raw memory must agree on order; the portable answer is to *define the wire order in the protocol* and convert explicitly at the boundary.

## 2.3 Serialization (the fix)
A **wire format** is a contract: "byte 0 is the magic, bytes 2–5 are device_id, big-endian." A serializer writes each byte to its contracted position using shifts and masks — math, not memory layout. The result is identical on every CPU, every compiler, every optimization level. That's the property we're buying.

## 2.4 Integrity: checksums
UART lines glitch; cellular links drop bits. A receiver must *detect* damage, so the last byte is a checksum the receiver recomputes. XOR is the teaching version (1 line, catches any single-byte corruption); CRC is the production version (catches burst errors — you'll meet CRC in CAN and in Phase 4). Rule: a decoder **rejects loudly**; it never guesses.

## 2.5 C API design (the quiet fifth concept)
This lab is also your first professionally-shaped C module: opaque-ish struct + small function API, caller-owned buffers, `const`-correct inputs, integer error codes, no hidden allocation, no global state. This shape is how every driver and library you'll read is built.

---

# Part 3 — How our code meets each concept

| Concept | Where in the code | What proves it |
|---|---|---|
| Padding is real | `padding_probe.c` | predicted 8, `sizeof` says 12; `offsetof` locates the holes |
| Order matters | ladder ex. 1 | reorder fields → size changes |
| Endianness is real | `padding_probe.c` | `0x12345678` prints `78 56 34 12` |
| Explicit serialization | `put_u32/put_u16` in `frame.c` | shifts place bytes; no struct is ever sent |
| Wire contract | `FRAME_WIRE_SIZE`, offsets in `frame_encode` | 14 is counted by hand from the protocol, not `sizeof` |
| Integrity | `xor_sum`, last wire byte | corrupting one byte makes decode return −2 |
| Reject loudly | `frame_decode` checks length → magic → checksum | distinct error codes −1 / −2 |
| Pro API shape | `frame.h` | `const` in, caller buffer + length, error codes out |

---

# Part 4 — frame.h, line by line (every keyword justified)

```c
#ifndef FRAME_H
#define FRAME_H
```
**Header guard.** Headers get included by many files; without the guard, the second inclusion would redefine `frame_t` → compile error. The preprocessor skips the body if `FRAME_H` is already defined. (Modern alternative `#pragma once` works everywhere that matters, but guards are the portable convention you'll see in kernel code.)

```c
#include <stdint.h>
```
Gives **fixed-width types** (`uint8_t`, `uint32_t`). Plain `int`/`long` change size across platforms (an `int` is 16-bit on some MCUs!). A wire protocol needs exact widths — "4 bytes" must mean 4 bytes on every machine. In embedded, default to fixed-width for any data with a defined size.

```c
#include <stddef.h>
```
For `size_t` — see below.

```c
#define FRAME_MAGIC     0xA5u
```
**Why a magic byte at all:** a receiver picking up mid-stream needs a way to find frame starts; 0xA5 (`10100101` — alternating bits, easy to spot on a scope) is a classic sync byte.
**Why `#define` and not `const uint8_t`:** a `#define` is a compile-time literal usable in array sizes and `_Static_assert`; a `const` variable in C (unlike C++) is not a true compile-time constant. **Why the `u` suffix:** makes the literal unsigned, avoiding signed/unsigned comparison warnings when compared against `uint8_t` values.

```c
#define FRAME_WIRE_SIZE 14u    /* 1 magic +1 type +4 id +4 ticks +2 mv +1 flags +1 xor */
```
Counted **by hand from the protocol contract** — deliberately NOT `sizeof(frame_t)`. That's the entire lesson in one line: wire size comes from the protocol, never from the compiler's struct layout. The comment showing the arithmetic is part of the documentation.

```c
typedef struct {
    uint8_t  msg_type;
    uint32_t device_id;
    uint32_t uptime_ticks;
    uint16_t battery_mv;
    uint8_t  flags;
} frame_t;
```
**Why `typedef`:** without it, every use is `struct frame f;` — the typedef makes `frame_t` a single-word type name, the dominant style in firmware APIs (`ringbuf_t`, `at_parser_t`, same pattern). The `_t` suffix signals "this is a type."
**Why this struct exists at all if we don't send structs:** it's the **in-memory working representation** — convenient, aligned, fast for your application code. The struct lives *inside* one machine; only serialized bytes cross machines. Two representations, one explicit conversion: that's the architecture.
**Why these field types:** each is the smallest fixed-width type that fits the real quantity — `battery_mv` maxes around 4200 (fits `uint16_t`), `flags` is a bitfield byte. On a 256 KB-RAM MCU, this sizing habit is survival.

```c
size_t frame_encode(const frame_t *f, uint8_t *buf, size_t buflen);
```
- **Why `const frame_t *f`:** pointer (cheap — no 12-byte copy) + `const` (contract: "I only read your frame"). The compiler now *enforces* that promise — a typo like `f->flags = 0` inside encode becomes a compile error. `const`-correctness is free documentation plus a free proofreader.
- **Why `uint8_t *buf, size_t buflen` (caller-owned buffer):** the caller decides where memory comes from — stack, static pool, DMA region. The function never `malloc`s. Embedded code avoids hidden allocation: heap on small systems means fragmentation and nondeterminism. Passing the length lets the function defend against overflow.
- **Why `size_t` and not `int` for sizes:** `size_t` is the unsigned type the platform defines as "big enough for any object size" — it's what `sizeof` returns and what `memcpy` takes. Using `int` for sizes invites signed/unsigned bugs and limits range.
- **Why return `size_t` (bytes written, 0 on failure):** encoders conventionally report how much they produced — callers chain this (`uart_send(buf, n)`). 0 is a safe impossible-on-success sentinel.

```c
int frame_decode(const uint8_t *buf, size_t len, frame_t *out);
```
- **Why `const uint8_t *buf`:** decoding must not modify received bytes (you may need them again — relog, retry, debug dump).
- **Why `frame_t *out` instead of returning a `frame_t`:** the return channel is reserved for the **error code**; results travel through an out-parameter. Returning a struct by value also costs a copy and can't express "I failed." This out-param pattern is the standard C idiom — you'll see it everywhere in the kernel.
- **Why `int` return with 0 = success, negative = error:** the UNIX/kernel convention (`-EINVAL`, `-ENODEV`...). Distinct codes (−1 bad frame, −2 bad checksum) let the caller react differently — a checksum failure might request retransmission; a bad magic means resync the stream.

```c
#endif
```
Closes the header guard. Comment it (`#endif /* FRAME_H */`) in bigger headers.

---

# Part 5 — frame.c, line by line

```c
static void put_u16(uint8_t *b, uint16_t v) { b[0] = v >> 8; b[1] = v; }
```
- **Why `static`:** on a function, `static` means *file-private* — invisible to the linker, not callable from other .c files. These helpers are implementation detail; hiding them keeps the public API exactly what `frame.h` declares, prevents name collisions across a big codebase, and lets the compiler inline them aggressively. Habit: **every function is `static` unless it's in the header.**
- **Why `void` return:** the function exists for its *side effect* (writing two bytes); it has nothing meaningful to return. Declaring `void` tells reader and compiler "don't expect a value." (Contrast: C's other `void` uses — `void` parameter list `f(void)` = "takes nothing", and `void *` = "pointer to anything" — three related-but-different meanings.)
- **The body:** `v >> 8` shifts the high byte down into the low position; assigning to `b[0]` (a `uint8_t`) keeps only the low 8 bits. `b[1] = v` truncates to the low byte — intentional, and it's high-byte-first, i.e. **big-endian by construction**. This is endianness handled with arithmetic: shifts are defined by *value*, not by memory order, so this code emits identical bytes on any CPU.

```c
static void put_u32(uint8_t *b, uint32_t v)
{
    b[0] = v >> 24; b[1] = v >> 16; b[2] = v >> 8; b[3] = v;
}
```
Same idea, four bytes. Note there are **no casts needed when narrowing into `uint8_t`** — the assignment truncates — but watch the *opposite* direction below.

```c
static uint32_t get_u32(const uint8_t *b)
{
    return (uint32_t)b[0] << 24 | (uint32_t)b[1] << 16 | (uint32_t)b[2] << 8 | b[3];
}
```
- **Why the `(uint32_t)` casts — the integer-promotion trap (interview gold):** in C, anything smaller than `int` is promoted to **signed `int`** before arithmetic. `b[0] << 24` therefore shifts a *signed int*; if `b[0] ≥ 0x80`, a 1 lands in the sign bit — **undefined behavior**. The cast forces unsigned 32-bit math first. Most engineers learn this from a 2 a.m. bug; you're learning it here.
- **Why `|` (OR) to combine:** each byte occupies disjoint bit positions after shifting; OR assembles them. (`+` would also work here but OR states the intent: bit assembly, no carries.)

```c
static uint8_t xor_sum(const uint8_t *b, size_t n)
{
    uint8_t s = 0;
    while (n--) s ^= *b++;
    return s;
}
```
- **`while (n--)`** — loop n times, idiomatic C: test, then decrement. **`*b++`** — dereference, then advance the pointer: classic pointer-walk. You must be able to read both fluently; half of all real C uses them.
- **Why XOR:** `s` flips wherever data bits are set; any single corrupted byte changes `s`. Limitation (ladder ex. 3): two errors can cancel, and XOR is order-blind. CRC fixes both — later.

```c
size_t frame_encode(const frame_t *f, uint8_t *buf, size_t buflen)
{
    if (buflen < FRAME_WIRE_SIZE) return 0;
```
**Bounds check FIRST.** The function refuses to write byte 0 until it knows all 14 fit. Buffer overflow is the #1 C vulnerability class; the guard-clause-at-the-top shape is how production code looks.

```c
    buf[0] = FRAME_MAGIC;
    buf[1] = f->msg_type;
    put_u32(&buf[2],  f->device_id);
    put_u32(&buf[6],  f->uptime_ticks);
    put_u16(&buf[10], f->battery_mv);
    buf[12] = f->flags;
```
Every offset is **literal and visible** — byte 2, byte 6, byte 10 — matching the protocol comment in `frame.h`. `&buf[2]` passes the address of slot 2, so `put_u32` writes bytes 2..5. This is the contract, executable.

```c
    buf[13] = xor_sum(buf, 13);
    return FRAME_WIRE_SIZE;
}
```
Checksum covers bytes 0..12 — everything before itself (it can't cover itself: writing it would change it).

```c
int frame_decode(const uint8_t *buf, size_t len, frame_t *out)
{
    if (len < FRAME_WIRE_SIZE || buf[0] != FRAME_MAGIC) return -1;
    if (xor_sum(buf, 13) != buf[13])                    return -2;
```
**Validation order is deliberate:** length first (everything after reads up to byte 13 — reading them on a short buffer would be an out-of-bounds read), then magic (cheap reject of mid-stream garbage), then checksum (costs a 13-byte pass, so do it last). Cheap checks before expensive ones — a pattern from parsers to firewalls. Note `||` short-circuits: if `len` is too small, `buf[0]` is never touched.

```c
    out->msg_type     = buf[1];
    out->device_id    = get_u32(&buf[2]);
    ...
    return 0;
}
```
The exact mirror of encode, same offsets. Only after *all* checks pass does it touch `out` — a failed decode leaves the caller's struct unmodified, so there's no half-written state to misuse.

---

# Part 6 — Language-construct quick reference (the "why" cheat sheet)

| Construct | Why it's used here |
|---|---|
| `typedef struct {...} name_t` | one-word type name; standard firmware API style |
| `void` return | function works by side effect; nothing meaningful to return |
| `f(void)` param list | explicitly "takes no arguments" (in C, `f()` historically meant "unspecified args") |
| `static` on a function | file-private; hides implementation, prevents collisions, enables inlining |
| `const` on pointer params | enforced promise not to modify; free documentation + compiler proofreading |
| `uint8_t` not `char` | `char` has *implementation-defined signedness* — `char` 0xA5 may be negative; bytes must be unsigned |
| `size_t` for sizes/counts | the platform's object-size type; what `sizeof` returns; never negative |
| `#define` for protocol constants | true compile-time constant; usable in `_Static_assert` / array sizes |
| `0xA5u` suffix | unsigned literal; kills signed/unsigned comparison warnings |
| out-parameter `frame_t *out` | return channel reserved for error code; no struct copy |
| negative error codes | kernel/UNIX convention; distinct codes → distinct caller reactions |
| `(uint32_t)` cast before `<<` | defeats promotion to signed int; avoids UB shifting into the sign bit |

---

# Part 7 — Study flow (~2 hours)

1. **(20 min)** Read Parts 1–3 above. Then `padding_probe.c` from the lab note: *predict* `sizeof` before running. Run, then `offsetof` the holes. Reorder fields, re-predict, re-run.
2. **(40 min)** Type in `frame.h` + `frame.c`, *reading Part 4/5 alongside* — for each line, say the "why" before typing it.
3. **(20 min)** `main.c`, build, hexdump: find `A5`, find `DE AD BE EF` at bytes 2–5, verify byte 13 by XOR-ing by eye if you're brave. gdb: `x/14xb wire`.
4. **(30 min)** Ladder from the lab note: minimum exercises 1 (reorder), 2 (`packed`), 3 (fool the XOR), 4 (chain through your ring buffer).
5. **(10 min)** Part 6 table, out loud, closed notes. Then commit:
   `git add . && git commit -m "binary_frames: codec + line-by-line review (david)" && git push`

**Done =** all asserts pass · you can explain why `FRAME_WIRE_SIZE ≠ sizeof(frame_t)` · you can state the integer-promotion trap from memory · one line + confidence /5 to Claude.

---

*Next plans will land in this same `plans/` folder as we open each topic.*
