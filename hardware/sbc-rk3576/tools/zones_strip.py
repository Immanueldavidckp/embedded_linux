#!/usr/bin/env python3
"""Remove zones by name prefix from a .kicad_pcb as text (s-expression level).

KiCad 9's Python API leaves dangling SWIG objects after BOARD.Remove(zone), so
later iteration (footprints, pads, reload) crashes. Editing the file before it is
loaded avoids touching that code path at all."""
import re, sys


def strip(src, dst, prefixes=('PWR_',)):
    txt = open(src).read()
    out, i, n = [], 0, 0
    for m in re.finditer(r'\n\t\(zone\b', txt):
        if m.start() < i:
            continue
        # find matching close paren of this top-level (zone ...)
        depth, j = 0, m.start() + 1
        while True:
            c = txt[j]
            if c == '(':
                depth += 1
            elif c == ')':
                depth -= 1
                if depth == 0:
                    break
            elif c == '"':
                j = txt.index('"', j + 1)
            j += 1
        block = txt[m.start():j + 1]
        name = re.search(r'\(name "([^"]*)"\)', block)
        if name and name.group(1).startswith(prefixes):
            out.append(txt[i:m.start()])
            i = j + 1
            n += 1
    out.append(txt[i:])
    open(dst, 'w').write(''.join(out))
    return n


if __name__ == '__main__':
    print(strip(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else sys.argv[1]), 'zones removed')
