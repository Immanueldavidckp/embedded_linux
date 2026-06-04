#ifndef AT_PARSER_H
#define AT_PARSER_H

#include <stddef.h>

#define AT_LINE_MAX 64u

typedef enum { ST_IDLE = 0, ST_IN_LINE, ST_GOT_CR, NUM_STATES } at_state_t;
typedef enum { LINE_OK, LINE_ERROR, LINE_URC, LINE_DATA } at_line_type_t;

/* the callback type: "a function taking (type, line), returning void" */
typedef void (*at_line_cb)(at_line_type_t type, const char *line);

typedef struct at_parser {
    at_state_t state;
    char       line[AT_LINE_MAX];
    size_t     len;
    at_line_cb on_line;   /* a function POINTER stored in a struct */
    unsigned   dropped;   /* chars lost to overflow — never lose errors silently */
} at_parser_t;

void at_init(at_parser_t *p, at_line_cb cb);
void at_feed(at_parser_t *p, char c);   /* feed ONE char, e.g. from a UART ISR */

#endif
