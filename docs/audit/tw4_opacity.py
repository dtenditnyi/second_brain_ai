"""Convert Tailwind v3 `X-color Y-opacity-N` pairs to v4 `X-color/N` inside quoted strings."""
import re, sys
OPA = re.compile(r'^(?P<v>(?:[a-z-]+:)*)(?P<k>bg|border|divide)-opacity-(?P<n>\d+)$')
def is_color(tok, v, k):
    if not tok.startswith(v + k + '-'): return False
    rest = tok[len(v + k) + 1:]
    if '/' in rest or 'opacity' in rest: return False
    return bool(re.match(r'^(\[.+\]|white|black|transparent|current|[a-z]+-\d{2,3})$', rest))
unpaired = []
def fix_string(s):
    toks = re.split(r'(\s+)', s)
    words = [i for i, t in enumerate(toks) if t and not t.isspace()]
    drop = set()
    for wi, i in enumerate(words):
        m = OPA.match(toks[i])
        if not m: continue
        for j in reversed(words[:wi]):
            if j in drop: continue
            if is_color(toks[j], m['v'], m['k']):
                toks[j] = toks[j] + '/' + m['n']; drop.add(i); break
        else:
            unpaired.append(s.strip()[:80])
    out = ''.join('' if i in drop else t for i, t in enumerate(toks))
    return re.sub(r'  +', ' ', out) if drop else s
def process(path):
    text = open(path, encoding='utf-8').read()
    new = re.sub(r'class="([^"]*)"', lambda m: 'class="' + fix_string(m.group(1)) + '"', text)
    if path.endswith('.js'):
        new = re.sub(r"'([^'\n]*-opacity-[^'\n]*)'", lambda m: "'" + fix_string(m.group(1)) + "'", new)
        new = re.sub(r"`([^`]*)`", lambda m: '`' + re.sub(r'class="([^"]*)"', lambda c: 'class="' + fix_string(c.group(1)) + '"', m.group(1)) + '`', new)
    if new != text:
        open(path, 'w', encoding='utf-8', newline='').write(new)
        print('changed', path)
for p in sys.argv[1:]: process(p)
print('UNPAIRED:', *unpaired, sep='\n  ')
