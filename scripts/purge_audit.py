#!/usr/bin/env python3
"""Purge audit — find harvest contamination in the library. READ-ONLY.

The harvest waves (radio/playlist neighbors-of-neighbors) pulled in tracks the
listener never wanted (sertanejo, reggaeton, ...). Flagging works in MuQ space:

  flag a track iff NONE of its 50 nearest library neighbors is a WANTED track
  (and the listener never engaged with it, and its artist has no wanted track).

Neighborhood wanted-DENSITY beats raw exemplar cosine here: with thousands of
exemplars every track is ~0.8-cosine to *something*, which let sertanejo slip a
plain-affinity cut. Contamination lives in dense, wanted-free clusters — its
neighbors are only more contamination. Affinity (top-3 exemplar cosine) is still
computed for ordering and context.

WANTED = trusted signals only:
  * data/seed_tracks.csv — the YT Music watch-history import (real listens)
  * plays log            — completes, likes, and >=2x replays
data/library_seeds.csv is deliberately NOT used: it was auto-sampled from the
library (not hand-approved) and contains contamination itself — a Gino & Geno
track in it seeded the whole sertanejo harvest neighborhood.

Grouping is by artist (channel): contamination arrives in artist-shaped chunks,
so review happens at the artist level, worst-affinity groups first.

Outputs:
  data/purge_audit.csv    every scored non-protected track (flagged column marks cut)
  data/purge_review.html  standalone review page: artist groups, checkboxes, audio
                          preview (plays via the local server if it is running),
                          "download drop list" button -> purge_drop.csv
  terminal                affinity distribution + the worst 25 artist groups

Then: review the HTML, download the drop list, and run scripts/purge_apply.py on it
(that step quarantines files + removes DB rows; THIS script changes nothing).

Usage:
  .venv\\Scripts\\python scripts\\purge_audit.py [--cut 0.55] [--min-group 2]
"""
from __future__ import annotations

import argparse
import csv
import html
import json
import sqlite3
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import personalize  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "library.db"
NPZ = ROOT / "data" / "muq_embeddings.npz"
GENRE_CSV = ROOT / "data" / "artist_genre.csv"
OUT_CSV = ROOT / "data" / "purge_audit.csv"
OUT_HTML = ROOT / "data" / "purge_review.html"

