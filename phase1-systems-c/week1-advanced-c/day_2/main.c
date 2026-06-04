#include <stdio.h>
#include <string.h>
#include <assert.h>
#include "at_parser.h"

static int ok_count, urc_count;

static void my_handler(at_line_type_t type, const char *line)
{
    const char *names[] = { "OK", "ERROR", "URC", "DATA" };
    printf("[%s] %s\n", names[type], line);
    if (type == LINE_OK)  ok_count++;
    if (type == LINE_URC) urc_count++;
}

int main(void)
{
    at_parser_t p;
    at_init(&p, my_handler);            /* registering the callback */

    /* a real EC200U-style exchange, fed ONE BYTE AT A TIME */
    const char *modem = "\r\n+CSQ: 23,0\r\n\r\nOK\r\n+CREG: 0,1\r\nERROR\r\n";
    for (size_t i = 0; i < strlen(modem); i++)
        at_feed(&p, modem[i]);

    assert(ok_count == 1);
    assert(urc_count == 2);             /* +CSQ and +CREG */
    assert(p.dropped == 0u);
    printf("ALL TESTS PASSED\n");
    return 0;
}
