# Learning Plan — Linux Processes: fork / exec / wait (Topic 5 · start of the Linux phase)
**Code target:** `~/embedded-linux/linux-process-ipc/mini_shell/` · **Artifact:** a working mini-shell

---

# Part 1 — WHY we are learning this

This is the topic where you stop being "a C programmer on Linux" and start being "a Linux systems programmer." Every single thing in your roadmap from here forward stands on the process model:

- **Boot (Phase 2):** the kernel's last act is starting **PID 1** (`init`/systemd) — which then `fork`+`exec`s *every other process on the system*. Your BusyBox rootfs boots to a shell precisely this way. If you understand fork/exec, you understand what "the system came up" actually means.
- **Your telematics gateway (capstone):** will be several cooperating processes — modem manager, data logger, uploader — started, supervised, and restarted-on-crash by exactly these calls.
- **Daily debugging:** `ps`, zombie processes, orphans, exit codes — you can't read a production incident without this model.
- **Interviews:** "what does fork return?", "why do we need exec?", "what's a zombie?" are *guaranteed* embedded-Linux screening questions.

**Goal:** own the lifecycle — one process becomes two (`fork`), a process becomes a different program (`exec`), a parent collects the result (`wait`) — well enough to build a shell, because a shell is nothing but this loop.

---

# Part 2 — The concepts, before any code

## 2.1 What a process IS
A process = a private virtual address space (your Topic-3 memory map: text/data/bss/heap/stack) + a kernel bookkeeping entry (PID, open files, credentials, state). Two processes cannot touch each other's memory — that isolation is the MMU's job, and it's exactly what your Pico (no MMU) *cannot* do. This is THE dividing line between RTOS firmware and Linux.

## 2.2 fork() — the call that returns twice
`fork()` clones the calling process: child gets a *copy* of the address space (lazily, via copy-on-write — pages are shared read-only until someone writes). After fork, **two processes are executing the same code at the same line**. They distinguish themselves by the return value: child sees `0`, parent sees the child's PID, error returns `-1`. There is no other difference — same code, two realities.

## 2.3 exec() — same process, new program
The `exec` family **replaces** the current process image: new text/data/heap/stack from the program file, same PID, same open file descriptors (that detail powers shell redirection and Topic 6). On success exec **never returns** — there is nothing to return to; that code is gone. Code after exec only runs when exec *failed*.

## 2.4 Why fork THEN exec (the UNIX two-step)
Why not one "spawn" call? Because the gap *between* fork and exec is where the child customizes itself — redirect stdout, change directory, drop privileges — using ordinary code, before becoming the new program. This composability is the most-praised design decision in UNIX. (`posix_spawn` exists for tiny systems, but fork+exec is the model to master.)

## 2.5 wait() — reaping, zombies, orphans
When a child exits, the kernel keeps a stub (PID + exit status) until the parent calls `wait`/`waitpid` to read it. Until then the child is a **zombie** (`Z` in `ps` — already dead, just unreaped). A parent that never waits leaks PIDs — on an embedded box that runs for a year, that's eventual death. If the *parent* dies first, the child is an **orphan**, adopted and reaped by PID 1. This is why init must exist.

## 2.6 Exit status
A process reports one byte: `exit(0)` = success, non-zero = failure kind. The parent unpacks it from `wait`'s status word with macros (`WIFEXITED`, `WEXITSTATUS`). Your shell's `$?` is exactly this byte. Convention `127` = "command not found" (we honor it below).

---

# Part 3 — How the code meets each concept

| Concept | Where in the code | Proof |
|---|---|---|
| fork returns twice | `pid == 0` vs `pid > 0` branches | both branches run, different processes |
| exec replaces, never returns | `perror` AFTER `execlp` | that line prints only for bad commands |
| fork-then-exec gap | child branch before exec | (ladder: redirect stdout there) |
| wait reaps, exit codes | `waitpid` + `WEXITSTATUS` print | `[exit 0]` vs `[exit 2]` for `ls /nope` |
| zombies are real | ladder exercise 3 | `ps` shows `Z` when wait is removed |
| stdio buffering across fork | `fflush` before fork, `_exit` in child | ladder 4 shows doubled output without them |

