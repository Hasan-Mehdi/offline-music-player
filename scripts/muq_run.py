#!/usr/bin/env python3
"""Incrementally embed the downloaded library with MuQ-MuLan (GPU) into
data/muq_embeddings.npz. Re-running only embeds tracks not already cached, so it's
cheap to keep current as downloads continue. Prints artist-coherence@5 at the end.

Usage: python scripts/muq_run.py [LIMIT]
"""
from __future__ import annotations

import re
import subprocess
import sys
import warnings
from collections import Counter
from pathlib import Path

import numpy as np
import torch
from muq import MuQMuLan

ID_RE = re.compile(r"\[([\w-]{11})\]\.opus$")
DIR = r"D:\OfflineMusic"
SR = 24000
WIN = 60
OUT = "data/muq_embeddings.npz"
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"


def probe(path):
    try:
        return float(subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)], capture_output=True, text=True).stdout.strip())
    except Exception:
        return None


def decode(path):
    d = probe(path)
    seek = ["-ss", str((d - WIN) / 2), "-t", str(WIN)] if d and d > WIN else []
    raw = subprocess.run(["ffmpeg", "-v", "quiet", *seek, "-i", str(path),
                          "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
                         capture_output=True).stdout
    a = np.frombuffer(raw, dtype=np.float32).copy()
    return a if a.size else None


def read_meta(path):
    from mutagen.oggopus import OggOpus
    try:
        f = OggOpus(str(path))
        return f.get("artist", [""])[0], f.get("title", [""])[0]
    except Exception:
        return "", ""


def main():
    warnings.filterwarnings("ignore")
    limit = int(sys.argv[1]) if len(sys.argv) > 1 else None
    files = sorted(Path(DIR).glob("*.opus"))
    if limit:
        files = files[:limit]
    print(f"MuQ-MuLan on {DEVICE}: {len(files)} tracks in library")

    known = {}
    if Path(OUT).exists():
        with np.load(OUT, allow_pickle=False) as prev:   # close the handle (Windows: an
            for vid, a, t, v in zip(prev["ids"], prev["artists"],  # open NpzFile blocks
                                    prev["titles"], prev["embeddings"]):  # the checkpoint
                known[str(vid)] = (str(a), str(t), v)                     # os.replace().
        print(f"  reusing {len(known)} cached embeddings")

    model = None
    ids, arts, titles, vecs = [], [], [], []
    new = 0

    def checkpoint():
        # Merge cached entries NOT iterated this run (LIMIT test runs) so a partial
        # run can never shrink the cache.
        seen = set(ids)
        all_ids, all_arts, all_titles, all_vecs = list(ids), list(arts), list(titles), list(vecs)
        for k, (a, t, v) in known.items():
            if k not in seen:
                all_ids.append(k); all_arts.append(a); all_titles.append(t); all_vecs.append(v)
        X = np.vstack(all_vecs).astype(np.float32)
        # atomic write: save to a temp then replace, so a crash mid-save can't corrupt OUT.
        tmp = OUT + ".tmp.npz"
        np.savez(tmp, embeddings=X, ids=np.array(all_ids), artists=np.array(all_arts),
                 titles=np.array(all_titles))
        Path(tmp).replace(OUT)
        return X, all_arts

    for p in files:
        m = ID_RE.search(p.name)
        vid = m.group(1) if m else p.stem
        if vid in known:
            a, t, v = known[vid]
            ids.append(vid); arts.append(a); titles.append(t); vecs.append(v)
            continue
        audio = decode(p)
        if audio is None:
            continue
        ar, ti = read_meta(p)
        if model is None:
            model = MuQMuLan.from_pretrained("OpenMuQ/MuQ-MuLan-large").to(DEVICE).eval()
        with torch.no_grad():
            wav = torch.tensor(audio)[None].to(DEVICE)
            e = torch.nn.functional.normalize(model(wavs=wav), dim=-1).cpu().numpy()[0]
        ids.append(vid); arts.append(ar); titles.append(ti); vecs.append(e)
        new += 1
        if new % 100 == 0:
            print(f"  embedded {new} new...")
        # Checkpoint periodically so a multi-hour run survives interruption/idle-reap and
        # resumes from the cache (only ~500 tracks of work lost at most).
        if new % 500 == 0:
            Xc, _ = checkpoint()
            print(f"  ...checkpointed {Xc.shape[0]} embeddings to {OUT}", flush=True)

    X, all_arts = checkpoint()
    print(f"saved {X.shape} ({new} new) -> {OUT}")

    # artist-coherence@5 (numpy only, CHUNKED — a full similarity matrix at 56k
    # tracks would be ~13 GB; 2048-row chunks keep it under ~500 MB)
    n = X.shape[0]
    A = np.array(all_arts)
    same = tot = 0
    for s in range(0, n, 2048):
        S = X[s:s + 2048] @ X.T
        for r in range(S.shape[0]):
            S[r, s + r] = -1                      # exclude self-match
        top = np.argpartition(-S, 5, axis=1)[:, :5]
        for r in range(S.shape[0]):
            a = A[s + r]
            if a:
                same += int((A[top[r]] == a).sum())
            tot += 5
    base = sum((v / n) ** 2 for v in Counter(a for a in all_arts if a).values())
    print(f"artist-coherence@5: {same/tot*100:.1f}%  (baseline {base*100:.2f}%, lift {(same/tot)/base:.1f}x)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
