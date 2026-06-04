# Week-1 Makefile. The inspection targets ARE the lesson — run them, read the
# output, and write what you see into ../LOG.md.

CC      := gcc
CFLAGS  := -std=c11 -Wall -Wextra -g -O0
SRC     := ringbuf.c test_ringbuf.c
BIN     := test_ringbuf

.PHONY: all run clean asm asm-opt obj readelf nm size layout help

all: $(BIN)                       ## build the test binary (-O0, with -g)

$(BIN): $(SRC) ringbuf.h
	$(CC) $(CFLAGS) $(SRC) -o $@

run: all                          ## build then run the tests
	./$(BIN)

# ---- inspection targets (binutils) --------------------------------------

asm: ringbuf.c ringbuf.h          ## emit human-readable assembly at -O0
	$(CC) $(CFLAGS) -S -fverbose-asm ringbuf.c -o ringbuf.s
	@echo ">>> wrote ringbuf.s — read how put/get compile with NO optimization"

asm-opt: ringbuf.c ringbuf.h      ## same at -O2 — diff against ringbuf.s to see the optimizer work
	$(CC) -std=c11 -O2 -S -fverbose-asm ringbuf.c -o ringbuf.opt.s
	@echo ">>> wrote ringbuf.opt.s — compare: vimdiff ringbuf.s ringbuf.opt.s"

obj: $(BIN)                       ## disassemble with interleaved source
	objdump -d -S $(BIN) | less

readelf: $(BIN)                   ## ELF header + section headers + symbols
	@echo "=== ELF header ==="    ; readelf -h $(BIN)
	@echo "=== Section headers ===" ; readelf -S $(BIN)
	@echo "=== Symbol table ==="   ; readelf -s $(BIN) | grep -Ei 'rb_|is_pow2|main'

nm: $(BIN)                        ## symbols: 'T'=global text, 't'=static(local) text
	@echo "Look: is_pow2 should be lowercase 't' (static); rb_* uppercase 'T'."
	nm $(BIN) | grep -Ei 'rb_|is_pow2|main'

size: $(BIN)                      ## .text/.data/.bss sizes (footprint matters in embedded)
	size $(BIN)

layout: layout.c ringbuf.h        ## build & run layout.c — see sizeof/offsets/padding
	$(CC) $(CFLAGS) layout.c -o layout_probe && ./layout_probe
	@echo ">>> Edit layout.c (or reorder fields in ringbuf.h) and re-run. When does sizeof change?"

clean:                            ## remove build artifacts (keeps your .c/.h sources)
	rm -f $(BIN) ringbuf.s ringbuf.opt.s layout_probe

help:                             ## list targets
	@grep -E '^[a-z-]+:.*##' $(MAKEFILE_LIST) | sed 's/:.*##/\t/'
