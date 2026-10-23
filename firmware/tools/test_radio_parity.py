"""The device radio engine (firmware/core/omp_radio.c) == player_server/radio.py's sequence().

Random sittings over a pack's radio.bin (scripts/radio_pack.py): a seed, a tail heard, songs
excluded, songs turned down, songs the device log knows. The reference is radio.sequence()
itself over the same quantized radio list (scores in thousandths, song2vec as int8, sound
as the pack's fp16), so this checks the C port of the per-pick logic, not the export.

  .venv\\Scripts\\python firmware\\tools\\test_radio_parity.py D:\\coda-h2card\\.coda\\pack [cases]
"""
import random
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts"))
from player_server import radio  # noqa: E402

pack = Path(sys.argv[1])
n_cases = int(sys.argv[2]) if len(sys.argv) > 2 else 400
raw = (pack / "radio.bin").read_bytes()
v2 = raw[:4] == b"CRA2"
n, K, dim = np.frombuffer(raw[4:16], "<u4")
o = 16
count = np.frombuffer(raw, "<u2", n, o); o += 2 * n
known = np.frombuffer(raw, "u1", n, o); o += n
game = np.frombuffer(raw, "u1", n, o); o += n
chan = np.frombuffer(raw, "<u4", n, o); o += 4 * n
chan2 = np.frombuffer(raw, "<u4", n, o) if v2 else np.zeros(n, "<u4"); o += 4 * n if v2 else 0
work = np.frombuffer(raw, "<u4", n, o) if v2 else np.zeros(n, "<u4"); o += 4 * n if v2 else 0
rows = np.frombuffer(raw, [("idx", "<u4"), ("score", "<i2")], n * K, o).reshape(n, K); o += 6 * n * K
s2v = np.frombuffer(raw, "i1", n * dim, o).reshape(n, dim).astype(np.float32); o += n * dim
shr = raw[o:o + 4] == b"SHR1"           # each seed's channel / game-series share, x 250
ashare = np.frombuffer(raw, "u1", n, o + 4) if shr else None
gshare = np.frombuffer(raw, "u1", n, o + 4 + n) if shr else None
o2 = o + 4 + 2 * n
fam1 = shr and raw[o2:o2 + 4] == b"FAM1"   # each seed's share of songs you know, x 250
fshare = np.frombuffer(raw, "u1", n, o2 + 4) if fam1 else None
X = np.memmap(pack / "embeddings.f16", dtype="<f2", mode="r").reshape(n, -1)

FAM = {i: 1.0 for i in np.flatnonzero(known).tolist()}
ART = {i: int(chan[i]) for i in np.flatnonzero(chan).tolist()}
CRED = {i: tuple(int(c) for c in (chan[i], chan2[i]) if c) for i in range(n)}
WORK = {i: int(work[i]) for i in np.flatnonzero(work).tolist()}
FR = {i: int(game[i]) for i in np.flatnonzero(game).tolist()}
rng = random.Random(7)
seeds = [i for i in range(n) if count[i]]
cases, want = [], []
for c in range(n_cases):
    seed = rng.choice(seeds)
    lst = [int(v) for v in rows[seed, :count[seed]]["idx"]]
    pool = lst + [rng.randrange(n) for _ in range(30)]
    tail = [rng.choice(pool) for _ in range(rng.randrange(0, 13))]
    ex = list(dict.fromkeys(tail + [rng.choice(pool) for _ in range(rng.randrange(0, 40))]))
    if c % 7 == 0:
        ex = list(dict.fromkeys(ex + lst[:rng.randrange(0, len(lst))]))   # most of it gone
    rej = rng.sample(pool, rng.randrange(0, 3)) if c % 3 else []
    kx = rng.sample(pool, rng.randrange(0, 20))

    exs = set(ex) | {seed}
    heard = {WORK[x] for x in [*exs, *tail] if x in WORK}       # no other version of these
    cand = [(int(v), s / 1000.0) for v, s in rows[seed, :count[seed]]
            if v < n and v not in exs and WORK.get(int(v)) not in heard]
    rv = [np.asarray(X[r], np.float32) for r in rej]
    rs = [s2v[r] for r in rej if s2v[r].any()]
    if rv or rs:
        adj = []
        for v, s in cand:
            m = 0.0
            if rv:
                xv = np.asarray(X[v], np.float32)
                m = max(m, max(float(xv @ r) for r in rv))
            if rs and s2v[v].any():
                m = max(m, max(float(s2v[v] @ r) / (127 * 127) for r in rs))
            adj.append((v, s - radio.REJECT_W * m))
        cand = sorted(adj, key=lambda e: -e[1])
    fam = dict(FAM)
    fam.update({v: 1.0 for v in kx})
    ctx = SimpleNamespace(fam=fam, artist=ART, franchise=FR, credits=CRED, work=WORK)
    sh = {} if ashare is None else {"artist_share": ashare[seed] / 250.0, "game_share": gshare[seed] / 250.0}
    if fshare is not None:
        sh["familiar_share"] = fshare[seed] / 250.0
    q = radio.sequence(seed, cand, 1, ctx, tail=tail, **sh) if cand else []
    want.append(q[0] if q else -1)
    cases.append(" ".join(str(x) for x in [seed, len(tail), *tail, len(ex), *ex, len(rej), *rej,
                                           len(kx), *kx]))

exe = ROOT / "firmware" / "host" / "build" / "test_radio.exe"
out = subprocess.run([str(exe), str(pack)], input="\n".join(cases) + "\n", capture_output=True,
                     text=True, check=True).stdout.split()
got = [int(x) for x in out]
bad = [(i, w, g) for i, (w, g) in enumerate(zip(want, got)) if w != g]
print(f"{len(got) - len(bad)}/{len(want)} identical picks")
for i, w, g in bad[:10]:
    print("  case", i, "python", w, "c", g)
sys.exit(1 if bad or len(got) != len(want) else 0)
