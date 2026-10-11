#!/usr/bin/env python3
"""Duplicate-rip finder — same recording, different YouTube upload. READ-ONLY.

The library was harvested from YouTube, so the same recording often exists two or
three times under different video_ids (different channel, different "artist"
string, sometimes a slightly different title). There is no acoustic fingerprint
here, but there IS a 2.3M-row table of precomputed MuQ cosine neighbors, and two
rips of one master sit at cosine ~0.99+ of each other — far above where distinct
recordings land (the sim histogram has a hard knee: 68k pairs >= 0.96, 3.1k >= 0.98,
1.4k >= 0.985). That knee is the dupe boundary, so:

  candidate pair  =  neighbors.sim >= 0.985  AND  |duration difference| <= 2.5 s

Duration is the second, independent axis: MuQ embeds the CENTER 60 s of a track, so
a 3-minute radio edit and its 7-minute extended mix can embed nearly identically —
the duration gate is what keeps those out (and what makes chaptered OST rips, where
two 40-minute compilations share a middle section, mostly self-eliminate).

Tiers (per pair, strongest first):
  exact      sim >= 0.995 and |durd| <= 1.5 s and normalized titles identical
  likely     sim >= 0.985 and (difflib title ratio >= 0.85 or |durd| <= 1.0 s)
  uncertain  everything else that got this far — near-identical embeddings from the
             SAME artist are often legit alt versions (live, remaster, single edit),
             so these are shown but never pre-checked.
Artist strings deliberately do NOT gate anything: dupe rips come from different
channels and usually disagree on artist. A matching artist is shown as a badge (it
raises confidence) but is never required.

Pairs are union-found into groups. Keeper per group: most play events, tie-break
longer duration, tie-break lowest video_id (stable across re-runs).

Outputs:
  data/dupes.csv        group_id, video_id, role, tier, sim_to_keeper, title, artist,
                        duration, play_count, path
  viz/dupe_review.html  standalone review page in the same mold as purge_review.html:
                        groups by tier (exact first), audio preview per member, the
                        remove-candidates of exact+likely pre-checked, and an export
                        button emitting a video_id list that scripts/purge_apply.py
                        eats directly (quarantine + undo log).

This script writes only those two files — it never touches audio or the DB.

Usage:
  .venv\\Scripts\\python scripts\\find_dupes.py [--sim 0.985] [--dur 2.5]
Then: open viz\\dupe_review.html, review, "download removal list" -> dupe_drop.csv,
      .venv\\Scripts\\python scripts\\purge_apply.py data\\dupe_drop.csv
"""
from __future__ import annotations

import argparse
import csv
import difflib
import json
import re
import sqlite3
import sys
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DB = ROOT / "data" / "library.db"
OUT_CSV = ROOT / "data" / "dupes.csv"
OUT_HTML = ROOT / "viz" / "dupe_review.html"

TIERS = ("exact", "likely", "uncertain")
TIER_RANK = {t: i for i, t in enumerate(TIERS)}

# Words that mark a DIFFERENT take of the same composition. When one of a pair carries
# such a word and the other does not, that is the precision hot-spot of this whole
# script — usually it is still a dupe (a "(Slowed + Reverb)" upload that was never
# actually slowed: same duration, cosine 1.0) but sometimes it is a real alt version.
# Flagged on the review page so those rows get an ear before they are dropped; it does
# NOT change the tier or the default checkbox.
VERSION_WORDS = re.compile(
    r"\b(live|remaster(?:ed)?|remix|instrumental|acoustic|sped ?up|slowed|reverb|"
    r"nightcore|cover|karaoke|extended|radio edit|demo|reprise|version|remake|"
    r"arrangement|orchestral|8d)\b", re.I)


def version_flags(title_a, title_b):
    """Version keywords present on exactly one side of a pair."""
    a = {w.lower() for w in VERSION_WORDS.findall(title_a or "")}
    b = {w.lower() for w in VERSION_WORDS.findall(title_b or "")}
    return sorted(a ^ b)


def norm(s):
    """String normalizer — copied verbatim from scripts/curate.py so title matching
    here behaves exactly like it does in the curation pipeline."""
    s = unicodedata.normalize("NFKD", str(s)).lower()
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9\s]", " ", s)).strip()