MIN_EXEMPLARS = 20      # below this the taste model is too thin to audit against
TOPK = 3                # affinity = mean of top-K exemplar sims (context/ordering only)
NEIGHBORS = 50          # local neighborhood size for the wanted-density flag
CLUSTER_SIM = 0.72      # greedy review-cluster join threshold


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--cut", type=float, default=None,
                    help="optionally ALSO require affinity below this (default: off; "
                         "the zero-wanted-neighborhood flag stands alone)")
    ap.add_argument("--min-group", type=int, default=1,
                    help="only show review clusters with at least this many tracks")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    con = sqlite3.connect(DB)
    con.row_factory = sqlite3.Row
    rows = {r["video_id"]: r for r in con.execute(
        "SELECT video_id, path, title, artist, duration FROM tracks")}
    durations = {v: r["duration"] for v, r in rows.items()}
    id2artist = {v: (r["artist"] or "") for v, r in rows.items()}
    plays = [(r["video_id"], r["ts"], r["event"], r["seconds"]) for r in con.execute(
        "SELECT video_id, ts, event, seconds FROM plays")]

    genre = {}
    if GENRE_CSV.exists():
        for r in csv.DictReader(open(GENRE_CSV, encoding="utf-8-sig")):
            if r.get("artist"):
                genre[r["artist"].strip().lower()] = r.get("genre", "")

    d = np.load(NPZ, allow_pickle=False)
    X = d["embeddings"].astype(np.float32)
    X /= (np.linalg.norm(X, axis=1, keepdims=True) + 1e-9)
    ids = [str(x) for x in d["ids"]]
    id2i = {v: i for i, v in enumerate(ids)}

    prefs = personalize.compute_prefs(plays, durations, id2artist, now=time.time())
    counts = prefs["play_counts"]
    # WANTED exemplars: trusted deliberate-taste signals only, undecayed (a track loved
    # in the watch-history import IS taste, no matter how long ago) — see docstring for
    # why library_seeds.csv is excluded
    wanted = set()
    p = ROOT / "data" / "seed_tracks.csv"
    if p.exists():
        wanted |= {r["video_id"] for r in csv.DictReader(open(p, encoding="utf-8-sig"))
                   if r.get("video_id")}
    wanted |= {v for v, s in prefs["track"].items() if s > 0.1}
    wanted |= {v for v, c in counts.items() if c >= 2}
    exemplars = [v for v in wanted if v in id2i]
    if len(exemplars) < MIN_EXEMPLARS:
        print(f"only {len(exemplars)} exemplars — not enough taste signal to audit")
        return 1
    protected_artists = {id2artist.get(v, "") for v in exemplars} - {""}
    # artists the listener explicitly engaged with positively at channel level too
    protected_artists |= {a for a, s in prefs["artist"].items() if s > 0.5}
    E = X[[id2i[v] for v in exemplars]]
    print(f"library {len(rows)} tracks | embedded {len(ids)} | "
          f"exemplars {len(exemplars)} | protected artists {len(protected_artists)}")

    # score every embedded, non-protected library track the listener never engaged with
    cand = [v for v in rows
            if v in id2i and v not in wanted and v not in prefs["skip_ids"]
            and prefs["track"].get(v, 0.0) <= 0.1
            and id2artist.get(v, "") not in protected_artists]
    rejected = [v for v in rows
                if v in id2i and (v in prefs["skip_ids"] or prefs["track"].get(v, 0) < -0.3)
                and id2artist.get(v, "") not in protected_artists]
    unembedded = sum(1 for v in rows if v not in id2i)

    # neighbor universe: embedded tracks that are actually in the library
    uni = [v for v in rows if v in id2i]
    ui = np.array([id2i[v] for v in uni], dtype=np.int64)
    wanted_mask = np.array([v in wanted for v in uni], dtype=bool)
    Xu = X[ui]

    aff, wfrac = {}, {}
    CH = 2048
    ci = [id2i[v] for v in cand]
    for lo in range(0, len(ci), CH):
        blk = X[ci[lo:lo + CH]]
        ex = blk @ E.T                                       # (chunk, n_exemplars)
        k = min(TOPK, ex.shape[1])
        m = np.partition(ex, -k, axis=1)[:, -k:].mean(axis=1)
        sims = blk @ Xu.T                                    # (chunk, library)
        nb = np.argpartition(-sims, NEIGHBORS + 1, axis=1)[:, :NEIGHBORS + 1]
        for off, v in enumerate(cand[lo:lo + CH]):
            aff[v] = float(m[off])
            near = [uni[int(j)] for j in nb[off] if uni[int(j)] != v][:NEIGHBORS]
            wfrac[v] = float(np.mean([w in wanted for w in near]))
        print(f"  scored {min(lo + CH, len(ci))}/{len(ci)}", end="\r")
    print()

    wanted_free = {v for v, f in wfrac.items() if f == 0.0}
    cut = args.cut if args.cut is not None else 1.0   # affinity cut optional, off by default
    flagged = {v for v in wanted_free if aff[v] < cut}
    fr = np.array(list(wfrac.values()))
    print(f"neighborhood wanted-density: {np.mean(fr == 0)*100:.1f}% of audited tracks "
          f"have ZERO wanted tracks among their {NEIGHBORS} nearest neighbors -> flagged")

    # review groups: cluster the flagged tracks by SOUND (contamination arrives in
    # sonic clusters — one checkbox nukes 'everything that sounds like forró'),
    # labeled by their dominant artists
    order = sorted(flagged, key=lambda v: aff[v])
    centroids, members = [], []
    for v in order:
        x = X[id2i[v]]
        best, bs = -1, CLUSTER_SIM
        for k, c in enumerate(centroids):
            s = float(x @ c / (np.linalg.norm(c) + 1e-9))
            if s > bs:
                best, bs = k, s
        if best < 0:
            centroids.append(x.copy())
            members.append([v])
        else:
            centroids[best] += x
            members[best].append(v)
    gstats = []
    for vs in members:
        if len(vs) < args.min_group:
            continue
        arts = {}
        for v in vs:
            a = id2artist.get(v, "") or "(no artist)"
            arts[a] = arts.get(a, 0) + 1
        top_a = sorted(arts, key=arts.get, reverse=True)
        label = ", ".join(top_a[:2]) + (f" +{len(arts)-2} more" if len(arts) > 2 else "")
        gen = [genre.get(a.strip().lower(), "") for a in top_a]
        gen = next((g for g in gen if g), "")
        vs = sorted(vs, key=lambda v: aff[v])
        gstats.append({
            "anchor": vs[0], "artist": label, "genre": gen,
            "flagged": len(vs), "total": len(vs), "top_artists": top_a[:6],
            "mean_aff": float(np.mean([aff[v] for v in vs])),
            "tracks": vs,
        })
    gstats.sort(key=lambda g: (-g["flagged"], g["mean_aff"]))

    # cluster dump for LLM/manual triage (anchor = lowest-affinity member: a stable
    # key that survives small re-runs); triage file marks whole clusters as junk
    (ROOT / "data" / "purge_clusters.json").write_text(json.dumps([{
        "anchor": g["anchor"], "n": g["flagged"], "genre": g["genre"],
        "artists": g["top_artists"],
        "samples": [rows[v]["title"] for v in g["tracks"][:3]],
    } for g in gstats], ensure_ascii=False, indent=1), encoding="utf-8")
    triage = {}
    tpath = ROOT / "data" / "purge_triage.json"
    if tpath.exists():
        try:
            triage = {t["anchor"]: t for t in json.loads(tpath.read_text(encoding="utf-8"))}
        except Exception as e:
            print(f"(triage file unreadable: {e})")
    for g in gstats:
        t = triage.get(g["anchor"])
        g["verdict"] = (t or {}).get("verdict", "unsure")
        g["why"] = (t or {}).get("why", "")
    if triage:
        nj = sum(g["flagged"] for g in gstats if g["verdict"] == "junk")
        print(f"triage: {sum(1 for g in gstats if g['verdict']=='junk')} junk clusters "
              f"({nj} tracks) pre-checked; keep/unsure left unchecked")

    size_of = {}
    for g in gstats:
        for v in g["tracks"]:
            try:
                size_of[v] = Path(rows[v]["path"]).stat().st_size
            except OSError:
                size_of[v] = 0
    tot_bytes = sum(size_of.values())

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["video_id", "artist", "title", "genre", "affinity", "wanted_frac",
                    "flagged", "play_count", "duration"])
        for v, a in sorted(aff.items(), key=lambda kv: (wfrac[kv[0]], kv[1])):
            r = rows[v]
            w.writerow([v, r["artist"], r["title"],
                        genre.get((r["artist"] or "").strip().lower(), ""),
                        f"{a:.4f}", f"{wfrac[v]:.3f}", int(v in flagged),
                        counts.get(v, 0), r["duration"]])

    write_review_html(gstats, rows, aff, size_of, cut, len(flagged), tot_bytes)

    print(f"\nflagged {len(flagged)} never-engaged tracks with wanted-free neighborhoods "
          f"({tot_bytes/1e9:.2f} GB) in {len(gstats)} sound clusters; "
          f"{len(rejected)} more were played-and-rejected (listed in CSV only); "
          f"{unembedded} tracks have no embedding yet (not auditable).")
    print(f"wrote {OUT_CSV.name} + {OUT_HTML.name}\n")
    print(f"{'tracks':>7}  {'aff':>6}  {'genre':<18} cluster (dominant artists)")
    for g in gstats[:25]:
        print(f"{g['flagged']:>7}  {g['mean_aff']:>6.3f}  "
              f"{(g['genre'] or '?')[:18]:<18} {g['artist'][:60]}")
    return 0


