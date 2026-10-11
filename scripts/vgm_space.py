#!/usr/bin/env python3
"""A finer embedding space WITHIN video-game music.

Filters the library to VGM (title heuristics + MuQ "video game music" similarity),
infers series & type from titles, then re-projects and sub-clusters ONLY the VGM subset
to reveal within-VGM structure that the global map compresses.

Outputs:
  viz/07_vgm_map.png  - VGM-specific interpretable axes (orchestral<->chiptune,
                        calm/town<->battle/intense), coloured by series
  viz/vgm_map.html    - interactive t-SNE (hover=track, click=play on YT Music)
  data/vgm.csv        - video_id, artist, title, series, type, cluster, x, y
"""
from __future__ import annotations

import csv
import json
import re
import warnings
from collections import Counter
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.colors import to_hex
from sklearn.cluster import KMeans
from sklearn.manifold import TSNE

import torch
from muq import MuQMuLan

NPZ = "data/muq_embeddings.npz"
VIZ = Path("viz"); VIZ.mkdir(exist_ok=True)
DEVICE = "cuda" if torch.cuda.is_available() else "cpu"

# series -> title keywords (checked in order; first match wins). Lowercased substrings.
SERIES = [
    ("Pokémon", ["pokemon", "pokémon", "pokè", "pkmn", "mystery dungeon", "kanto", "johto",
                 "sinnoh", "unova", "kalos", "alola", "galar", "lavender", "slateport",
                 "azalea", "nacrene", "anville", "nuvema", "hau'oli", "eterna", "arceus",
                 "jacinthe", "dialga", "explorers of sky", "don't ever forget"]),
    ("Zelda", ["zelda", "hyrule", "ocarina", "majora", "wind waker", "breath of the wild",
               "tears of the kingdom", "kakariko", "gerudo", "windfish", "rito", "ganon",
               "dragon roost", "ordon", "lost woods", "kass", "spirit tracks", "fairy's fountain",
               "fairy fountain", "skyward"]),
    ("Sonic", ["sonic", "green hill", "chemical plant", "studiopolis", "flying battery",
               "metallic madness", "palmtree panic", "quartz quadrant", "stardust speedway",
               "hedgehog", "windmill isle", "cool edge", "star light", "special stage"]),
    ("Mario", ["mario", "luigi", "bowser", "galaxy", "odyssey", "sunshine", "comet observatory",
               "dreamy", "dream team", "somnom", "delfino", "mushroom"]),
    ("Final Fantasy", ["final fantasy", "ffvii", "ff7", "chocobo", "zanarkand", "aerith",
                       "one winged angel", "uematsu", "eternal wind"]),
    ("Deltarune/Undertale", ["deltarune", "undertale", "toby fox", "megalovania", "ruder buster",
                             "rude buster", "dark sanctuary", "spamton", "field of hopes",
                             "death by glamour", "spider dance", "dummy", "running sky"]),
    ("MOTHER/Earthbound", ["mother 3", "earthbound", "new pork", "porky", "snowman",
                           "pork bossa", "tazmilian"]),
    ("Octopath", ["octopath"]),
    ("Kirby", ["kirby", "dedede", "green greens", "gourmet race"]),
    ("Metroid", ["metroid", "samus", "brinstar"]),
    ("Mega Man", ["mega man", "megaman", "wily", "vulpex"]),
    ("Donkey Kong", ["donkey kong", "stickerbush", "aquatic ambiance"]),
    ("Castlevania", ["castlevania", "bloody tears", "vampire killer", "dracula", "crystal teardrops"]),
    ("Splatoon", ["splatoon", "inkopolis", "calamari"]),
    ("Animal Crossing", ["animal crossing", "k.k.", "kk slider"]),
    ("Xenoblade", ["xenoblade", "gaur plain"]),
    ("Chrono", ["chrono trigger", "chrono cross", "corridors of time"]),
    ("Kingdom Hearts", ["kingdom hearts", "dearly beloved"]),
    ("Touhou", ["touhou", "cirno", "marisa", "reimu"]),
    ("Celeste", ["celeste", "resurrections"]),
    ("Hollow Knight", ["hollow knight", "greenpath", "hornet"]),
    ("Pseudoregalia", ["pseudoregalia"]),
]
ARR_MARKERS = ["remix", "arrangement", "arr.", "cover", "remaster", "re-imagined", "reimagined",
               "remake", "ft.", "feat.", "8-bit", "8 bit", "16-bit", "chiptune", "mix)", "mix ",
               "fm version", "(re", "rearrange"]
