# Learning Plan — Pointers Deep-Dive (Advanced C · Topic 4)
**Code target:** `~/embedded-linux/advanced-c/pointers/` · **Artifact:** a linked-list device registry

---

# Part 1 — WHY we are learning this

You already *use* pointers. This topic makes you someone who *thinks* in them — because everything ahead demands it:

- **The Linux kernel is pointer code.** Every driver you write in Phase 4 manipulates linked lists (`struct list_head` is woven through the entire kernel), passes structs by pointer, and registers callbacks through pointer tables. You cannot read kernel source without pointer fluency.
- **Double pointers (`**`) are the kernel's daily bread** — functions that must modify the *caller's pointer* (allocate something and hand it back, unlink a node from a list).
- **Ownership bugs are the #1 C defect class:** leaks, use-after-free, double-free. In a TCU that runs for months, a 16-byte leak per modem reconnect kills the device in the field.
- **Interviews:** "remove a node from a linked list using a double pointer" is a literal FAANG/embedded screening question — and our artifact is exactly that, in its most elegant known form.

**Goal:** read and write `*`, `**`, `&`, `->` chains as fluently as arithmetic, and *know who owns every byte*.

---

# Part 2 — The concepts, before any code

## 2.1 A pointer is an address PLUS a type
`uint32_t *p` is not "an address" — it's "an address *that I will interpret as 4 bytes of unsigned int*". The type controls: how much memory a dereference touches, and how far `p + 1` jumps (4 bytes here, 1 for `uint8_t *`). Pointer arithmetic is **typed** arithmetic — that's why `get_u32(&buf[2])` in Topic 3 worked.

## 2.2 `&` and `*` are inverses
`&x` = "the address of x". `*p` = "the thing at p". `*&x == x`. The declaration mirrors the use: `int *p` reads "*p is an int".

## 2.3 Double pointers: modifying the caller's pointer
A function receiving `device_t *head` gets a **copy** of the pointer — reassigning it changes nothing for the caller. To change *where the caller's pointer points* (e.g., insert at list head), you pass the pointer's address: `device_t **head`. Rule: **n levels of `*` in the parameter = the function can modify n−1 levels of the caller's data.**

## 2.4 Ownership and lifetime
Every allocated byte has exactly one owner — the code responsible for freeing it. Stack memory dies at `}`; returning its address = instant bug. `malloc` memory lives until `free` — and using it after = **use-after-free**, the nastiest C bug because it often *works* for weeks. Discipline: document ownership in the API ("caller must free", "registry owns nodes"), and NULL pointers after freeing.

## 2.5 Self-referential structs
A list node contains a pointer to the next node — the struct refers to its own type *before the typedef exists*. That's why the struct **tag** is required: `struct device *next;` inside `typedef struct device {...} device_t;`.

## 2.6 The walk patterns
Two ways to traverse a list: pointer-walk (`for (d = head; d; d = d->next)`) for reading, and **pointer-to-pointer walk** (`for (pp = &head; *pp; pp = &(*pp)->next)`) for modifying — the second eliminates all "special case for the first node" code. Linus Torvalds famously uses exactly this as his example of "good taste" in C.

---

# Part 3 — How the code meets each concept

| Concept | Where in the code | Proof |
|---|---|---|
| Typed pointers / `->` | every `(*pp)->id`, `d->next` | dereference + member in one step |
| Double pointer modifies caller | `reg_add(device_t **head, ...)` | caller's `head` changes from NULL to first node |
| The `**` walk (no special cases) | `reg_remove` | removing the FIRST node needs no special branch |
| Ownership | `reg_add` mallocs, `reg_free` frees, header comments | valgrind: 0 leaks |
| Self-reference needs struct tag | `struct device *next;` | rename the tag → compile error shows why |
| Dangling-pointer hygiene | `reg_free` sets `*head = NULL` | caller's pointer can't dangle |

---

# Part 4 — The code, line by line

### `registry.h`
```c
#ifndef REGISTRY_H
#define REGISTRY_H

#include <stdint.h>
```
Header guard + fixed-width types — same reasoning as Topic 3 (see that plan; from now on repeated constructs are only re-explained when something is new).

