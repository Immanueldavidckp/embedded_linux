#!/usr/bin/env python3
"""Re-derive the pin tables in ../data from public reference documents.

    ref/rock4d.pdf  Radxa ROCK 4D schematic V1.11
                    https://dl.radxa.com/rock4/4d/docs/hw/Radxa_ROCK_4D_SCH_V1.11.pdf
    ref/emmc.pdf    Alliance Memory ASFC8G31M-51BIN eMMC datasheet (JEDEC 153b ballout)

Usage: python3 extract_ref_pins.py <ref_dir>
(The RK3576 table comes from parse_rk3576_pins.py.)
"""
import os, re, subprocess, sys

HERE = os.path.dirname(os.path.abspath(__file__))
DATA = os.path.join(HERE, '..', 'data')


def pdftext(pdf, page=None, raw=True):
    cmd = ['pdftotext'] + (['-raw'] if raw else ['-layout'])
    if page:
        cmd += ['-f', str(page), '-l', str(page)]
    return subprocess.run(cmd + [pdf, '-'], capture_output=True, text=True).stdout


def write(name, rows):
    with open(os.path.join(DATA, name), 'w') as f:
        f.write('ball,name\n' + ''.join(f'{b},{n}\n' for b, n in rows))
    print(f'{name}: {len(rows)} pins')


def rk806(ref):
    """Page 25 (PMIC). In raw text order each pin is 'NAME' then 'NUMBER'."""
    L = [l.strip() for l in pdftext(os.path.join(ref, 'rock4d.pdf'), 25).splitlines()]
    i = L.index('U7A')
    pins = {}
    for a, b in zip(L[i:], L[i + 1:]):
        if re.fullmatch(r'[A-Z][A-Z0-9_]*', a) and re.fullmatch(r'\d{1,2}', b):
            pins.setdefault(int(b), a)
    # Multi-function pins print their alternate name in brackets; the plain
    # regex above skips them, so they are listed explicitly (same page).
    pins.update({15: 'SDA', 16: 'PWRCTRL3', 17: 'SCL', 18: 'CS', 39: 'EXT_EN', 69: 'EPAD'})
    write('rk806_pins.csv', sorted(pins.items()))


def lpddr5(ref):
    """Page 15 (LPDDR5 315b). Raw text gives 'BALL NAME' pairs per unit."""
    T = pdftext(os.path.join(ref, 'rock4d.pdf'), 15).split()
    pins = {}
    for unit in ('U3900A', 'U3900B'):
        i = T.index(unit) + 1
        if T[i].startswith('K3LK'):
            i += 1
        while i < len(T) - 1:
            b, n = T[i], T[i + 1]
            if (re.fullmatch(r'[A-Z]{1,2}\d{1,2}', b) and re.fullmatch(r'[A-Z][A-Z0-9_*]*', n)
                    and not re.fullmatch(r'[A-Z]{1,2}\d{1,2}', n) and b not in pins):
                pins[b] = n
                i += 2
            else:
                break
    write('lpddr5_315b_pins.csv', pins.items())


def emmc(ref):
    """Ball-assignment grid (layout text) -> nearest column header."""
    lines = pdftext(os.path.join(ref, 'emmc.pdf'), raw=False).splitlines()
    i = [k for k, l in enumerate(lines) if 'Figure 2. eMMC Package Ball Assignment' in l][-1]
    hdr = next(l for l in lines[i + 1:] if l.strip().startswith('1      2'))
    centers = [((m.start() + m.end()) / 2, int(m.group())) for m in re.finditer(r'\d+', hdr)]
    out = []
    for l in lines[i + 2:i + 60]:
        m = re.match(r'\s*([A-P])\s', l)
        if not m:
            continue
        for t in re.finditer(r'\S+', l[m.end():]):
            if t.group() == m.group(1):
                continue
            c = m.end() + (t.start() + t.end()) / 2
            out.append((f'{m.group(1)}{min(centers, key=lambda x: abs(x[0] - c))[1]}', t.group()))
    write('emmc_153b_pins.csv', out)


if __name__ == '__main__':
    ref = sys.argv[1] if len(sys.argv) > 1 else 'ref'
    rk806(ref)
    lpddr5(ref)
    emmc(ref)