def tier_of(sim, dd, title_a, title_b):
    """(tier, title_ratio) for one candidate pair."""
    na, nb = norm(title_a or ""), norm(title_b or "")
    ratio = difflib.SequenceMatcher(None, na, nb).ratio() if (na and nb) else 0.0
    if sim >= 0.995 and dd <= 1.5 and na and na == nb:
        return "exact", ratio
    if sim >= 0.985 and (ratio >= 0.85 or dd <= 1.0):
        return "likely", ratio
    return "uncertain", ratio


class UF:
    def __init__(self):
        self.p = {}

    def find(self, x):
        self.p.setdefault(x, x)
        while self.p[x] != x:
            self.p[x] = self.p[self.p[x]]
            x = self.p[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.p[rb] = ra


def fetch_pairs(con, sim_min, dur_max):
    """Candidate pairs, canonicalized to one row per unordered pair, IN SQL.

    neighbors is 2.3M rows and has no index on sim, so this is one streaming scan
    that returns ~10^3 rows; nothing large ever reaches Python."""
    sql = """
      WITH p AS (
        SELECT min(video_id, neighbor_id) AS a,
               max(video_id, neighbor_id) AS b,
               max(sim)                   AS sim
        FROM neighbors
        WHERE sim >= ? AND video_id <> neighbor_id
        GROUP BY 1, 2
      )
      SELECT p.a, p.b, p.sim,
             ta.title, ta.artist, ta.album, ta.duration, ta.path,
             tb.title, tb.artist, tb.album, tb.duration, tb.path
      FROM p
      JOIN tracks ta ON ta.video_id = p.a
      JOIN tracks tb ON tb.video_id = p.b
      WHERE ta.duration IS NOT NULL AND tb.duration IS NOT NULL
        AND abs(ta.duration - tb.duration) <= ?
      ORDER BY p.sim DESC
    """
    return con.execute(sql, (sim_min, dur_max)).fetchall()


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sim", type=float, default=0.985,
                    help="cosine floor for a candidate pair (default 0.985)")
    ap.add_argument("--dur", type=float, default=2.5,
                    help="max |duration difference| in seconds (default 2.5)")
    args = ap.parse_args()
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

    con = sqlite3.connect(f"file:{DB}?mode=ro", uri=True)
    con.execute("PRAGMA busy_timeout=15000")
    con.row_factory = sqlite3.Row

    n_tracks = con.execute("SELECT count(*) FROM tracks").fetchone()[0]
    n_nb = con.execute("SELECT count(*) FROM neighbors").fetchone()[0]
    raw = fetch_pairs(con, args.sim, args.dur)
    n_above = con.execute("SELECT count(*) FROM neighbors WHERE sim >= ?",
                          (args.sim,)).fetchone()[0]
    print(f"library {n_tracks} tracks | neighbors {n_nb} rows | "
          f"{n_above} directed rows >= {args.sim} -> {len(raw)} unordered pairs "
          f"within {args.dur}s duration")

    # play events per track (the keeper signal); 'peek'/'skip' are not listens
    counts = {r[0]: r[1] for r in con.execute(
        "SELECT video_id, count(*) FROM plays WHERE event IN ('play','complete') "
        "GROUP BY video_id")}

    meta, pair_sim, adj, uf = {}, {}, {}, UF()
    for r in raw:
        a, b, sim = r[0], r[1], float(r[2])
        meta[a] = {"title": r[3] or "", "artist": r[4] or "", "album": r[5] or "",
                   "duration": float(r[6]), "path": r[7] or ""}
        meta[b] = {"title": r[8] or "", "artist": r[9] or "", "album": r[10] or "",
                   "duration": float(r[11]), "path": r[12] or ""}
        dd = abs(meta[a]["duration"] - meta[b]["duration"])
        tier, _ = tier_of(sim, dd, meta[a]["title"], meta[b]["title"])
        pair_sim[(a, b)] = sim
        adj.setdefault(a, []).append(tier)
        adj.setdefault(b, []).append(tier)
        uf.union(a, b)

    clusters = {}
    for v in meta:
        clusters.setdefault(uf.find(v), []).append(v)

    def sim_lookup(x, y):
        """Direct cosine for a member that is only transitively linked to the keeper."""
        s = pair_sim.get((min(x, y), max(x, y)))
        if s is not None:
            return s
        row = con.execute(
            "SELECT max(sim) FROM neighbors WHERE (video_id=? AND neighbor_id=?) "
            "OR (video_id=? AND neighbor_id=?)", (x, y, y, x)).fetchone()
        return float(row[0]) if row and row[0] is not None else None

    groups = []
    for members in clusters.values():
        # keeper: most play events, then longer, then lowest id (stable)
        members = sorted(members, key=lambda v: (-counts.get(v, 0),
                                                 -meta[v]["duration"], v))
        keeper = members[0]
        km = meta[keeper]
        out = []
        for v in members:
            if v == keeper:
                continue
            s = sim_lookup(keeper, v)
            dd = abs(km["duration"] - meta[v]["duration"])
            if s is None:
                # linked only through a third member: inherit the weakest hop so a
                # transitive chain can never be promoted to 'exact'
                hops = adj.get(v, [])
                tier = max(hops, key=lambda t: TIER_RANK[t]) if hops else "uncertain"
                ratio = 0.0
            else:
                tier, ratio = tier_of(s, dd, km["title"], meta[v]["title"])
            out.append({"id": v, "sim": s, "dd": dd, "tier": tier, "ratio": ratio,
                        "vw": version_flags(km["title"], meta[v]["title"]),
                        "artist_match": norm(meta[v]["artist"]) == norm(km["artist"])
                        and bool(norm(km["artist"]))})
        gtier = min((m["tier"] for m in out), key=lambda t: TIER_RANK[t]) \
            if out else "uncertain"
        groups.append({"keeper": keeper, "removes": out, "tier": gtier,
                       "n": len(members)})

    groups.sort(key=lambda g: (TIER_RANK[g["tier"]], -g["n"],
                               -max((m["sim"] or 0) for m in g["removes"])))
    for i, g in enumerate(groups, 1):
        g["gid"] = i

    size_of = {}
    for g in groups:
        for v in [g["keeper"]] + [m["id"] for m in g["removes"]]:
            try:
                size_of[v] = Path(meta[v]["path"]).stat().st_size
            except OSError:
                size_of[v] = 0

    # ------------------------------------------------------------------ CSV
    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["group_id", "video_id", "role", "tier", "sim_to_keeper",
                    "title", "artist", "duration", "play_count", "path"])
        for g in groups:
            k = g["keeper"]
            w.writerow([g["gid"], k, "keep", g["tier"], "", meta[k]["title"],
                        meta[k]["artist"], f"{meta[k]['duration']:.1f}",
                        counts.get(k, 0), meta[k]["path"]])
            for m in sorted(g["removes"], key=lambda m: TIER_RANK[m["tier"]]):
                v = m["id"]
                w.writerow([g["gid"], v, "remove", m["tier"],
                            "" if m["sim"] is None else f"{m['sim']:.4f}",
                            meta[v]["title"], meta[v]["artist"],
                            f"{meta[v]['duration']:.1f}", counts.get(v, 0),
                            meta[v]["path"]])

    write_review_html(groups, meta, counts, size_of, args)

    # ------------------------------------------------------------------ report
    by_tier = {t: 0 for t in TIERS}
    gby_tier = {t: 0 for t in TIERS}
    bytes_by_tier = {t: 0 for t in TIERS}
    for g in groups:
        gby_tier[g["tier"]] += 1
        for m in g["removes"]:
            by_tier[m["tier"]] += 1
            bytes_by_tier[m["tier"]] += size_of.get(m["id"], 0)
    tot_rm = sum(by_tier.values())
    print(f"\n{len(groups)} groups | {tot_rm} remove-candidates "
          f"({sum(bytes_by_tier.values())/1e9:.2f} GB)")
    for t in TIERS:
        print(f"  {t:<10} {by_tier[t]:>4} tracks in {gby_tier[t]:>3} groups "
              f"({bytes_by_tier[t]/1e9:.2f} GB)")
    pre = by_tier["exact"] + by_tier["likely"]
    print(f"  pre-checked on the review page: {pre} (exact+likely); "
          f"{by_tier['uncertain']} uncertain left unchecked")

    sizes = {}
    for g in groups:
        sizes[g["n"]] = sizes.get(g["n"], 0) + 1
    print("group sizes: " + ", ".join(f"{k}x{v}" for k, v in sorted(sizes.items())))
    same_art = sum(1 for g in groups
                   for m in g["removes"] if m["artist_match"])
    print(f"artist string matches the keeper in {same_art}/{tot_rm} remove-candidates "
          f"(dupe rips usually disagree — different channel)")
    dur_only = sum(1 for g in groups for m in g["removes"]
                   if m["tier"] == "likely" and m["ratio"] < 0.85)
    print(f"{dur_only} of the {by_tier['likely']} 'likely' removes matched on duration "
          f"alone (titles differ) — verbose YouTube titles for the same rip")
    flagged = [(g, m) for g in groups for m in g["removes"] if m["vw"]]
    print(f"{len(flagged)} removes carry a version word the keeper lacks "
          f"({', '.join(sorted({w for _, m in flagged for w in m['vw']})[:10])}...) "
          f"— flagged on the page, listen before dropping those")
    longs = [g for g in groups if meta[g["keeper"]]["duration"] >= 600]
    if longs:
        print(f"{len(longs)} groups are long-form (>=10 min keeper) — check these by ear, "
              f"chaptered OST/compilation rips share their middle 60 s")

    print("\nexamples (tier | sim | durations | keeper <- strongest dupe):")
    shown = 0
    for g in groups:
        if shown >= 10:
            break
        k = g["keeper"]
        m = min(g["removes"], key=lambda m: (TIER_RANK[m["tier"]], -(m["sim"] or 0)))
        v = m["id"]
        print(f"  [{m['tier']:<9}] sim {('%.4f' % m['sim']) if m['sim'] else '  -   '} "
              f"{meta[k]['duration']:.0f}s/{meta[v]['duration']:.0f}s "
              f"({g['n']} copies)")
        print(f"      KEEP   {meta[k]['title'][:62]!r} - {meta[k]['artist'][:34]}")
        print(f"      DROP   {meta[v]['title'][:62]!r} - {meta[v]['artist'][:34]}")
        shown += 1

    print(f"\nwrote {OUT_CSV} + {OUT_HTML}")
    print("review -> download removal list -> "
          "python scripts\\purge_apply.py data\\dupe_drop.csv")
    return 0


