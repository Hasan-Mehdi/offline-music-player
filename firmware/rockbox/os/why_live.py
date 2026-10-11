#!/usr/bin/env python3
"""Why is this code still in the firmware? Rebuilds the linker's --gc-sections reachability
from the objects' relocations (section level: -ffunction-sections) and prints, for each
object matching a pattern, the chain of functions from the entry point that keeps it.

  python3 why_live.py <build_dir> [pattern ...]      e.g. apps/gui/ apps/menus/ tree.o
  python3 why_live.py <build_dir> --top 40           biggest live objects with their chains

Approximate (the linker script's KEEPs and the entry point are the roots), but it is the
same rule the linker uses, so a chain it prints is a real reason something is kept.
"""
import collections, os, re, subprocess, sys

OBJDUMP = os.path.expanduser('~/rbdev/bin/mipsel-elf-objdump')
build = sys.argv[1]
args = sys.argv[2:]
top = 0
if '--top' in args:
    i = args.index('--top'); top = int(args[i + 1]); del args[i:i + 2]
patterns = args
mapfile = os.path.join(build, 'rockbox.map')

# --- the link's input files, from the map
files = set()
for line in open(mapfile, errors='replace'):
    m = re.search(r'\s(/\S+?\.(?:o|a))(?:\(([^)]+)\))?\s*$', line)
    if m:
        files.add(m.group(1))

sec_size = {}                     # (obj, sec) -> size
defs = {}                         # global symbol -> (obj, sec)
local = collections.defaultdict(dict)   # obj -> {symbol or section name -> sec}
edges = collections.defaultdict(set)    # (obj, sec) -> {(obj, sec)}
pending = []                      # (src node, symbol name, obj)

def parse(path):
    out = subprocess.run([OBJDUMP, '-h', '-t', '-r', '-w', path], capture_output=True, text=True).stdout
    obj = path
    mode = None
    cur_rel = None
    for line in out.splitlines():
        m = re.match(r'^(\S+?\.o):\s+file format', line)
        if m:
            obj = f'{path}({m.group(1)})' if path.endswith('.a') else path
            continue
        if line.startswith('Sections:'):
            mode = 'h'; continue
        if line.startswith('SYMBOL TABLE:'):
            mode = 't'; continue
        m = re.match(r'^RELOCATION RECORDS FOR \[(.+)\]:', line)
        if m:
            mode = 'r'; cur_rel = m.group(1); continue
        if mode == 'h':
            m = re.match(r'^\s*\d+\s+(\S+)\s+([0-9a-f]+)\s', line)
            if m:
                sec_size[(obj, m.group(1))] = int(m.group(2), 16)
                local[obj][m.group(1)] = m.group(1)
        elif mode == 't':
            # 00000000 l     F .text.foo  00000040 foo
            m = re.match(r'^[0-9a-f]+\s+(.{7})\s+(\S+)\s+[0-9a-f]+\s+(.*)$', line)
            if not m:
                continue
            flags, sec, name = m.group(1), m.group(2), m.group(3).strip()
            name = name.split()[-1] if name else name
            if sec in ('*UND*', '*ABS*') or not name:
                continue
            if flags[0] in 'gu' or 'w' in flags[1:2]:
                if name not in defs or 'w' not in flags:
                    defs[name] = (obj, sec)
            local[obj].setdefault(name, sec)
        elif mode == 'r':
            m = re.match(r'^[0-9a-f]+\s+\S+\s+(\S+)', line)
            if m and m.group(1) != 'VALUE':
                sym = re.split(r'[+-]0x', m.group(1))[0]
                pending.append(((obj, cur_rel), sym, obj))

for f in sorted(files):
    parse(f)
for src, sym, obj in pending:
    sec = local[obj].get(sym) if sym in local[obj] and (sym.startswith('.') or sym not in defs) else None
    if sec is None and sym in defs:
        dst = defs[sym]
    elif sec is not None:
        dst = (obj, sec)
    else:
        continue
    edges[src].add(dst)

# --- roots: the entry point and the linker script's KEEPs
roots = []
if '_start' in defs:
    roots.append(defs['_start'])
for node in sec_size:
    if re.match(r'^\.(vectors|tcsm)', node[1]):
        roots.append(node)
parent = {r: None for r in roots}
q = collections.deque(roots)
while q:
    n = q.popleft()
    for m in edges.get(n, ()):
        if m not in parent:
            parent[m] = n
            q.append(m)

def short(node):
    obj, sec = node
    o = obj.split(build.rstrip('/') + '/')[-1]
    s = sec.replace('.text.', '').replace('.rodata.', 'ro:')
    return f'{s} [{o}]'

def chain(node):
    out = []
    while node is not None:
        out.append(short(node)); node = parent[node]
    return ' <- '.join(out)

live_by_obj = collections.Counter()
for node in parent:
    if 'bss' not in node[1]:
        live_by_obj[node[0]] += sec_size.get(node, 0)
print(f'live: {sum(live_by_obj.values()) / 1024:.0f} KB in {len(live_by_obj)} objects')

def report(obj):
    nodes = [n for n in parent if n[0] == obj and sec_size.get(n, 0)]
    if not nodes:
        return
    # the shortest chain into this object
    best = min(nodes, key=lambda n: len(chain(n)))
    print(f'\n{live_by_obj[obj] / 1024:6.1f} KB  {short((obj, ""))}')
    print('   ', chain(best))

if top:
    for obj, _ in live_by_obj.most_common(top):
        report(obj)
for pat in patterns:
    for obj in sorted(live_by_obj, key=lambda o: -live_by_obj[o]):
        if pat in obj:
            report(obj)
