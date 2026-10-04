"""Minimal KiCad s-expression reader/writer.

KiCad files are Lisp-style trees: (token arg arg (child ...)).
We parse into nested Python lists; strings stay `str`, quoted strings are
wrapped in `Q` so they round-trip with their quotes.
"""
import re


class Q(str):
    """A quoted string atom."""


_TOK = re.compile(r'\s*(?:(\()|(\))|"((?:[^"\\]|\\.)*)"|([^\s()"]+))', re.S)


def parse(text):
    stack, cur = [], []
    pos = 0
    n = len(text)
    while pos < n:
        m = _TOK.match(text, pos)
        if not m:
            if text[pos:].strip() == '':
                break
            raise ValueError(f'bad sexp near {text[pos:pos+40]!r}')
        pos = m.end()
        if m.group(1):
            stack.append(cur)
            cur = []
        elif m.group(2):
            done = cur
            cur = stack.pop()
            cur.append(done)
        elif m.group(3) is not None:
            cur.append(Q(m.group(3).replace('\\"', '"').replace('\\\\', '\\')))
        else:
            cur.append(m.group(4))
    return cur[0] if len(cur) == 1 else cur


def _atom(a):
    if isinstance(a, Q):
        return '"' + a.replace('\\', '\\\\').replace('"', '\\"') + '"'
    if isinstance(a, float):
        s = f'{a:.4f}'.rstrip('0').rstrip('.')
        return s if s not in ('-0', '') else '0'
    return str(a)


def dump(node, indent=0):
    """Serialise; short lists stay on one line like KiCad does."""
    if not isinstance(node, list):
        return _atom(node)
    flat = '(' + ' '.join(dump(c) for c in node) + ')'
    if len(flat) <= 100 and '\n' not in flat:
        return flat
    pad = '  ' * (indent + 1)
    head = [dump(c) for c in node if not isinstance(c, list)]
    kids = [c for c in node if isinstance(c, list)]
    s = '(' + ' '.join(head)
    for k in kids:
        s += '\n' + pad + dump(k, indent + 1)
    return s + '\n' + '  ' * indent + ')'


def find(node, key):
    for c in node:
        if isinstance(c, list) and c and c[0] == key:
            return c
    return None


def findall(node, key):
    return [c for c in node if isinstance(c, list) and c and c[0] == key]


# ---------------------------------------------------------------- symbol libs
_lib_cache = {}


def load_lib(path):
    if path not in _lib_cache:
        tree = parse(open(path, encoding='utf-8').read())
        _lib_cache[path] = {s[1]: s for s in findall(tree, 'symbol')}
    return _lib_cache[path]


def flatten_symbol(lib, name):
    """Return a deep-copied symbol with any (extends ...) resolved."""
    import copy
    sym = copy.deepcopy(lib[name])
    ext = find(sym, 'extends')
    if not ext:
        return sym
    parent = flatten_symbol(lib, ext[1])
    sym.remove(ext)
    props = {p[1]: p for p in findall(sym, 'property')}
    out = [sym[0], Q(name)]
    for c in parent[2:]:
        if isinstance(c, list) and c[0] == 'property' and c[1] in props:
            out.append(props.pop(c[1]))
        elif isinstance(c, list) and c[0] == 'symbol':
            c = copy.deepcopy(c)
            c[1] = Q(c[1].replace(ext[1], name, 1))
            out.append(c)
        else:
            out.append(c)
    out.extend(props.values())
    return out


def symbol_pins(sym):
    """[(unit, number, name, x, y, angle, length, etype)] for every pin."""
    pins = []
    for sub in findall(sym, 'symbol'):
        m = re.search(r'_(\d+)_(\d+)$', sub[1])
        unit = int(m.group(1)) if m else 0
        for p in findall(sub, 'pin'):
            at = find(p, 'at')
            ln = find(p, 'length')
            nm = find(p, 'name')
            nb = find(p, 'number')
            pins.append((unit, str(nb[1]), str(nm[1]), float(at[1]), float(at[2]),
                         int(float(at[3])) if len(at) > 3 else 0, float(ln[1]), p[1]))
    return pins


def symbol_units(sym):
    us = set()
    for sub in findall(sym, 'symbol'):
        m = re.search(r'_(\d+)_(\d+)$', sub[1])
        if m and int(m.group(1)) > 0:
            us.add(int(m.group(1)))
    return sorted(us) or [1]
