#!/usr/bin/env python3
"""Personal "Every Noise at Once"-style genre map of the library.

  * interpretable axes from MuQ-MuLan text anchors:
        x = energetic - calm,   y = electronic - acoustic
  * KMeans clusters = your personal micro-genres, auto-labelled by the best-matching
    genre phrase (MuQ text->audio) + dominant artist
  * outputs:
        viz/genre_map.html   - interactive (hover = track, click = play on YT Music)
        viz/06_genre_map.png - static, interpretable axes + cluster labels
        data/clusters.csv    - video_id, artist, title, cluster, genre, x, y
"""
from __future__ import annotations

import csv
import json
import warnings
from collections import Counter
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import to_hex
from sklearn.cluster import KMeans

import torch
from muq import MuQMuLan

NPZ = "data/muq_embeddings.npz"
VIZ = Path("viz"); VIZ.mkdir(exist_ok=True)
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

AXIS_X = ("energetic intense fast aggressive music", "calm relaxing slow gentle music")
AXIS_Y = ("electronic synthetic digital chiptune music", "acoustic organic orchestral instrumental music")
GENRE_VOCAB = [
    "chiptune", "8-bit video game music", "orchestral video game soundtrack",
    "piano arrangement", "future funk", "vaporwave", "city pop", "jazz",
    "lo-fi hip hop", "hip hop rap", "rock", "metal", "electronic dance music",
    "synthwave", "ambient", "acoustic folk", "funk", "drum and bass", "pop", "soundtrack",
]


def l2(M):
    return M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)


def asc(s, n=40):
    s = str(s).encode("ascii", "ignore").decode().strip() or str(s)
    return s if len(s) <= n else s[: n - 1] + "."