---

# Part 4 — The code, line by line

### `mini_shell.c`
```c
#include <stdio.h>
#include <stdlib.h>
#include <string.h>
#include <unistd.h>
#include <sys/wait.h>
```
- **`<unistd.h>`** = the POSIX syscall wrappers (`fork`, `exec*`, `getpid`) — the door from C into the kernel. **`<sys/wait.h>`** = `waitpid` + the `W*` status macros. These two headers ARE systems programming; the first three you know.

```c
int main(void)
{
    char line[128];

    for (;;) {
        printf("mini> ");
        fflush(stdout);
```
- **Why `fflush(stdout)`:** `printf` to a terminal flushes on `\n` — our prompt has none, so without the flush it sits in the stdio buffer and the user stares at nothing. Deeper reason you must learn NOW: **a forked child inherits a copy of unflushed buffers** — flush-before-fork prevents the prompt printing twice. Buffering bugs around fork are a classic rite of passage; we're skipping the painful version.

```c
        if (!fgets(line, sizeof line, stdin))
            break;                          /* EOF (Ctrl-D) -> exit shell */
        line[strcspn(line, "\n")] = '\0';
```
- **Why `fgets`, never `gets`/`scanf("%s")`:** `fgets` takes the buffer size — it *cannot* overflow. `gets` is so dangerous it was removed from the C standard. Returning NULL on end-of-input gives us clean Ctrl-D handling: your shell exits like a real one.
- **The `strcspn` idiom:** `strcspn(line, "\n")` returns the index of the first newline (or the string length if none) — writing `'\0'` there strips the trailing newline `fgets` keeps. One line, no `if`, handles both cases. Memorize it.

```c
        if (line[0] == '\0') continue;          /* empty line: re-prompt   */
        if (strcmp(line, "exit") == 0) break;   /* built-in, NOT a program */
```
- **Why `exit` must be a built-in:** a child process can't make its *parent* quit — `exec`ing some `/bin/exit` would exit only the child. Real shells have built-ins (`cd` is the famous one — ladder exercise) for exactly this reason: some actions must happen *in the shell's own process*.

