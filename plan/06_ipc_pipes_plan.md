# Learning Plan — IPC with Pipes (Topic 6)
**Code target:** `~/embedded-linux/linux-process-ipc/telemetry_pipe/` · **Artifact:** a two-process telemetry pipeline reusing YOUR frame codec from Topic 3

---

# Part 1 — WHY we are learning this

Topic 5 gave you isolated processes — private address spaces that *cannot* touch each other. That isolation is a feature until your processes need to cooperate. Your capstone gateway is the proof: a **modem-manager** process producing telemetry and an **uploader** process consuming it. They need a kernel-provided channel: **IPC**.

Pipes are the first and most instructive channel:
- **A pipe IS a ring buffer in the kernel.** Literally — a fixed-size (64 KB on Linux) circular byte buffer, with the kernel handling the full/empty blocking you hand-rolled in Topic 1. Everything you learned there now reappears one level down.
- **Pipes teach file descriptors** — the single most important Linux abstraction. Master fd discipline here and sockets, serial ports (your EC200U's `/dev/ttyUSB0`!), and device files in Phase 4 all behave identically: `open/read/write/close` on a small integer.
- **The shell's `|`** — after this topic you know exactly what `dmesg | grep usb` does under the hood, and you'll build it.
- **Interview:** "how do pipes work?", "why must you close unused ends?", "what's a short read?" — all standard embedded-Linux screens.

**Goal:** move *your own binary frames* from a producer process to a consumer process through the kernel, handling the two real-world traps: unclosed ends and short reads.

---

# Part 2 — The concepts, before any code

## 2.1 File descriptors
A file descriptor (fd) is a small integer indexing a kernel table of open I/O objects for your process. 0 = stdin, 1 = stdout, 2 = stderr; everything you open next gets 3, 4… `read`/`write` work on fds regardless of what's behind them — file, pipe, socket, UART. **This uniformity is the UNIX superpower**: in Phase 6, your code reading GPS from a serial port uses the same `read()` you learn today.

## 2.2 pipe() — a one-way kernel byte channel
`pipe(fd)` fills `fd[2]`: **`fd[0]` = read end, `fd[1]` = write end** (mnemonic: like stdin 0 / stdout 1). Bytes written to `fd[1]` come out of `fd[0]`, FIFO order, through a kernel ring buffer. Unidirectional: one pipe = one direction; two-way needs two pipes.

## 2.3 fork shares the pipe
fds are inherited across fork — that's the whole trick. Create the pipe *first*, then fork: now both processes hold both ends, and each closes the end it doesn't use, leaving a clean one-way channel: parent writes → child reads.

## 2.4 The close discipline (where everyone's first pipe program hangs)
A reader gets **EOF (read returns 0) only when ALL write ends in ALL processes are closed**. If the child forgets to close its inherited, unused `fd[1]`, then even after the parent closes its write end the kernel sees "a writer still exists" — the child's own! — and `read` blocks forever. Your program hangs, no error, no crash. Rule: **immediately after fork, every process closes every pipe end it will not use.**

## 2.5 Blocking & short reads/writes
`read(fd, buf, 14)` returns *up to* 14 bytes — it may return 5 if that's what's in the pipe right now (a **short read**; same for writes into a full pipe). Robust code loops until it has the full record. This isn't pedantry: short reads are rare on a lightly-loaded desktop and *constant* on a busy embedded system or serial link — the classic "works on my machine, fails on the device" bug. We build `read_full()` to handle it permanently.

## 2.6 Framing over a byte stream
A pipe (like UART, like TCP) carries **bytes, not messages** — boundaries are your job. We already solved this in Topic 3: fixed-size frames with magic + checksum. Watch the topics interlock: ring buffer (1) → frame codec (3) → processes (5) → and now bytes-between-processes (6). This *is* the TCU architecture.

---

# Part 3 — How the code meets each concept

| Concept | Where in the code | Proof |
|---|---|---|
| fd inheritance via fork | pipe() before fork() | both processes use the same channel |
| close discipline | the four close() calls | ladder 2: remove one → program hangs forever |
| EOF = all writers closed | parent's close(fd[1]) ends child's loop | child exits cleanly when parent finishes |
| short reads | `read_full()` loop | ladder 3 sends frames byte-by-byte; still decodes |
| framing over a stream | reuse of frame_encode/decode | corrupt a byte → decode returns −2 across processes |
| pipe = kernel ring buffer | concept + ladder 5 (fill it up) | write blocks when the 64 KB buffer fills |

---

# Part 4 — The code, line by line

Copy `frame.h` / `frame.c` from Topic 3 into this folder (or better: `git mv` nothing — reference via Makefile `../../advanced-c/binary_frames/frame.c`). Reuse, don't rewrite.

### `telemetry_pipe.c`
```c
#include <stdio.h>
#include <stdlib.h>
#include <unistd.h>
#include <sys/wait.h>
#include "frame.h"
```
`<unistd.h>` again — `pipe`, `read`, `write`, `close`, `fork` all live behind it.

```c
static ssize_t read_full(int fd, uint8_t *buf, size_t want)
{
    size_t got = 0;
    while (got < want) {
        ssize_t n = read(fd, buf + got, want - got);
        if (n == 0)  return 0;            /* EOF: no more writers       */
        if (n < 0)   return -1;           /* real error (check errno)   */
        got += (size_t)n;
    }
    return (ssize_t)got;
}
```
- **Why this function exists:** concept 2.5 — `read` may deliver fewer bytes than asked. The loop re-issues the read at offset `buf + got` for the remainder until the frame is complete. Every serious program that reads records from a stream contains this function; you'll reuse it verbatim for the EC200U serial port.
- **Why `ssize_t` (note the extra s):** `read`'s return type — **signed** size, because −1 must be expressible for errors. `size_t` for "how much I want" (never negative), `ssize_t` for "what the syscall returned" (may be −1). Mixing them up triggers exactly the signed/unsigned warnings `-Wextra` exists to catch.
- **Why three outcomes, in this order:** `0` = clean EOF (writers gone — normal shutdown path), `<0` = real error, positive = progress. Distinguishing "no more data ever" from "error" from "partial" is the entire skill of stream programming.
- **`buf + got`** — pointer arithmetic from Topic 4 earning its keep: "write the next bytes *after* what I already have."

```c
int main(void)
{
    int fd[2];
    if (pipe(fd) < 0) { perror("pipe"); return 1; }
```
- **Why `int fd[2]`:** the API fills both slots — `fd[0]` read, `fd[1]` write. The array is the documentation; learn the 0/1 mnemonic (stdin/stdout).
- **Pipe BEFORE fork** — otherwise the two processes hold two *unrelated* pipes. Order is everything here.

```c
    pid_t pid = fork();
    if (pid < 0) { perror("fork"); return 1; }

    if (pid == 0) {
        /* ===== CHILD: consumer (the "uploader") ===== */
        close(fd[1]);                     /* close unused WRITE end - or hang forever */
```
- **The most important line in the file.** Concept 2.4: while the child holds `fd[1]`, EOF can never arrive — *its own* write end counts as "a writer exists," even though it never writes. Close it first thing. (Ladder 2 makes you experience the hang so you never forget.)

```c
        uint8_t buf[FRAME_WIRE_SIZE];
        frame_t f;
        while (read_full(fd[0], buf, sizeof buf) == (ssize_t)sizeof buf) {
            if (frame_decode(buf, sizeof buf, &f) == 0)
                printf("uploader: id=%08X uptime=%u mv=%u\n",
                       f.device_id, f.uptime_ticks, f.battery_mv);
            else
                fprintf(stderr, "uploader: bad frame, dropped\n");
        }
        close(fd[0]);
        _exit(0);
    }
```
- **The consumer loop shape:** read exactly one wire-frame; loop ends when `read_full` returns 0 (EOF — parent closed its write end). Decode failures are *reported and dropped*, never trusted — your Topic 3 "reject loudly" rule, now across a process boundary.
- **Why `fprintf(stderr, ...)` for the error:** data goes to stdout, diagnostics to stderr — so `./telemetry_pipe > data.log` still shows errors on the terminal. fd discipline again: 1 vs 2.
- **Why `(ssize_t)sizeof buf` cast:** `sizeof` yields unsigned `size_t`; comparing against signed `ssize_t` draws a -Wextra warning. The cast states intent. Small, but it's why your builds are warning-free.
- **`_exit(0)` in the child** — Topic 5's rule, same reason.

```c
    /* ===== PARENT: producer (the "modem manager") ===== */
    close(fd[0]);                         /* close unused READ end */

    for (uint32_t i = 0; i < 3; i++) {
        frame_t f = { .msg_type = 1, .device_id = 0xDEADBEEF,
                      .uptime_ticks = i * 1000u, .battery_mv = 3850u - i };
        uint8_t wire[FRAME_WIRE_SIZE];
        size_t n = frame_encode(&f, wire, sizeof wire);
        if (write(fd[1], wire, n) != (ssize_t)n) { perror("write"); break; }
    }
```
- **Designated initializers** (`.msg_type = 1`) — fields named at init; unmentioned fields (`.flags`) become 0. Order-independent and self-documenting; this is also exactly how kernel driver structs are initialized (`.open = my_open, .read = my_read` — Phase 4 preview).
- **Why check `write`'s return:** writes can be short or fail (reader died → `SIGPIPE`/`EPIPE`). Production code checks; we at least `perror` and stop.

```c
    close(fd[1]);                         /* THE signal: "no more data" -> child sees EOF */
    wait(NULL);                           /* reap - no zombie (Topic 5) */
    return 0;
}
```
- **`close(fd[1])` is not cleanup — it's a message.** This close is what makes the child's `read_full` return 0 and its loop end. In pipe programs, close *is* the shutdown protocol.
- **`wait(NULL)`** — NULL because we don't need the status this time; we just refuse to leave a zombie. Topic 5 habits, permanent now.

`Makefile`:
```make
CC = gcc
CFLAGS = -g -Og -Wall -Wextra -I../../advanced-c/binary_frames

telemetry_pipe: telemetry_pipe.c ../../advanced-c/binary_frames/frame.c
	$(CC) $(CFLAGS) $^ -o $@
```
- **`-I<dir>`** adds a header search path — how multi-module projects find each other's headers. **`$^`** = all prerequisites, **`$@`** = the target: your first real Make automatic variables; Yocto recipes generate Makefiles full of these.

---

# Part 5 — Construct cheat sheet (new this topic)

| Construct | Why |
|---|---|
| `int fd[2]` + `pipe(fd)` | fd[0]=read, fd[1]=write (stdin/stdout mnemonic) |
| pipe before fork | inheritance is what connects the processes |
| close-what-you-don't-use | unclosed write end = reader never sees EOF = silent hang |
| `read` returning 0 / −1 / short | EOF / error / partial — the three stream outcomes |
| `read_full` loop | the permanent fix for short reads; reused for UART later |
| `ssize_t` vs `size_t` | syscall returns are signed (−1); sizes are unsigned |
| `fprintf(stderr, ...)` | diagnostics on fd 2, data on fd 1 |
| close as shutdown signal | EOF is *delivered* by closing write ends |
| designated initializers | named, order-free struct init; kernel style |
| `-I`, `$^`, `$@` in Make | header paths + automatic variables |

---

# Part 6 — Study flow (~2 hours)

1. **(20 min)** Parts 1–2. Sketch the fd diagram: two processes, four pipe-end boxes, cross out the two that get closed.
2. **(40 min)** Type the code, whys aloud, build, run. You should see three decoded frames and a clean exit.
3. **(40 min)** Ladder:
   a. Print `getpid()` in both roles — confirm who's who.
   b. **The hang:** comment out the child's `close(fd[1])`. Run. It prints 3 frames then freezes forever. Feel it, `Ctrl-C` it, explain it, restore it. This is the lesson of the topic.
   c. **Short-read proof:** change the parent to `write` the frame **one byte at a time** with `usleep(1000)` between bytes. `read_full` still assembles perfect frames. Now replace `read_full` with a bare `read` — watch decoding shatter.
   d. Corrupt one byte of one frame before writing (`wire[5] ^= 0xFF`) → child reports "bad frame, dropped" and *keeps going*. Resilience across a process boundary.
   e. **Stretch — build the shell `|`:** in your Topic-5 mini-shell, support `cmd1 | cmd2` using pipe + two forks + `dup2(fd[1], 1)` / `dup2(fd[0], 0)`. (`dup2` clones a pipe end *onto* stdout/stdin — suddenly the shell's magic is just fd surgery.)
4. **(20 min)** Interview probes:
   - Why must every process close unused pipe ends? What exactly goes wrong?
   - What does `read` returning 0 mean, and when does it happen?
   - What's a short read, when do they bite, and what's the fix?
   - One pipe, two directions — possible? What do you do instead?
   - How does `ls | grep` work, syscall by syscall?

**Done =** pipeline runs · you've experienced the hang AND fixed it · probes out loud → one line + confidence /5 to Claude.
*Forward link: swap the pipe's fd for `/dev/ttyUSB0` and `read_full` is reading your EC200U. Same calls. That's the payoff of fd uniformity — and the next stop after this is the boot-flow phase on the Radxa.*