def write_review_html(gstats, rows, aff, size_of, cut, n_flagged, tot_bytes):
    """Standalone review page: no build step, opens from disk, previews audio through
    the local server when it is up. Checked tracks land in the exported drop list."""
    order = {"junk": 0, "unsure": 1, "keep": 2}
    gsorted = sorted(gstats, key=lambda g: (order.get(g["verdict"], 1), -g["flagged"]))
    data = [{
        "artist": g["artist"], "genre": g["genre"], "aff": round(g["mean_aff"], 3),
        "total": g["total"], "verdict": g["verdict"], "why": g["why"],
        "tracks": [{"id": v, "t": rows[v]["title"], "ar": rows[v]["artist"],
                    "a": round(aff[v], 3),
                    "mb": round(size_of.get(v, 0) / 1e6, 1)} for v in g["tracks"]],
    } for g in gsorted]
    page = """<!doctype html><meta charset="utf-8">
<title>Purge review</title>
<style>
 body{font:14px/1.5 system-ui;margin:24px auto;max-width:980px;color:#1a1a1a;background:#fafafa}
 h1{font-size:20px} .sum{color:#666;margin-bottom:18px}
 details{background:#fff;border:1px solid #e2e2e2;border-radius:8px;margin:8px 0;padding:2px 14px}
 summary{cursor:pointer;padding:8px 0;display:flex;gap:12px;align-items:baseline}
 summary b{flex:1} .aff{color:#b4231f;font-variant-numeric:tabular-nums}
 .ge{color:#888;font-size:12px} .n{color:#666;font-size:12px}
 .tr{display:flex;gap:10px;align-items:center;padding:3px 0;border-top:1px solid #f0f0f0}
 .tr span.ti{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 .tr .a{color:#b4231f;font-size:12px;width:46px;text-align:right;font-variant-numeric:tabular-nums}
 .tr .mb{color:#999;font-size:12px;width:56px;text-align:right}
 button{cursor:pointer;border:1px solid #ccc;border-radius:6px;background:#fff;padding:2px 9px}
 .bar{position:sticky;top:0;background:#fafafa;padding:10px 0;display:flex;gap:10px;align-items:center;border-bottom:1px solid #e2e2e2;margin-bottom:12px}
 .bar .cnt{font-weight:600} #dl{background:#b4231f;color:#fff;border-color:#b4231f;padding:6px 14px}
 audio{height:26px;max-width:230px}
 .badge{font-size:11px;border-radius:10px;padding:1px 8px;margin-left:4px}
 .badge.junk{background:#fde8e8;color:#b4231f} .badge.keep{background:#e6f4ea;color:#137333}
 .badge.unsure{background:#eee;color:#666}
 .why{color:#888;font-size:12px;padding:0 0 6px 26px;font-style:italic}
</style>
<h1>Purge review — flagged harvest contamination</h1>
<div class="sum">__SUMMARY__</div>
<div class="bar">
 <span class="cnt" id="cnt"></span>
 <button onclick="setAll(true)">check all</button>
 <button onclick="setAll(false)">uncheck all</button>
 <button id="dl" onclick="dl()">download drop list (purge_drop.csv)</button>
</div>
<div id="groups"></div>
<script>
const DATA = __DATA__;
const state = {};   // id -> checked; only triaged-junk clusters start checked
DATA.forEach(g => g.tracks.forEach(t => state[t.id] = (g.verdict === 'junk')));
function esc(s){const d=document.createElement('div');d.textContent=s;return d.innerHTML}
const BADGE = {junk:'<span class="badge junk">junk</span>',
               keep:'<span class="badge keep">looks fine</span>',
               unsure:'<span class="badge unsure">unsure</span>'};
function render(){
  document.getElementById('groups').innerHTML = DATA.map((g,gi)=>`
   <details ${g.verdict==='junk'?'open':''}>
    <summary><input type="checkbox" ${g.tracks.every(t=>state[t.id])?'checked':''}
       onclick="event.stopPropagation();grp(${gi},this.checked)">
     <b>${esc(g.artist)}</b>${BADGE[g.verdict]||''}<span class="ge">${esc(g.genre||'?')}</span>
     <span class="n">${g.tracks.length} tracks</span></summary>
    ${g.why?`<div class="why">${esc(g.why)}</div>`:''}
    ${g.tracks.map(t=>`
     <div class="tr"><input type="checkbox" ${state[t.id]?'checked':''}
        onchange="state['${t.id}']=this.checked;count()">
      <span class="ti" title="${esc(t.t)}">${esc(t.t)}</span>
      <span class="ge">${esc(t.ar)}</span>
      <span class="a">${t.a.toFixed(3)}</span><span class="mb">${t.mb} MB</span>
      <button onclick="prev(this,'${t.id}')">▶</button></div>`).join('')}
   </details>`).join('');
  count();
}
function grp(gi,on){DATA[gi].tracks.forEach(t=>state[t.id]=on);render()}
function setAll(on){DATA.forEach(g=>g.tracks.forEach(t=>state[t.id]=on));render()}
function count(){const n=Object.values(state).filter(Boolean).length;
  document.getElementById('cnt').textContent = n + ' selected'}
let cur=null;
function prev(btn,id){
  if(cur){cur.pause();cur.remove();cur=null}
  cur=document.createElement('audio');cur.controls=true;cur.autoplay=true;
  cur.src='http://127.0.0.1:5000/audio/'+id;
  btn.after(cur);
}
function dl(){
  const ids=Object.keys(state).filter(k=>state[k]);
  const blob=new Blob(['video_id\\n'+ids.join('\\n')+'\\n'],{type:'text/csv'});
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);
  a.download='purge_drop.csv';a.click();
}
render();
</script>"""
    summary = (f"{n_flagged} tracks have no wanted music anywhere near them in sound "
               f"space ({tot_bytes/1e9:.2f} GB, {len(gstats)} sound clusters). Clusters "
               f"triaged as <b>junk</b> start CHECKED (drop); everything else starts "
               f"unchecked — most of it is unexplored discovery, not contamination. "
               f"Preview needs the player server on :5000. Adjust checkboxes, download "
               f"the drop list, then run "
               f"<code>scripts\\purge_apply.py data\\purge_drop.csv</code>.")
    page = page.replace("__SUMMARY__", summary)
    page = page.replace("__DATA__", json.dumps(data, ensure_ascii=False))
    OUT_HTML.write_text(page, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