def write_review_html(groups, meta, counts, size_of, args):
    """Standalone page, same mold as data/purge_review.html: no build step, opens
    from disk, previews audio through the local player server, exports a video_id
    CSV that purge_apply.py consumes."""
    data = []
    for g in groups:
        k = g["keeper"]
        rows = [{"id": k, "t": meta[k]["title"], "ar": meta[k]["artist"],
                 "al": meta[k]["album"], "d": round(meta[k]["duration"], 1),
                 "pc": counts.get(k, 0), "mb": round(size_of.get(k, 0) / 1e6, 1),
                 "role": "keep", "tier": g["tier"], "sim": None, "vw": [],
                 "am": True}]
        for m in sorted(g["removes"], key=lambda m: TIER_RANK[m["tier"]]):
            v = m["id"]
            rows.append({"id": v, "t": meta[v]["title"], "ar": meta[v]["artist"],
                         "al": meta[v]["album"], "d": round(meta[v]["duration"], 1),
                         "pc": counts.get(v, 0),
                         "mb": round(size_of.get(v, 0) / 1e6, 1),
                         "role": "remove", "tier": m["tier"],
                         "sim": None if m["sim"] is None else round(m["sim"], 4),
                         "vw": m["vw"], "am": bool(m["artist_match"])})
        data.append({"gid": g["gid"], "tier": g["tier"], "n": g["n"],
                     "title": meta[k]["title"], "tracks": rows})

    n_rm = sum(len(g["removes"]) for g in groups)
    n_vw = sum(1 for g in groups for m in g["removes"] if m["vw"])
    pre = sum(1 for g in groups for m in g["removes"] if m["tier"] != "uncertain")
    gb = sum(size_of.get(m["id"], 0) for g in groups for m in g["removes"]) / 1e9
    summary = (f"{len(groups)} groups of near-identical recordings "
               f"({n_rm} removable copies, {gb:.2f} GB) found by MuQ cosine "
               f"&ge; {args.sim} plus a &le; {args.dur}s duration gate. "
               f"<b>exact</b> and <b>likely</b> copies start CHECKED ({pre}); "
               f"<b>uncertain</b> starts unchecked — same-artist twins are often a "
               f"live take or a remaster, not a dupe. The <span class='kp'>KEEP</span> "
               f"row is the one with the most plays (then longest, then lowest id); "
               f"check it and uncheck a copy if you would rather keep the other rip. "
               f"{n_vw} rows carry a <span class='vw'>&ne;version</span> flag — a "
               f"version word (live, slowed, remix...) the keeper does not have; those "
               f"are the ones worth an ear, and one button defers them all. "
               f"Preview needs the player server on :5000. Download the removal list, "
               f"then run <code>scripts\\purge_apply.py data\\dupe_drop.csv</code> "
               f"(quarantines, fully undoable).")

    page = """<!doctype html><meta charset="utf-8">
<title>Duplicate review</title>
<style>
 body{font:14px/1.5 system-ui;margin:24px auto;max-width:1040px;color:#1a1a1a;background:#fafafa}
 h1{font-size:20px} .sum{color:#666;margin-bottom:18px}
 details{background:#fff;border:1px solid #e2e2e2;border-radius:8px;margin:8px 0;padding:2px 14px}
 details.danger{border-color:#e8b4b3;background:#fffafa}
 summary{cursor:pointer;padding:8px 0;display:flex;gap:10px;align-items:baseline}
 summary b{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 .n{color:#666;font-size:12px} .ge{color:#888;font-size:12px}
 .tr{display:flex;gap:10px;align-items:center;padding:3px 0;border-top:1px solid #f0f0f0}
 .tr span.ti{flex:1;overflow:hidden;text-overflow:ellipsis;white-space:nowrap}
 .tr .s{color:#b4231f;font-size:12px;width:52px;text-align:right;font-variant-numeric:tabular-nums}
 .tr .d{color:#666;font-size:12px;width:52px;text-align:right;font-variant-numeric:tabular-nums}
 .tr .mb{color:#999;font-size:12px;width:56px;text-align:right}
 .tr .pc{color:#137333;font-size:12px;width:44px;text-align:right}
 .tr.keep{background:#f4faf5}
 .kp{font-size:11px;border-radius:10px;padding:1px 7px;background:#e6f4ea;color:#137333}
 .rm{font-size:11px;border-radius:10px;padding:1px 7px;background:#f2f2f2;color:#777}
 button{cursor:pointer;border:1px solid #ccc;border-radius:6px;background:#fff;padding:2px 9px}
 .bar{position:sticky;top:0;background:#fafafa;padding:10px 0;display:flex;gap:8px;
      align-items:center;border-bottom:1px solid #e2e2e2;margin-bottom:12px;flex-wrap:wrap}
 .bar .cnt{font-weight:600;margin-right:6px}
 #dl{background:#b4231f;color:#fff;border-color:#b4231f;padding:6px 14px}
 audio{height:26px;max-width:230px}
 .badge{font-size:11px;border-radius:10px;padding:1px 8px}
 .badge.exact{background:#fde8e8;color:#b4231f}
 .badge.likely{background:#fff2e0;color:#a35b00}
 .badge.uncertain{background:#eee;color:#666}
 .am{font-size:11px;color:#137333}
 .vw{font-size:11px;color:#a35b00;background:#fff2e0;border-radius:8px;padding:0 6px}
 .warn{color:#b4231f;font-size:12px;padding:2px 0 6px 26px}
</style>
<h1>Duplicate review — same recording, different upload</h1>
<div class="sum">__SUMMARY__</div>
<div class="bar">
 <span class="cnt" id="cnt"></span>
 <button onclick="setTier('exact',true)">check exact</button>
 <button onclick="setTier('likely',true)">check likely</button>
 <button onclick="setTier('uncertain',true)">check uncertain</button>
 <button onclick="setAll(false)">uncheck all</button>
 <button onclick="unflag()" title="defer every row whose title carries a version word the keeper lacks">uncheck &ne;version</button>
 <span class="ge">show:</span>
 <select id="flt" onchange="render()">
  <option value="">all tiers</option><option value="exact">exact</option>
  <option value="likely">likely</option><option value="uncertain">uncertain</option>
  <option value="vw">&ne;version only</option>
 </select>
 <button id="dl" onclick="dl()">download removal list (dupe_drop.csv)</button>
</div>
<div id="groups"></div>
<script>
const DATA = __DATA__;
const state = {};   // id -> checked; exact+likely copies start checked, keepers never
DATA.forEach(g => g.tracks.forEach(t =>
  state[t.id] = (t.role === 'remove' && t.tier !== 'uncertain')));
// escapes quotes too: YouTube titles are full of them and these strings also land
// in title="..." attributes
function esc(s){const d=document.createElement('div');d.textContent=s||'';
  return d.innerHTML.replace(/"/g,'&quot;')}
function mmss(s){const m=Math.floor(s/60);return m+':'+String(Math.round(s-60*m)).padStart(2,'0')}
function vis(){const f=document.getElementById('flt').value;
  if(!f) return DATA;
  if(f==='vw') return DATA.filter(g=>g.tracks.some(t=>t.vw&&t.vw.length));
  return DATA.filter(g=>g.tier===f)}
function allGone(g){return g.tracks.every(t=>state[t.id])}
function render(){
  document.getElementById('groups').innerHTML = vis().map(g=>`
   <details ${g.tier==='exact'?'':'open'} class="${allGone(g)?'danger':''}">
    <summary><span class="badge ${g.tier}">${g.tier}</span>
     <b>${esc(g.title)}</b>
     <span class="n">${g.n} copies</span>
     <span class="ge">#${g.gid}</span></summary>
    ${allGone(g)?'<div class="warn">every copy in this group is checked — you would lose this recording entirely</div>':''}
    ${g.tracks.map(t=>`
     <div class="tr ${t.role==='keep'?'keep':''}">
      <input type="checkbox" ${state[t.id]?'checked':''}
        onchange="state['${t.id}']=this.checked;render()">
      <span class="${t.role==='keep'?'kp':'rm'}">${t.role==='keep'?'KEEP':t.tier}</span>
      <span class="ti" title="${esc(t.t)}">${esc(t.t)}</span>
      <span class="ge">${esc(t.ar)}${t.am&&t.role==='remove'?' <span class="am">=artist</span>':''}${t.vw&&t.vw.length?' <span class="vw" title="version word on one side only — give it an ear">&ne; '+esc(t.vw.join(' '))+'</span>':''}</span>
      <span class="s">${t.sim!=null?t.sim.toFixed(4):''}</span>
      <span class="d">${mmss(t.d)}</span>
      <span class="pc">${t.pc?t.pc+'&#9654;':''}</span>
      <span class="mb">${t.mb} MB</span>
      <button onclick="prev(this,'${t.id}')">&#9654;</button></div>`).join('')}
   </details>`).join('');
  count();
}
function setTier(tier,on){DATA.forEach(g=>g.tracks.forEach(t=>{
  if(t.role==='remove' && t.tier===tier) state[t.id]=on}));render()}
function setAll(on){DATA.forEach(g=>g.tracks.forEach(t=>{
  state[t.id]= on && t.role==='remove'}));render()}
function unflag(){DATA.forEach(g=>g.tracks.forEach(t=>{
  if(t.vw&&t.vw.length) state[t.id]=false}));render()}
function count(){const n=Object.values(state).filter(Boolean).length;
  const bad=DATA.filter(allGone).length;
  document.getElementById('cnt').textContent = n + ' to remove' +
    (bad? '  ('+bad+' group(s) fully checked!)':'')}
let cur=null;
function prev(btn,id){
  if(cur){cur.pause();cur.remove();cur=null}
  cur=document.createElement('audio');cur.controls=true;cur.autoplay=true;
  cur.src='http://127.0.0.1:5000/audio/'+id;
  btn.after(cur);
}
function dl(){
  const bad=DATA.filter(allGone);
  if(bad.length && !confirm(bad.length+' group(s) have EVERY copy checked — those '
     +'recordings would disappear from the library. Export anyway?')) return;
  const ids=Object.keys(state).filter(k=>state[k]);
  const blob=new Blob(['video_id\\n'+ids.join('\\n')+'\\n'],{type:'text/csv'});
  const a=document.createElement('a');a.href=URL.createObjectURL(blob);
  a.download='dupe_drop.csv';a.click();
}
render();
</script>"""
    page = page.replace("__SUMMARY__", summary)
    payload = json.dumps(data, ensure_ascii=False).replace("</", "<\\/")  # no </script> break
    page = page.replace("__DATA__", payload)
    OUT_HTML.parent.mkdir(parents=True, exist_ok=True)
    OUT_HTML.write_text(page, encoding="utf-8")


if __name__ == "__main__":
    raise SystemExit(main())
