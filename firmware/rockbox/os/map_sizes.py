#!/usr/bin/env python3
"""Where the firmware's bytes come from: sum a GNU ld map by source folder / object.
  python3 map_sizes.py build-strip/rockbox.map [--objects N] [--filter apps/gui]"""
import re, sys, collections
args = sys.argv[1:]
path = args[0]
nobj = int(args[args.index('--objects') + 1]) if '--objects' in args else 0
filt = args[args.index('--filter') + 1] if '--filter' in args else None
by_dir, by_obj, by_kind = collections.Counter(), collections.Counter(), collections.Counter()
sec = None
pending = None
in_discard = False
for line in open(path, errors='replace'):
    if line.startswith('/DISCARD/') or line.startswith('Discarded input sections'):
        in_discard = True
    if line.startswith('Memory map') or line.startswith('Linker script and memory map'):
        in_discard = False
    if in_discard:
        continue
    m = re.match(r'^ (\.[\w.$]+)\s*$', line)
    if m:
        pending = m.group(1); continue
    m = re.match(r'^ (\.[\w.$]+)?\s+0x([0-9a-f]+)\s+0x([0-9a-f]+)\s+(\S+\.(?:o|a\(.*\)))\s*$', line)
    if not m:
        pending = None; continue
    name = m.group(1) or pending
    pending = None
    size = int(m.group(3), 16)
    obj = m.group(4)
    if not name or size == 0:
        continue
    kind = 'text' if name.startswith('.text') or name.startswith('.icode') else \
           'rodata' if name.startswith('.rodata') else \
           'data' if name.startswith('.data') or name.startswith('.sdata') else \
           'bss' if 'bss' in name or name.startswith('.ibss') else 'other'
    if kind == 'bss':
        continue
    o = obj.split('/build-strip/')[-1].split('/build-os/')[-1]
    if filt and filt not in o:
        continue
    parts = o.split('/')
    d = '/'.join(parts[:2]) if len(parts) > 2 else parts[0]
    if 'libcoda' in o or 'coda_os' in o: d = 'CODA'
    by_dir[d] += size; by_obj[o] += size; by_kind[kind] += size
tot = sum(by_dir.values())
print(f'total (text+rodata+data, no bss): {tot/1024:.0f} KB  ' + '  '.join(f'{k} {v/1024:.0f}KB' for k, v in by_kind.items()))
for d, v in by_dir.most_common(40):
    print(f'{v/1024:8.1f} KB  {d}')
if nobj:
    print('--- objects')
    for o, v in by_obj.most_common(nobj):
        print(f'{v/1024:8.1f} KB  {o}')
