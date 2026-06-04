/*
 * layout.c — inspect the memory layout of ringbuf_t.
 *
 * This is a throwaway-but-permanent probe: `make layout` builds and runs it.
 * Use it to SEE struct alignment/padding instead of guessing.
 *
 * Experiment (Week-1 exercise):
 *   1. Run `make layout`, note sizeof and the offsets.
 *   2. In ringbuf.h, add `uint8_t flag;` right after `size_t mask;`.
 *      PREDICT the new sizeof before re-running. (Hint: not +1.)
 *   3. Re-run `make layout`. Were you right? Why the jump?
 *   4. Now move `flag` to the very end of the struct and re-run. Different? Why?
 *   5. Write what you learned in ../LOG.md.
 *
 * offsetof() is in <stddef.h>; it gives a field's byte offset from the start
 * of the struct — exactly what the compiler computes when you write rb->head.
 */
#include "ringbuf.h"
#include <stdio.h>
#include <stddef.h>

int main(void)
{
    printf("sizeof(ringbuf_t) = %zu bytes\n", sizeof(ringbuf_t));
    printf("_Alignof          = %zu bytes\n", _Alignof(ringbuf_t));
    puts("field offsets:");
    printf("  buf      @ %2zu  (size %zu)\n", offsetof(ringbuf_t, buf),      sizeof(((ringbuf_t*)0)->buf));
    printf("  capacity @ %2zu  (size %zu)\n", offsetof(ringbuf_t, capacity), sizeof(((ringbuf_t*)0)->capacity));
    printf("  mask     @ %2zu  (size %zu)\n", offsetof(ringbuf_t, mask),     sizeof(((ringbuf_t*)0)->mask));
    printf("  head     @ %2zu  (size %zu)\n", offsetof(ringbuf_t, head),     sizeof(((ringbuf_t*)0)->head));
    printf("  tail     @ %2zu  (size %zu)\n", offsetof(ringbuf_t, tail),     sizeof(((ringbuf_t*)0)->tail));

    /* sum of field sizes vs sizeof: if sizeof is larger, the gap is PADDING */
    size_t fields = sizeof(((ringbuf_t*)0)->buf) + sizeof(((ringbuf_t*)0)->capacity)
                  + sizeof(((ringbuf_t*)0)->mask) + sizeof(((ringbuf_t*)0)->head)
                  + sizeof(((ringbuf_t*)0)->tail);
    printf("sum of fields     = %zu bytes\n", fields);
    printf("padding           = %zu bytes\n", sizeof(ringbuf_t) - fields);
    return 0;
}