```c
typedef struct device {
    uint32_t id;
    char     name[16];
    struct device *next;
} device_t;
```
- **Why `struct device` tag AND `typedef`:** inside the braces, `device_t` doesn't exist yet — the typedef completes only at the semicolon. A self-referential member therefore *must* use the tag form `struct device *`. This is the one place the tag is mandatory; everywhere else we enjoy the short `device_t`.
- **Why `char name[16]` (array, not `char *name`):** the node **owns** its name — copied in, dies with the node. A `char *` would store a pointer to memory someone else owns; if the caller's string was on the stack, it dangles the moment they return. Embedding the array buys simple, total ownership at the cost of a fixed 15-char limit. This array-vs-pointer ownership decision is a constant theme in embedded design.
- **Why `next` is a pointer, not a struct:** a struct physically containing itself would be infinitely large. A pointer (fixed 8 bytes) breaks the recursion — lists, trees, every linked structure exists because of this.

```c
int       reg_add(device_t **head, uint32_t id, const char *name);
device_t *reg_find(device_t *head, uint32_t id);
int       reg_remove(device_t **head, uint32_t id);
void      reg_free(device_t **head);
```
- **Why `**head` in add/remove/free but `*head` in find:** find only *reads* the list — a copy of the head pointer suffices. The other three may *change which node is first* (insert at head, remove the head, empty the list) — they must reach back into the caller's variable, so they take its address. The asterisk count in the signature literally announces intent: `*` = I read your list, `**` = I may restructure it.
- **Why find returns `device_t *` and not a copy:** returning the node lets the caller read *and modify* the live entry, for free. Returning by value would copy 32 bytes and disconnect the caller from the list. Convention: return pointer = "borrowed reference, registry still owns it; don't free it."
- **Why `const char *name`:** we only read the caller's string — and this permits string literals (`reg_add(&head, 1, "ec200u")`), which are unwritable.

### `registry.c`
```c
#include "registry.h"
#include <stdlib.h>
#include <string.h>

int reg_add(device_t **head, uint32_t id, const char *name)
{
    device_t *d = malloc(sizeof *d);
    if (!d) return -1;
```
- **Why `sizeof *d` and not `sizeof(device_t)`:** it stays correct if the type ever changes — the expression derives the size from the variable itself. Idiomatic, kernel-style.
- **Why check malloc:** on a small system allocation *will* eventually fail; an unchecked NULL malloc dereference is a crash you chose. `if (!d)` reads "if d is NULL" — pointers are falsy when NULL.

```c
    d->id = id;
    strncpy(d->name, name, sizeof d->name - 1);
    d->name[sizeof d->name - 1] = '\0';
```
- **Why `strncpy` + manual terminator:** plain `strcpy` overflows if `name` ≥ 16 chars (buffer overflow, the classic CVE). `strncpy` bounds the copy BUT has a famous trap — it does **not** null-terminate when the source fills the buffer. The explicit `'\0'` on the last byte closes that hole. Being able to recite *why strncpy alone is insufficient* is an interview checkbox.

```c
    d->next = *head;
    *head = d;
    return 0;
}
```
- **Insert-at-head in two lines:** new node points at the current first node; then the caller's head (reached through `*head`) points at the new node. Order matters — swap the lines and you orphan the whole list. Draw this once with boxes and arrows; it's the foundational list operation.

```c
device_t *reg_find(device_t *head, uint32_t id)
{
    for (device_t *d = head; d; d = d->next)
        if (d->id == id)
            return d;
    return NULL;
}
```
- **The canonical pointer-walk:** init at head; `d` as the condition means "while not NULL" (idiomatic — NULL terminates every proper list); advance by following `next`. Returning NULL for "not found" works because no valid node can be NULL.

```c
int reg_remove(device_t **head, uint32_t id)
{
    device_t **pp = head;

    while (*pp && (*pp)->id != id)
        pp = &(*pp)->next;

    if (!*pp) return -1;

    device_t *victim = *pp;
    *pp = victim->next;
    free(victim);
    return 0;
}
```
**The crown jewel — read it slowly.** `pp` never points at a *node*; it points at a **pointer-slot**: first the caller's `head` variable, then node 1's `next` field, then node 2's `next`… Whichever slot currently points at the victim, `*pp = victim->next` rewrites *that slot* to skip it.
- **Why this is beautiful:** the naive version needs `prev` bookkeeping plus a special branch for "victim is the first node". Here, the head variable and a `next` field are treated identically — both are just `device_t *` slots — so **there is no special case**. This exact function is Torvalds' "good taste in code" example. Own it; tell the story in interviews.
- `&(*pp)->next` parses as `&((*pp)->next)`: "the address of the next-field inside the node this slot points to." Precedence: `->` binds before `&`.
- **Why save `victim` before relinking:** after `*pp = victim->next`, the slot no longer leads to the node — without the saved copy you'd have leaked it (no pointer left = no way to free).