```c
        pid_t pid = fork();
        if (pid < 0) { perror("fork"); continue; }
```
- **`pid_t`** — the POSIX type for PIDs (don't assume `int`; same fixed-width philosophy as Topic 3).
- **`perror("fork")`** — the kernel reports *why* a syscall failed in the global `errno`; `perror` prints your label + the human translation ("Resource temporarily unavailable"). Syscall fails → `perror`/`strerror` immediately — make it a reflex; silent failure handling is how field bugs become unfindable.

```c
        if (pid == 0) {
            /* ===== CHILD - same code, new reality ===== */
            execlp(line, line, (char *)NULL);
            perror(line);
            _exit(127);
        }
```
- **`pid == 0` = "I am the child."** From this line, two processes run this same source file. Everything in this block executes only in the clone.
- **`execlp(file, arg0, ..., NULL)`:** `l` = args passed as an explicit *list*; `p` = search `$PATH` (so `ls` works without typing `/bin/ls`). First argument = program to run; second = `argv[0]`, the name the program sees for itself — by convention the same string.
- **Why the `(char *)NULL` cast — a real trap:** `execlp` is variadic, so the compiler cannot convert the terminator for you. A bare `0` may be passed as an `int` (4 bytes) where an 8-byte null pointer is expected → undefined behavior on 64-bit. The cast makes it an honest null pointer. (Same trap class as Topic 3's integer-promotion cast — variadic functions don't know their argument types. `printf` has the identical issue.)
- **Why `perror` *after* exec:** on success exec never returns — this line is unreachable. Reached = exec failed (typo'd command). Printing the command name as the label gives `nosuchcmd: No such file or directory`, just like bash.
- **Why `_exit(127)` and not `exit(127)`:** `exit()` runs atexit handlers and **flushes inherited stdio buffers** — the child could re-print data the parent also prints (the doubled-output bug). `_exit()` terminates immediately, kernel-level, no library cleanup. Rule: **in a forked child that fails to exec, always `_exit`.** And `127` is the shell convention for "command not found" — bash uses it; we speak the same protocol.

```c
        /* ===== PARENT ===== */
        int status;
        if (waitpid(pid, &status, 0) < 0) { perror("waitpid"); continue; }

        if (WIFEXITED(status))
            printf("[exit %d]\n", WEXITSTATUS(status));
        else if (WIFSIGNALED(status))
            printf("[killed by signal %d]\n", WTERMSIG(status));
    }
    return 0;
}
```
- **Why `waitpid(pid, ...)` over plain `wait(...)`:** wait reaps *any* child; waitpid targets *this* one — the habit that survives when your gateway has five children and you must know *which* one died.
- **Why `&status` (out-parameter):** same API shape as Topic 3's `frame_decode` — return value = success/failure of the call itself, result delivered through a pointer. You now recognize this as the standard C idiom, kernel-wide.
- **Why macros, not `status == 0`:** the status int is a *packed bitfield* — exit code in some bits, terminating signal in others. `WIFEXITED` asks "did it exit normally?", `WEXITSTATUS` extracts the code; `WIFSIGNALED`/`WTERMSIG` handle the killed-by-signal case (try `sleep 100` then Ctrl-C… ladder 5). Bit-packed status words should feel familiar — your Topic-3 `flags` byte is the same idea.
- **Blocking semantics:** `waitpid(..., 0)` *sleeps the parent until the child dies* — that's why the prompt returns only after the command finishes. Foreground execution falls out of the API for free.

`Makefile`: usual flags. Run it, then inside your shell try: `ls`, `date`, `nosuchcmd`, `exit`.

---

# Part 5 — Construct cheat sheet (new this topic)

| Construct | Why |
|---|---|
| `pid_t` | POSIX's PID type; never assume int |
| `fork()` return triage `<0 / ==0 / >0` | error / I-am-child / I-am-parent — the canonical three-way |
| `execlp(cmd, cmd, (char*)NULL)` | PATH search; arg list; cast because variadic args don't auto-convert |
| code after exec | reachable only on exec failure |
| `_exit()` in child vs `exit()` | skip stdio flush/atexit double-execution after fork |
| `perror` / `errno` | the kernel's error channel; reflex after every failed syscall |
| `waitpid(pid, &status, 0)` | targeted, blocking reap; status via out-param |
| `WIFEXITED/WEXITSTATUS/...` | unpack the bit-packed status word |
| `fflush` before fork | child inherits unflushed buffers |
| built-ins (`exit`, later `cd`) | actions that must run in the shell's own process |

---

# Part 6 — Study flow (~2 hours)

1. **(20 min)** Parts 1–2. Then watch the fork video from your travel watchlist again — it will land differently now.
2. **(40 min)** Type the shell with Part 4 open, saying the whys. Build. Drive it: `ls`, `date`, `nosuchcmd` (note the 127), Ctrl-D.
3. **(40 min)** Ladder:
   a. Print `getpid()` and `getppid()` in both branches right after fork — *see* the two processes.
   b. Remove `waitpid` entirely; run `ls`; in another terminal `ps -o pid,stat,cmd --ppid <shell-pid>` → meet your first **zombie** (`Z`). Restore.
   c. Remove `fflush` and change `_exit` to `exit`; find an input that prints the prompt twice. Explain it. Restore.
   d. Run `sleep 100`, Ctrl-C it → your `[killed by signal 2]` line fires. Signal 2 = SIGINT.
   e. **Stretch:** add a `cd` built-in (`chdir`) — then explain in one comment why `cd` *cannot* be an external program.
4. **(20 min)** Interview probes, out loud:
   - What does fork return, and to whom? What's copy-on-write?
   - Why fork+exec instead of one spawn call?
   - What exactly is a zombie, who removes it, what if the parent never waits?
   - Why `_exit` in a failed child?
   - Where does `$?` come from?

**Done =** shell works · zombie witnessed with your own eyes · probes answered → one line + confidence /5 to Claude.
*Forward link: Topic 6 wires two of these processes together with a pipe — your shell's `|` is twenty lines away. And when your Radxa boots to BusyBox in Phase 2, you'll know exactly what PID 1 is doing.*
