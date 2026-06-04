/*
 * test_ringbuf.c — tiny assert-based harness. No framework; that's the point.
 * `make run` builds and runs this. All asserts pass once ringbuf.c is done.
 */
#include "ringbuf.h"
#include <assert.h>
#include <stdio.h>

int main(void)
{
    uint8_t storage[8];          /* capacity 8 -> mask 0b111 */
    ringbuf_t rb;

    /* init rejects bad capacities */
    assert(rb_init(&rb, storage, 0) == -1 && "capacity 0 must fail");
    assert(rb_init(&rb, storage, 7) == -1 && "non-power-of-two must fail");
    assert(rb_init(&rb, storage, 8) == 0  && "power-of-two must succeed");

    assert(rb_is_empty(&rb));
    assert(!rb_is_full(&rb));
    assert(rb_count(&rb) == 0);

    /* fill it */
    for (uint8_t i = 0; i < 8; i++)
        assert(rb_put(&rb, (uint8_t)(0xA0 + i)) && "put within capacity");

    assert(rb_is_full(&rb));
    assert(rb_count(&rb) == 8);
    assert(!rb_put(&rb, 0xFF) && "put on full must fail");

    /* drain it, FIFO order */
    for (uint8_t i = 0; i < 8; i++) {
        uint8_t v;
        assert(rb_get(&rb, &v) && "get within count");
        assert(v == (uint8_t)(0xA0 + i) && "FIFO ordering");
    }
    assert(rb_is_empty(&rb));
    uint8_t junk;
    assert(!rb_get(&rb, &junk) && "get on empty must fail");

    /* wrap-around: index must wrap via mask, not overflow the buffer */
    for (int round = 0; round < 100; round++) {
        assert(rb_put(&rb, (uint8_t)round));
        uint8_t v;
        assert(rb_get(&rb, &v));
        assert(v == (uint8_t)round && "wrap preserves value");
    }
    assert(rb_is_empty(&rb));

    printf("All ring buffer tests passed.\n");
    return 0;
}