```c
void reg_free(device_t **head)
{
    device_t *d = *head;
    while (d) {
        device_t *next = d->next;   /* save BEFORE freeing */
        free(d);
        d = next;
    }
    *head = NULL;
}
```
- **Why save `next` first:** touching `d->next` *after* `free(d)` is use-after-free — it often "works" (the heap rarely reuses the block instantly) and then corrupts something weeks later. This save-then-free shape is THE pattern for destroying linked structures.
- **Why `**head` here and the final `*head = NULL`:** the function leaves the caller's own pointer NULL — the caller physically cannot use the dead list afterwards. Defensive API design: make the wrong thing impossible.
- **Why `void` return:** destruction cannot meaningfully fail; nothing to report.

### `main.c` (test)
```c
#include <stdio.h>
#include <assert.h>
#include "registry.h"

int main(void)
{
    device_t *head = NULL;              /* an empty list IS a NULL head */

    assert(reg_add(&head, 1, "ec200u-modem") == 0);
    assert(reg_add(&head, 2, "pico-sensor") == 0);
    assert(reg_add(&head, 3, "gps") == 0);          /* list: 3 -> 2 -> 1 */

    assert(reg_find(head, 2) && reg_find(head, 2)->id == 2);
    assert(reg_find(head, 99) == NULL);

    assert(reg_remove(&head, 3) == 0);  /* removes the HEAD - no special case! */
    assert(reg_remove(&head, 1) == 0);  /* removes the TAIL */
    assert(reg_remove(&head, 7) == -1); /* not found */
    assert(head && head->id == 2);      /* only node 2 remains */

    reg_free(&head);
    assert(head == NULL);               /* free left us safe */
    printf("ALL TESTS PASSED\n");
    return 0;
}
```
- **Why `head` starts as NULL:** the empty list isn't a special object — it's simply a NULL head pointer. Every function above already handles it correctly with zero extra code (check each one and convince yourself).
- **Why `&head` at call sites:** that's the caller handing over *the address of its own pointer variable* — the thing `**` parameters exist to receive.

`Makefile`: same as previous topics (`-g -Og -Wall -Wextra`).

---

# Part 5 — Construct cheat sheet (new ones this topic)

| Construct | Why |
|---|---|
| `struct device *next` inside its own struct | typedef isn't complete yet; tag form required for self-reference |
| `char name[16]` vs `char *name` | array = node owns the bytes; pointer = borrowed, dangles if owner dies |
| `device_t **` parameter | function may rewrite the caller's pointer (insert/remove/destroy) |
| `sizeof *d` | size derived from the variable; survives type renames |
| `if (!d)` | NULL test, idiomatic |
| `strncpy` + manual `'\0'` | bounded copy; strncpy alone doesn't guarantee termination |
| `&(*pp)->next` | address of a node's next-slot; `->` binds before `&` |
| save-then-free loop | touching freed memory = use-after-free |
| `*head = NULL` after destroy | caller can't dangle; make misuse impossible |

---

# Part 6 — Study flow (~2 hours)

1. **(15 min)** Parts 1–2. Draw three boxes (nodes) and arrows on paper. Physically trace `reg_remove` of the middle node — move your pen along `pp`.
2. **(45 min)** Type the code with Part 4 beside you, saying each "why" aloud. Build, run.
3. **(20 min)** **valgrind proof:** `valgrind --leak-check=full ./registry_test` → "0 bytes lost". Then delete the `reg_free` call, rerun, and *read the leak report* — learn what a leak looks like before one finds you.
4. **(30 min)** Ladder:
   a. Comment out `*pp = victim->next` — predict, run, draw what broke.
   b. Make a use-after-free on purpose (free, then read `d->id`), catch it with valgrind.
   c. Write `reg_count(device_t *head)` and `reg_print` yourself, no reference.
   d. Rewrite `reg_remove` the "naive way" (with `prev` and a head special-case). Compare line counts. Feel the taste difference.
5. **(10 min)** Interview probes:
   - Why `**` in remove but `*` in find?
   - Remove the first node of a list with no special case — how?
   - What's wrong with returning a pointer to a local variable?
   - strncpy's trap?
   - Who owns the node returned by `reg_find`, and may the caller free it?

**Done =** tests pass · valgrind clean · ladder a–d · probes out loud → one line + confidence /5 to Claude.
*Forward link: the kernel's `list_head` (Phase 3) is this exact structure, made generic with macros — you'll recognize it on sight now.*
