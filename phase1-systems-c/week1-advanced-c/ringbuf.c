/*
 * ringbuf.c — IMPLEMENT ME (Week-1 hands-on).
 *
 * Each function has a TODO. The file compiles and links today (stubs return
 * safe defaults) so `make`, `make obj`, `make readelf` etc. work before you've
 * written a line of logic. Replace each stub, then `make run` until tests pass.
 *
 * volatile note: you may be tempted to mark head/tail `volatile`. Don't — not
 * for thread safety. `volatile` only stops the compiler from caching a value in
 * a register; it gives you NO atomicity and NO memory ordering. For real SPSC
 * across threads/cores you need C11 atomics (stdatomic.h) with acquire/release.
 * `volatile` is for memory-mapped hardware registers, not inter-thread comms.
 * (Good interview answer — write it in your own words in LOG.md once it clicks.)
 */
#include "ringbuf.h"

/*
 * is_pow2 — static: internal linkage, invisible outside this translation unit.
 * Check it after `make nm`: it should NOT appear as a global ('T') symbol.
 * TODO: a number is a power of two iff it is non-zero AND (n & (n-1)) == 0.
 */
static bool is_pow2(size_t n)
{
    /* A power of two has exactly one bit set: 8 = 0b1000.
     * Subtracting 1 flips that bit and sets all lower bits: 7 = 0b0111.
     * AND them -> 0. For any non-power-of-two (e.g. 6=110, 5=101 -> 100) it's
     * non-zero. The n!=0 guard rejects 0, which would sneak through (0&-1==0). */
    return n != 0 && (n & (n - 1)) == 0;
}

int rb_init(ringbuf_t *rb, uint8_t *storage, size_t capacity)
{
    if (!is_pow2(capacity))      /* also rejects 0 */
        return -1;
    rb->buf      = storage;
    rb->capacity = capacity;
    rb->mask     = capacity - 1; /* precompute once; used on every put/get */
    rb->head     = 0;
    rb->tail     = 0;
    return 0;
}

size_t rb_count(const ringbuf_t *rb)
{
    /* Unsigned subtraction. Even if head has wrapped past SIZE_MAX and tail
     * hasn't, modular arithmetic makes (head - tail) the true in-flight count,
     * as long as that count never exceeds capacity (which put/full enforce). */
    return rb->head - rb->tail;
}

bool rb_is_empty(const ringbuf_t *rb)
{
    return rb_count(rb) == 0;
}

bool rb_is_full(const ringbuf_t *rb)
{
    return rb_count(rb) == rb->capacity;
}

bool rb_put(ringbuf_t *rb, uint8_t byte)
{
    if (rb_is_full(rb))
        return false;
    rb->buf[rb->head & rb->mask] = byte;  /* mask wrap: head&mask is always 0..capacity-1 */
    rb->head++;                           /* counter grows forever; the mask handles wrap */
    return true;
}

bool rb_get(ringbuf_t *rb, uint8_t *out)
{
    if (rb_is_empty(rb))
        return false;
    *out = rb->buf[rb->tail & rb->mask];
    rb->tail++;
    return true;
}
