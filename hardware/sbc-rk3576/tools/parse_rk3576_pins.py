#!/usr/bin/env python3
"""Parse 'Table 2-1 Pin Number Order Information' from the RK3576 datasheet
(pdftotext -layout output) into a CSV: ball,name.

Usage: pdftotext -layout RK3576_Datasheet.pdf ds.txt
       python3 parse_rk3576_pins.py ds.txt > ../data/rk3576_pins.csv
"""
import re, sys, csv

BALL = re.compile(r'^\d?[A-Z]{1,2}\d{1,2}$')

def main(path):
    lines = open(path, encoding='utf-8', errors='replace').read().splitlines()
    # skip the table of contents: the real section heading has no dot leader
    start = next(i for i, l in enumerate(lines)
                 if l.startswith('2.6 Pin Number List') and '....' not in l)
    end = next(i for i, l in enumerate(lines[start:], start) if l.startswith('Chapter 3'))
    pins, cols, last = [], None, [None, None]
    for l in lines[start:end]:
        if l.startswith('Pin Name'):
            # column boundaries: left name | left ball | right name | right ball
            p2 = l.index('Pin Name', 5)
            cols = (l.index('Pin', 9), p2, l.rindex('Pin'))
            continue
        if cols is None or not l.strip() or 'Copyright' in l or 'Datasheet' in l:
            continue
        halves = [l[:cols[1]], l[cols[1]:]]
        for side, h in enumerate(halves):
            toks = h.split()
            if not toks:
                continue
            if len(toks) >= 2 and BALL.match(toks[-1]):
                name = ''.join(toks[:-1])
                pins.append([toks[-1], name])
                last[side] = pins[-1]
            elif last[side] is not None and len(toks) == 1:
                if toks[0].isdigit():
                    last[side][0] += toks[0]      # ball id wrapped (e.g. 1AD2 / 0)
                else:
                    last[side][1] += toks[0]      # wrapped name continuation
    w = csv.writer(sys.stdout)
    w.writerow(['ball', 'name'])
    # Any remaining duplicate is tagged rather than dropped so it stays visible.
    seen = {}
    for b, n in pins:
        if b in seen:
            seen[b] += 1
            b = f'{b}?{seen[b]}'
        else:
            seen[b] = 0
        w.writerow([b, n])
    dup = sum(seen.values())
    print(f'# parsed {len(pins)} pins, {dup} with clipped/duplicate ball ids', file=sys.stderr)

if __name__ == '__main__':
    main(sys.argv[1])
