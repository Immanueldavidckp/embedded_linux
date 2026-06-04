/*
 * ringbuf.h — byte-oriented single-producer/single-consumer FIFO.
 *
 * Week-1 teaching vehicle. Every design choice here maps to a roadmap topic:
 *   - power-of-2 capacity + bitmask wrap   -> bit manipulation
 *   - struct field order / padding         -> struct alignment (inspect with `make layout`)
 *   - monotonic head/tail counters         -> unsigned wraparound arithmetic
 *   - `volatile` discussion (see .c)       -> what volatile does and does NOT buy you
 *
 * Design: head and tail are *monotonically increasing* counters (they never
 * reset). The physical slot is `index & mask`. This is the classic embedded
 * trick that distinguishes full from empty WITHOUT wasting a slot:
 *      count = head - tail        (unsigned subtraction, wraps cleanly)
 *      empty when head == tail
 *      full  when (head - tail) == capacity
 */
#ifndef RINGBUF_H
#define RINGBUF_H

#include <stddef.h>   /* size_t            */
#include <stdint.h>   /* uint8_t           */
#include <stdbool.h>  /* bool              */

typedef struct ringbuf {
    uint8_t *buf;       /* caller-owned backing storage                       */
    size_t   capacity;  /* number of slots; MUST be a power of two            */
    size_t   mask;      /* capacity - 1; AND with an index to wrap it         */
    size_t   head;      /* total bytes ever written (producer owns this)      */
    size_t   tail;      /* total bytes ever read    (consumer owns this)      */
} ringbuf_t;

/* Returns 0 on success, -1 if capacity is 0 or not a power of two. */
int    rb_init(ringbuf_t *rb, uint8_t *storage, size_t capacity);

size_t rb_count(const ringbuf_t *rb);   /* bytes currently buffered */
bool   rb_is_empty(const ringbuf_t *rb);
bool   rb_is_full(const ringbuf_t *rb);

/* rb_put: append one byte. Returns true on success, false if full.   */
bool   rb_put(ringbuf_t *rb, uint8_t byte);
/* rb_get: pop one byte into *out. Returns true, or false if empty.   */
bool   rb_get(ringbuf_t *rb, uint8_t *out);

#endif /* RINGBUF_H */