def main():
    warnings.filterwarnings("ignore")
    d = np.load(NPZ, allow_pickle=False)
    X = l2(d["embeddings"].astype(np.float64))
    ids, arts, titles = list(d["ids"]), [str(a) for a in d["artists"]], [str(t) for t in d["titles"]]
    n = len(ids)
    print(f"{n} tracks")

    model = MuQMuLan.from_pretrained("OpenMuQ/MuQ-MuLan-large").to(DEVICE).eval()
    texts = [AXIS_X[0], AXIS_X[1], AXIS_Y[0], AXIS_Y[1]] + GENRE_VOCAB
    with torch.no_grad():
        T = torch.nn.functional.normalize(model(texts=texts), dim=-1).cpu().numpy().astype(np.float64)
    ex, ey = T[0] - T[1], T[2] - T[3]
    gvecs = T[4:]

    def z(v):
        return (v - v.mean()) / (v.std() + 1e-9)
    ax = z(X @ ex)
    ay = z(X @ ey)

    k = max(6, min(16, n // 30))
    km = KMeans(n_clusters=k, n_init=10, random_state=0).fit(X)
    lab = km.labels_

    # name each cluster: best genre phrase for its centroid + dominant artist
    cluster_genre, cluster_artist = {}, {}
    for c in range(k):
        idx = np.where(lab == c)[0]
        cen = l2(X[idx].mean(0, keepdims=True))[0]
        cluster_genre[c] = GENRE_VOCAB[int(np.argmax(gvecs @ cen))]
        cluster_artist[c] = Counter(arts[i] for i in idx if arts[i]).most_common(1)[0][0] if len(idx) else ""
    names = {c: f"{cluster_genre[c]} ({asc(cluster_artist[c], 18)})" for c in range(k)}

    pal = [to_hex(plt.cm.tab20(i / 20)) for i in range(20)]
    cols = [pal[lab[i] % 20] for i in range(n)]

    # ---- clusters.csv ----
    with open("data/clusters.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["video_id", "artist", "title", "cluster", "genre", "x_energetic", "y_electronic"])
        for i in range(n):
            w.writerow([ids[i], arts[i], titles[i], lab[i], cluster_genre[lab[i]],
                        round(float(ax[i]), 3), round(float(ay[i]), 3)])

    # ---- static PNG ----
    fig, axp = plt.subplots(figsize=(12, 9))
    axp.scatter(ax, ay, c=cols, s=22, edgecolors="none", alpha=0.85)
    for c in range(k):
        idx = np.where(lab == c)[0]
        cx, cy = ax[idx].mean(), ay[idx].mean()
        axp.annotate(names[c], (cx, cy), fontsize=9, fontweight="bold", ha="center",
                     bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="0.5", alpha=0.85))
    axp.axhline(0, color="0.8", lw=0.8); axp.axvline(0, color="0.8", lw=0.8)
    axp.set_xlabel("calm  ───────▶  energetic", fontsize=11)
    axp.set_ylabel("acoustic  ───────▶  electronic", fontsize=11)
    axp.set_title(f"Your library as a genre map — {n} tracks, {k} auto-labelled clusters "
                  "(MuQ-MuLan, interpretable axes)")
    axp.set_xticks([]); axp.set_yticks([])
    fig.tight_layout(); fig.savefig(VIZ / "06_genre_map.png", dpi=130); plt.close(fig)

    # ---- interactive HTML ----
    pts = [{"x": round(float(ax[i]), 3), "y": round(float(ay[i]), 3), "col": cols[i],
            "lab": asc(f"{arts[i]} - {titles[i]}", 60), "g": names[lab[i]],
            "url": f"https://music.youtube.com/watch?v={ids[i]}"} for i in range(n)]
    html = HTML_TEMPLATE.replace("__DATA__", json.dumps(pts, ensure_ascii=False))
    (VIZ / "genre_map.html").write_text(html, encoding="utf-8")

    print(f"clusters ({k}):")
    for c in range(k):
        print(f"  {names[c]}  -  {int((lab == c).sum())} tracks")
    print("\nwrote viz/genre_map.html, viz/06_genre_map.png, data/clusters.csv")
    return 0


HTML_TEMPLATE = """<!doctype html><html><head><meta charset="utf-8">
<title>Library genre map</title>
<style>
 body{font-family:system-ui,sans-serif;background:#0f1115;color:#e6e6e6;margin:0}
 h3{padding:10px 14px;margin:0;font-weight:600}
 #wrap{position:relative}
 #tip{position:absolute;pointer-events:none;background:#000d;border:1px solid #444;
      padding:5px 9px;border-radius:5px;font-size:12px;display:none;max-width:340px}
</style></head><body>
<h3>Your library &mdash; MuQ-MuLan genre map &nbsp;<span style="color:#888;font-weight:400">
hover = track &middot; click = play on YT Music</span></h3>
<div id="wrap"><canvas id="c" width="1280" height="780"></canvas><div id="tip"></div></div>
<script>
const PTS=__DATA__;const W=1280,H=780,P=64;
const xs=PTS.map(p=>p.x),ys=PTS.map(p=>p.y);
const xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=Math.min(...ys),ymax=Math.max(...ys);
const px=x=>P+(x-xmin)/(xmax-xmin)*(W-2*P), py=y=>H-P-(y-ymin)/(ymax-ymin)*(H-2*P);
const cv=document.getElementById('c'),ctx=cv.getContext('2d'),tip=document.getElementById('tip');
function draw(){ctx.clearRect(0,0,W,H);
 ctx.strokeStyle='#333';ctx.beginPath();ctx.moveTo(P,H-P);ctx.lineTo(W-P,H-P);ctx.moveTo(P,P);ctx.lineTo(P,H-P);ctx.stroke();
 ctx.fillStyle='#9aa';ctx.font='13px sans-serif';
 ctx.fillText('calm  \\u2192  energetic',W/2-50,H-28);
 ctx.save();ctx.translate(22,H/2+70);ctx.rotate(-Math.PI/2);ctx.fillText('acoustic  \\u2192  electronic',0,0);ctx.restore();
 for(const p of PTS){ctx.fillStyle=p.col;ctx.beginPath();ctx.arc(px(p.x),py(p.y),4,0,7);ctx.fill();}}
draw();
cv.addEventListener('mousemove',e=>{const r=cv.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
 let b=null,bd=160;for(const p of PTS){const dx=px(p.x)-mx,dy=py(p.y)-my,d=dx*dx+dy*dy;if(d<bd){bd=d;b=p;}}
 if(b){tip.style.display='block';tip.style.left=(mx+14)+'px';tip.style.top=(my+14)+'px';
  tip.innerHTML='<b>'+b.lab+'</b><br><span style=\\"color:#9cf\\">'+b.g+'</span>';cv.style.cursor='pointer';cv._h=b;}
 else{tip.style.display='none';cv.style.cursor='default';cv._h=null;}});
cv.addEventListener('click',()=>{if(cv._h)window.open(cv._h.url,'_blank');});
</script></body></html>"""


if __name__ == "__main__":
    raise SystemExit(main())
