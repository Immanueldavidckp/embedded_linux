#include "at_parser.h"
#include <string.h>

/* ---- a state handler: takes parser + char, RETURNS the next state ---- */
typedef at_state_t (*state_fn)(at_parser_t *p, char c);

static at_line_type_t classify(const char *line)
{
    if (strcmp(line, "OK") == 0)    return LINE_OK;
    if (strcmp(line, "ERROR") == 0) return LINE_ERROR;
    if (line[0] == '+')             return LINE_URC;
    return LINE_DATA;
}

static void emit_line(at_parser_t *p)
{
    if (p->len == 0u) return;            /* ignore blank lines */
    p->line[p->len] = '\0';
    if (p->on_line)                      /* ALWAYS null-check a callback */
        p->on_line(classify(p->line), p->line);
    p->len = 0u;
}

static at_state_t handle_idle(at_parser_t *p, char c)
{
    if (c == '\r' || c == '\n') return ST_IDLE;   /* skip line endings */
    p->line[p->len++] = c;
    return ST_IN_LINE;
}

static at_state_t handle_in_line(at_parser_t *p, char c)
{
    if (c == '\r') return ST_GOT_CR;
    if (c == '\n') { emit_line(p); return ST_IDLE; }
    if (p->len < AT_LINE_MAX - 1u)
        p->line[p->len++] = c;
    else
        p->dropped++;                    /* full: drop, but COUNT it */
    return ST_IN_LINE;
}

static at_state_t handle_got_cr(at_parser_t *p, char c)
{
    emit_line(p);
    if (c == '\n') return ST_IDLE;
    /* '\r' followed by a normal char: new line already starting */
    p->line[p->len++] = c;
    return ST_IN_LINE;
}

/* ---- the dispatch table: state -> handler. No switch. O(1). ---- */
static const state_fn state_table[NUM_STATES] = {
    [ST_IDLE]    = handle_idle,      /* designated initializers: order-proof */
    [ST_IN_LINE] = handle_in_line,
    [ST_GOT_CR]  = handle_got_cr,
};

void at_init(at_parser_t *p, at_line_cb cb)
{
    p->state = ST_IDLE;
    p->len = 0u;
    p->dropped = 0u;
    p->on_line = cb;
}

void at_feed(at_parser_t *p, char c)
{
    /* the whole engine is ONE line: look up handler, call it, store next state */
    p->state = state_table[p->state](p, c);
}
