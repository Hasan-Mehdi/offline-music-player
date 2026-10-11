#!/usr/bin/env python3
"""Turn the analysis into playable .m3u playlists in viz/playlists/:
  * one per auto-detected genre cluster (data/clusters.csv)
  * mood mixes via MuQ-MuLan text->music
Paths point into the library so they open in VLC / any player.
"""
from __future__ import annotations

import csv
import re
from collections import defaultdict
from pathlib import Path

import numpy as np

DIR = Path(r"D:\OfflineMusic")
OUT = Path("viz/playlists")
OUT.mkdir(parents=True, exist_ok=True)
ID_RE = re.compile(r"\[([\w-]{11})\]\.opus$")

MOODS = ["rainy late night lofi", "upbeat chiptune", "vaporwave future funk",
         "epic orchestral", "relaxing piano", "energetic workout"]


def safe(s):
    return re.sub(r'[\\/:*?"<>|]', "_", str(s))[:60].strip()


def main():
    id2path = {}
    for p in DIR.glob("*.opus"):
        m = ID_RE.search(p.name)
        if m:
            id2path[m.group(1)] = str(p)
    print(f"{len(id2path)} library files indexed")

    def write_m3u(name, vids, title):
        paths = [id2path[v] for v in vids if v in id2path]
        if not paths:
            return 0
        (OUT / f"{safe(name)}.m3u").write_text(
            "\n".join(["#EXTM3U", f"#PLAYLIST:{title}"] + paths), encoding="utf-8")
        return len(paths)

    # genre cluster playlists
    clusters, labels = defaultdict(list), {}
    if Path("data/clusters.csv").exists():
        for r in csv.DictReader(open("data/clusters.csv", encoding="utf-8-sig")):
            clusters[r["cluster"]].append(r["video_id"])
            labels[r["cluster"]] = r["genre"]
    ng = sum(bool(write_m3u(f"genre_{c}_{labels.get(c,'')}", v, f"{labels.get(c,'')} #{c}"))
             for c, v in clusters.items())
    print(f"{ng} genre playlists")

    # mood mixes (text -> music)
    d = np.load("data/muq_embeddings.npz", allow_pickle=False)
    X = d["embeddings"].astype(np.float64)
    X /= np.linalg.norm(X, axis=1, keepdims=True) + 1e-9
    ids = list(d["ids"])
    import torch
    from muq import MuQMuLan
    dev = "cuda" if torch.cuda.is_available() else "cpu"
    model = MuQMuLan.from_pretrained("OpenMuQ/MuQ-MuLan-large").to(dev).eval()
    with torch.no_grad():
        T = torch.nn.functional.normalize(model(texts=MOODS), dim=-1).cpu().numpy()
    for mood, row in zip(MOODS, T @ X.T):
        top = [ids[j] for j in np.argsort(-row)[:30]]
        write_m3u(f"mood_{mood}", top, mood)
    print(f"{len(MOODS)} mood mixes")
    print(f"playlists -> {OUT.resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
