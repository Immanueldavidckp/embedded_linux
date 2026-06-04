CC      = gcc
CFLAGS  = -g -Og -Wall -Wextra

at_test: main.c at_parser.c at_parser.h
	$(CC) $(CFLAGS) main.c at_parser.c -o $@

clean:
	rm -f at_test
.PHONY: clean
