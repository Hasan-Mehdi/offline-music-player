#!/usr/bin/env python3
"""Split the library's track titles into chunk files for LLM classification.
Writes data/llm_chunks/in_NN.jsonl (one JSON object per line: idx,id,artist,title).
"""
import json
from pathlib import Path

import numpy as np

CH = 200
out = Path("data/llm_chunks")
out.mkdir(parents=True, exist_ok=True)
for f in list(out.glob("in_*.jsonl")) + list(out.glob("out_*.json")):
    f.unlink()

d = np.load("data/muq_embeddings.npz", allow_pickle=False)
ids, arts, titles = list(d["ids"]), d["artists"], d["titles"]
n = len(ids)
k = 0
for start in range(0, n, CH):
    lines = [json.dumps({"idx": i, "id": str(ids[i]), "artist": str(arts[i]),
                         "title": str(titles[i])}, ensure_ascii=False)
             for i in range(start, min(start + CH, n))]
    (out / f"in_{k:02d}.jsonl").write_text("\n".join(lines), encoding="utf-8")
    k += 1
print(f"{n} tracks -> {k} chunks (<= {CH} each) in {out}/  [in_00..in_{k-1:02d}]")