CHIP = re.compile(r"\[(nsf|ym\d|huc6280|vrc6|n163|spc700|2a03|fds|msx|sega|psg|gb|sn76489|ymz)\w*",
                  re.I)
ORIG_MARKERS = ["ost", "original soundtrack", '(from "', "official", "original game soundtrack"]

AXIS_X = ("8-bit chiptune retro video game music", "orchestral cinematic live instrument soundtrack")
AXIS_Y = ("intense fast video game boss battle theme", "calm peaceful village town overworld theme")


def l2(M):
    return M / (np.linalg.norm(M, axis=1, keepdims=True) + 1e-9)


def asc(s, n=40):
    s = str(s).encode("ascii", "ignore").decode().strip() or str(s)
    return s if len(s) <= n else s[: n - 1] + "."


def infer_series(text):
    for canon, kws in SERIES:
        if any(k in text for k in kws):
            return canon
    return None


def infer_type(text):
    if CHIP.search(text) or any(m in text for m in ARR_MARKERS):
        return "remix/arrangement"
    if any(m in text for m in ORIG_MARKERS):
        return "original OST"
    return "other"


def main():
    warnings.filterwarnings("ignore")
    d = np.load(NPZ, allow_pickle=False)
    X = l2(d["embeddings"].astype(np.float64))
    ids, arts, titles = list(d["ids"]), [str(a) for a in d["artists"]], [str(t) for t in d["titles"]]
    n = len(ids)
    text = [f"{arts[i]} {titles[i]}".lower() for i in range(n)]

    model = MuQMuLan.from_pretrained("OpenMuQ/MuQ-MuLan-large").to(DEVICE).eval()
    STYLE = ["8-bit chiptune", "orchestral", "solo piano", "jazz", "funk", "rock", "synthwave",
             "drum and bass", "ambient", "acoustic guitar", "big band swing", "lo-fi hip hop",
             "vaporwave", "metal"]
    anchors = [AXIS_X[0], AXIS_X[1], AXIS_Y[0], AXIS_Y[1], "video game music soundtrack"] + STYLE
    with torch.no_grad():
        T = torch.nn.functional.normalize(model(texts=anchors), dim=-1).cpu().numpy().astype(np.float64)
    ex, ey, vgm_vec = T[0] - T[1], T[2] - T[3], T[4]
    style_vecs = T[5:]
    vgm_score = X @ vgm_vec

    # Haiku LLM classification (if present) drives VGM membership + series labels.
    llm = {}
    if Path("data/llm_series.csv").exists():
        for r in csv.DictReader(open("data/llm_series.csv", encoding="utf-8-sig")):
            llm[r["video_id"]] = (r["is_vgm"] == "1", r["series"], r["confidence"])
    print(f"LLM labels: {len(llm)}")

    series_all = [infer_series(text[i]) for i in range(n)]
    thr = float(np.percentile(vgm_score, 35))

    def heuristic_vgm(i):
        return (bool(series_all[i]) or bool(CHIP.search(text[i]))
                or any(m in text[i] for m in ARR_MARKERS + ORIG_MARKERS) or vgm_score[i] >= thr)

    # membership: LLM is_vgm wins; tracks LLM didn't cover fall back to the heuristic
    vgm = []
    for i in range(n):
        v = llm.get(ids[i])
        if (v[0] if v is not None else heuristic_vgm(i)):
            vgm.append(i)
    print(f"VGM tracks: {len(vgm)} / {n}  (LLM-curated, non-VGM dropped)")

    Xv = X[vgm]
    BAD = {"", "Unknown VGM", "NOT VGM", "Unknown", "Nintendo"}
    series = []
    for i in vgm:
        v = llm.get(ids[i])
        if v and v[2] in ("high", "med") and v[1] not in BAD:
            series.append(v[1])                 # trust the LLM franchise
        elif series_all[i]:
            series.append(series_all[i])        # keyword fallback
        else:
            series.append("other VGM")          # filled by nearest-neighbour below
    typ = [infer_type(text[i]) for i in vgm]

    inferred = [s == "other VGM" for s in series]
    named = [j for j in range(len(vgm)) if series[j] != "other VGM"]
    if named:
        Nmat = Xv[named]
        for j in range(len(vgm)):
            if series[j] == "other VGM":
                series[j] = series[named[int(np.argmax(Xv[j] @ Nmat.T))]]
    print(f"inferred series for {sum(inferred)} tracks via nearest-neighbour")

    def z(v):
        return (v - v.mean()) / (v.std() + 1e-9)
    axx, axy = z(Xv @ ex), z(Xv @ ey)

    k = max(6, min(18, len(vgm) // 40))
    lab = KMeans(n_clusters=k, n_init=10, random_state=0).fit_predict(Xv)
    style_global = (Xv @ style_vecs.T).mean(0)        # baseline -> pick each cluster's *distinctive* style
    cnames = {}
    for c in range(k):
        idx = [j for j in range(len(vgm)) if lab[j] == c]
        cen = l2(Xv[idx].mean(0, keepdims=True))[0]
        style = STYLE[int(np.argmax((style_vecs @ cen) - style_global))]
        real = [(s, ct) for s, ct in Counter(series[j] for j in idx).most_common() if s != "other VGM"]
        ser = real[0][0] if real and real[0][1] >= max(3, 0.12 * len(idx)) else None
        cnames[c] = f"{style}" + (f" · {ser}" if ser else "")

    ser_counts = Counter(series)
    print("series breakdown:")
    for s, cnt in ser_counts.most_common(14):
        print(f"  {s:<22} {cnt}")

    print("t-SNE...")
    emb = TSNE(n_components=2, perplexity=30, init="pca", random_state=0).fit_transform(Xv)
    e0, e1 = emb[:, 0], emb[:, 1]
    tx = (e0 - e0.min()) / (e0.max() - e0.min() + 1e-9)
    ty = (e1 - e1.min()) / (e1.max() - e1.min() + 1e-9)

    # ---- vgm.csv (everything the web tab needs) ----
    with open("data/vgm.csv", "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["video_id", "artist", "title", "series", "type", "cluster", "cluster_label",
                    "x_chiptune", "y_battle", "tsne_x", "tsne_y"])
        for j, i in enumerate(vgm):
            w.writerow([ids[i], arts[i], titles[i], series[j], typ[j], lab[j], cnames[lab[j]],
                        round(float(axx[j]), 3), round(float(axy[j]), 3),
                        round(float(tx[j]), 4), round(float(ty[j]), 4)])

    # ---- colours by top series ----
    top = [s for s, _ in ser_counts.most_common(12)]
    pal = [to_hex(plt.cm.tab20(i / 20)) for i in range(20)]
    cmap = {s: pal[i] for i, s in enumerate(top)}
    cols = [cmap.get(series[j], "#cfcfcf") for j in range(len(vgm))]

    # ---- static PNG: interpretable VGM axes ----
    fig, ax = plt.subplots(figsize=(12, 9))
    ax.scatter(axx, axy, c=cols, s=24, edgecolors="none", alpha=0.85)
    for c in range(k):
        idx = [j for j in range(len(vgm)) if lab[j] == c]
        ax.annotate(cnames[c], (np.mean([axx[j] for j in idx]), np.mean([axy[j] for j in idx])),
                    fontsize=8.5, fontweight="bold", ha="center",
                    bbox=dict(boxstyle="round,pad=0.2", fc="white", ec="0.5", alpha=0.85))
    ax.axhline(0, color="0.85", lw=0.8); ax.axvline(0, color="0.85", lw=0.8)
    ax.set_xlabel("orchestral / live  ───────▶  8-bit / chiptune", fontsize=11)
    ax.set_ylabel("calm / town  ───────▶  battle / intense", fontsize=11)
    ax.set_title(f"Video-game music sub-space — {len(vgm)} tracks, {k} clusters (series-coloured)")
    ax.set_xticks([]); ax.set_yticks([])
    handles = [plt.Line2D([0], [0], marker="o", ls="", color=cmap[s], label=asc(s, 22)) for s in top]
    ax.legend(handles=handles, fontsize=8, loc="center left", bbox_to_anchor=(1.0, 0.5), frameon=False)
    fig.tight_layout(); fig.savefig(VIZ / "07_vgm_map.png", dpi=130); plt.close(fig)

    print(f"\nclusters ({k}):")
    for c in range(k):
        print(f"  {cnames[c]:<34} {sum(1 for j in range(len(vgm)) if lab[j]==c)} tracks")
    print("\nwrote viz/07_vgm_map.png, data/vgm.csv (VGM tab served by app.py)")
    return 0


HTML = """<!doctype html><html><head><meta charset="utf-8"><title>VGM sub-space</title>
<style>body{font-family:system-ui,sans-serif;background:#0f1115;color:#e6e6e6;margin:0}
h3{padding:10px 14px;margin:0}#wrap{position:relative}
#tip{position:absolute;pointer-events:none;background:#000d;border:1px solid #444;padding:5px 9px;
border-radius:5px;font-size:12px;display:none;max-width:340px}</style></head><body>
<h3>Video-game music sub-space (__N__ tracks) &nbsp;<span style="color:#888;font-weight:400">
hover = track &middot; click = play on YT Music</span></h3>
<div id="wrap"><canvas id="c" width="1280" height="780"></canvas><div id="tip"></div></div>
<script>
const PTS=__DATA__;const W=1280,H=780,P=46;
const xs=PTS.map(p=>p.x),ys=PTS.map(p=>p.y);
const xmin=Math.min(...xs),xmax=Math.max(...xs),ymin=Math.min(...ys),ymax=Math.max(...ys);
const px=x=>P+(x-xmin)/(xmax-xmin)*(W-2*P),py=y=>H-P-(y-ymin)/(ymax-ymin)*(H-2*P);
const cv=document.getElementById('c'),ctx=cv.getContext('2d'),tip=document.getElementById('tip');
for(const p of PTS){ctx.fillStyle=p.col;ctx.beginPath();ctx.arc(px(p.x),py(p.y),4,0,7);ctx.fill();}
cv.addEventListener('mousemove',e=>{const r=cv.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
 let b=null,bd=170;for(const p of PTS){const dx=px(p.x)-mx,dy=py(p.y)-my,d=dx*dx+dy*dy;if(d<bd){bd=d;b=p;}}
 if(b){tip.style.display='block';tip.style.left=(mx+14)+'px';tip.style.top=(my+14)+'px';
  tip.innerHTML='<b>'+b.lab+'</b><br><span style=\\"color:#9cf\\">'+b.g+'</span>';cv.style.cursor='pointer';cv._h=b;}
 else{tip.style.display='none';cv.style.cursor='default';cv._h=null;}});
cv.addEventListener('click',()=>{if(cv._h)window.open(cv._h.url,'_blank');});
</script></body></html>"""


if __name__ == "__main__":
    raise SystemExit(main())
