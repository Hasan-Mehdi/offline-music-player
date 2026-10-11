#!/usr/bin/env python3
"""Merge the Haiku chunk outputs (data/llm_chunks/out_*.json) into data/llm_series.csv
and report coverage + curation stats (what's VGM, what's dropped, series distribution).
"""
import collections
import csv
import json
from pathlib import Path

import numpy as np

d = np.load("data/muq_embeddings.npz", allow_pickle=False)
ids = list(d["ids"])
n = len(ids)

recs, bad = {}, []
for f in sorted(Path("data/llm_chunks").glob("out_*.json")):
    try:
        arr = json.loads(f.read_text(encoding="utf-8"))
    except Exception as e:
        bad.append((f.name, str(e)[:60]))
        continue
    for o in arr:
        try:
            recs[int(o["idx"])] = o
        except Exception:
            pass

missing = [i for i in range(n) if i not in recs]
with open("data/llm_series.csv", "w", encoding="utf-8-sig", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["video_id", "is_vgm", "series", "confidence"])
    for i in range(n):
        o = recs.get(i)
        if o is None:
            continue
        w.writerow([ids[i], int(bool(o.get("is_vgm"))),
                    str(o.get("series", "")), str(o.get("confidence", ""))])

vg = sum(1 for o in recs.values() if o.get("is_vgm"))
print(f"covered {len(recs)}/{n}  | missing {len(missing)}  | bad files: {bad}")
print(f"is_vgm: true {vg}  false {len(recs)-vg}")
sc = collections.Counter(o.get("series", "") for o in recs.values() if o.get("is_vgm"))
print("top VGM series:")
for s, c in sc.most_common(20):
    print(f"  {s:<22} {c}")
conf = collections.Counter(o.get("confidence", "") for o in recs.values() if o.get("is_vgm"))
print("confidence (vgm):", dict(conf))
if missing:
    print("missing idx (chunks to re-run):", missing[:15], "..." if len(missing) > 15 else "")
print("wrote data/llm_series.csv")
