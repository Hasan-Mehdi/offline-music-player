#!/usr/bin/env python3
"""Local web player over the offline library. Tabs:
  * Player  - genre map + mood search (MuQ-MuLan text->music) + hybrid autoplay
  * VGM Space - interactive video-game-music sub-map: series colours, filter by series,
                toggle projection (style axes <-> t-SNE), click to play locally

Run:  .venv\\Scripts\\python scripts\\app.py    then open http://127.0.0.1:5000
"""
from __future__ import annotations

import csv
import json
import re
from pathlib import Path

import numpy as np
import torch
from flask import Flask, Response, jsonify, request, send_file
from muq import MuQMuLan

DIR = Path(r"D:\OfflineMusic")
CACHE = Path("data/radio_cache")
ID_RE = re.compile(r"\[([\w-]{11})\]\.opus$")

d = np.load("data/muq_embeddings.npz", allow_pickle=False)
X = d["embeddings"].astype(np.float32)
X /= np.linalg.norm(X, axis=1, keepdims=True) + 1e-9
ids = list(d["ids"])
arts = [str(a) for a in d["artists"]]
titles = [str(t) for t in d["titles"]]
id2i = {v: i for i, v in enumerate(ids)}
idset = set(ids)

cl, gx, gy = {}, {}, {}
if Path("data/clusters.csv").exists():
    for r in csv.DictReader(open("data/clusters.csv", encoding="utf-8-sig")):
        cl[r["video_id"]] = r["genre"]
        gx[r["video_id"]] = float(r["x_energetic"])
        gy[r["video_id"]] = float(r["y_electronic"])

id2path = {}
for p in DIR.glob("*.opus"):
    m = ID_RE.search(p.name)
    if m:
        id2path[m.group(1)] = str(p)

VGM = []
if Path("data/vgm.csv").exists():
    for r in csv.DictReader(open("data/vgm.csv", encoding="utf-8-sig")):
        if r["video_id"] in id2path:
            VGM.append({"id": r["video_id"], "artist": r["artist"], "title": r["title"],
                        "series": r["series"], "type": r["type"], "label": r["cluster_label"],
                        "sx": float(r["x_chiptune"]), "sy": float(r["y_battle"]),
                        "tx": float(r["tsne_x"]), "ty": float(r["tsne_y"])})

members = {}
for s in ids:
    f = CACHE / f"{s}.json"
    if f.exists():
        try:
            tr = json.loads(f.read_text(encoding="utf-8"))
            members[s] = {t.get("videoId") for t in tr if t.get("videoId")} & idset
        except Exception:
            pass

cfg = json.loads(Path("data/autoplay_config.json").read_text()) if Path("data/autoplay_config.json").exists() else {}
BETA = cfg.get("beta", 0.6)

DEVICE = "cuda" if torch.cuda.is_available() else "cpu"
print(f"loading MuQ-MuLan on {DEVICE} ...")
model = MuQMuLan.from_pretrained("OpenMuQ/MuQ-MuLan-large").to(DEVICE).eval()
print(f"ready: {len(id2path)} playable tracks, {len(VGM)} in VGM space")

app = Flask(__name__)


def track(i):
    return {"id": ids[i], "artist": arts[i], "title": titles[i], "genre": cl.get(ids[i], "")}


@app.route("/")
def home():
    return Response(PAGE, mimetype="text/html")


@app.route("/map")
def mapdata():
    return jsonify([{"x": gx.get(ids[i], 0.0), "y": gy.get(ids[i], 0.0), "id": ids[i],
                     "lab": f"{arts[i]} - {titles[i]}", "g": cl.get(ids[i], "")}
                    for i in range(len(ids)) if ids[i] in id2path])


@app.route("/vgm")
def vgmdata():
    return jsonify(VGM)


@app.route("/search")
def search():
    q = request.args.get("q", "").strip()
    if not q:
        return jsonify([])
    with torch.no_grad():
        t = torch.nn.functional.normalize(model(texts=[q]), dim=-1).cpu().numpy()[0]
    sims = X @ t
    return jsonify([track(int(j)) for j in np.argsort(-sims)[:25] if ids[int(j)] in id2path])


@app.route("/next")
def nxt():
    cur = request.args.get("id", "")
    exclude = set(request.args.get("exclude", "").split(","))
    if cur not in id2i:
        return jsonify({})
    score = (X @ X[id2i[cur]]).copy()
    if members.get(cur):
        mem = members[cur]
        for j in range(len(ids)):
            if ids[j] in mem:
                score[j] += BETA
    for j in range(len(ids)):
        if ids[j] == cur or ids[j] in exclude or ids[j] not in id2path:
            score[j] = -1e9
    return jsonify(track(int(np.argmax(score))))


@app.route("/audio/<vid>")
def audio(vid):
    p = id2path.get(vid)
    return send_file(p, mimetype="audio/ogg", conditional=True) if p else ("not found", 404)


PAGE = """<!doctype html><html><head><meta charset="utf-8"><title>Offline Music Player</title>
<style>
body{margin:0;font-family:system-ui,sans-serif;background:#0f1115;color:#e6e6e6;display:flex;flex-direction:column;height:100vh}
header{padding:8px 14px;display:flex;gap:10px;align-items:center;border-bottom:1px solid #222}
.tabs button{background:#1a1d24;border:1px solid #333;color:#bbb;padding:7px 13px;border-radius:6px;cursor:pointer;margin-right:4px}
.tabs button.active{background:#2a9d8f;color:#fff;border-color:#2a9d8f}
input[type=text]{flex:1;padding:8px;background:#1a1d24;border:1px solid #333;color:#eee;border-radius:6px}
button.go{padding:8px 14px;background:#2a9d8f;border:none;color:#fff;border-radius:6px;cursor:pointer}
#main{flex:1;display:flex;overflow:hidden}
.tab{flex:1;display:flex;overflow:hidden}
#results{width:320px;overflow:auto;border-right:1px solid #222}
.row{padding:8px 12px;cursor:pointer;border-bottom:1px solid #181b20;font-size:13px}
.row:hover{background:#1a1d24}.g{color:#7fd6c6;font-size:11px}
.cwrap{flex:1;position:relative}canvas{display:block}
.tip{position:absolute;pointer-events:none;background:#000d;border:1px solid #444;padding:4px 8px;border-radius:4px;font-size:12px;display:none}
#vgmbar{padding:6px 10px;display:flex;flex-wrap:wrap;gap:6px;align-items:center;border-bottom:1px solid #222;max-height:96px;overflow:auto}
.chip{font-size:11px;padding:3px 8px;border-radius:10px;cursor:pointer;border:1px solid #333;user-select:none}
footer{padding:9px 14px;border-top:1px solid #222;display:flex;gap:14px;align-items:center}
#np{flex:1;font-size:13px}audio{height:34px}
</style></head><body>
<header>
 <span class="tabs"><button id="tA" class="active" onclick="showTab('player')">&#9834; Player</button>
 <button id="tB" onclick="showTab('vgm')">&#127918; VGM Space</button></span>
 <input type="text" id="q" placeholder="type a mood: rainy late-night lo-fi / vaporwave / epic orchestral...">
 <button class="go" onclick="search()">Search</button>
</header>
<div id="main">
 <div id="tab-player" class="tab">
  <div id="results"><div style="padding:12px;color:#888">Search a mood, or click a dot &rarr;</div></div>
  <div class="cwrap"><canvas id="cv"></canvas><div id="tip" class="tip"></div></div>
 </div>
 <div id="tab-vgm" class="tab" style="display:none;flex-direction:column">
  <div id="vgmbar"><button class="go" onclick="toggleProj()">view: <span id="pn">style axes</span></button>
   <span id="legend"></span></div>
  <div class="cwrap"><canvas id="vcv"></canvas><div id="vtip" class="tip"></div></div>
 </div>
</div>
<footer><div id="np">nothing playing</div>
 <label><input type="checkbox" id="auto" checked> autoplay</label>
 <audio id="au" controls></audio></footer>
<script>
let played=[];const au=document.getElementById('au'),np=document.getElementById('np');
function play(t){if(!t||!t.id)return;au.src='/audio/'+t.id;au.play();
 np.innerHTML='&#9654; <b>'+t.artist+'</b> &mdash; '+t.title+' <span class=g>'+(t.genre||t.g||'')+'</span>';
 played.push(t.id);if(played.length>80)played.shift();window._cur=t;}
au.addEventListener('ended',()=>{if(document.getElementById('auto').checked&&window._cur)
 fetch('/next?id='+window._cur.id+'&exclude='+played.join(',')).then(r=>r.json()).then(play);});
function hue(s){let h=0;for(const c of (s||'x'))h=(h*31+c.charCodeAt(0))%360;return 'hsl('+h+',62%,62%)';}

// ---- tabs ----
function showTab(n){
 document.getElementById('tab-player').style.display=n==='player'?'flex':'none';
 document.getElementById('tab-vgm').style.display=n==='vgm'?'flex':'none';
 document.getElementById('tA').className=n==='player'?'active':'';
 document.getElementById('tB').className=n==='vgm'?'active':'';
 if(n==='vgm'){if(!VG.length)loadVGM();else vresize();}else presize();}

// ---- player tab: search + global map ----
function search(){fetch('/search?q='+encodeURIComponent(document.getElementById('q').value)).then(r=>r.json()).then(rs=>{
 const d=document.getElementById('results');d.innerHTML='';
 rs.forEach(t=>{const e=document.createElement('div');e.className='row';
  e.innerHTML='<b>'+t.artist+'</b> &mdash; '+t.title+'<br><span class=g>'+(t.genre||'')+'</span>';
  e.onclick=()=>play(t);d.appendChild(e);});});}
document.getElementById('q').addEventListener('keydown',e=>{if(e.key==='Enter')search();});
let MP=[],pmin={};const cv=document.getElementById('cv'),ctx=cv.getContext('2d'),tip=document.getElementById('tip');
const ppx=x=>44+(x-pmin.x0)/(pmin.x1-pmin.x0||1)*(cv.width-88),ppy=y=>cv.height-44-(y-pmin.y0)/(pmin.y1-pmin.y0||1)*(cv.height-88);
function pdraw(){if(!MP.length)return;ctx.clearRect(0,0,cv.width,cv.height);
 ctx.fillStyle='#888';ctx.font='12px sans-serif';ctx.fillText('calm -> energetic',cv.width/2-40,cv.height-12);
 ctx.save();ctx.translate(14,cv.height/2+55);ctx.rotate(-Math.PI/2);ctx.fillText('acoustic -> electronic',0,0);ctx.restore();
 for(const p of MP){ctx.fillStyle=hue(p.g);ctx.beginPath();ctx.arc(ppx(p.x),ppy(p.y),3.5,0,7);ctx.fill();}}
function presize(){cv.width=cv.parentElement.clientWidth;cv.height=cv.parentElement.clientHeight;pdraw();}
window.addEventListener('resize',()=>{presize();vresize();});
fetch('/map').then(r=>r.json()).then(p=>{MP=p;pmin={x0:Math.min(...p.map(d=>d.x)),x1:Math.max(...p.map(d=>d.x)),
 y0:Math.min(...p.map(d=>d.y)),y1:Math.max(...p.map(d=>d.y))};presize();});
cv.addEventListener('mousemove',e=>{const r=cv.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
 let b=null,bd=120;for(const p of MP){const dx=ppx(p.x)-mx,dy=ppy(p.y)-my,dd=dx*dx+dy*dy;if(dd<bd){bd=dd;b=p;}}
 if(b){tip.style.display='block';tip.style.left=(mx+12)+'px';tip.style.top=(my+12)+'px';tip.innerHTML='<b>'+b.lab+'</b><br><span class=g>'+b.g+'</span>';cv._h=b;cv.style.cursor='pointer';}else{tip.style.display='none';cv._h=null;}});
cv.addEventListener('click',()=>{if(cv._h){const nm=cv._h.lab.split(' - ');play({id:cv._h.id,artist:nm[0]||cv._h.lab,title:nm.slice(1).join(' - '),g:cv._h.g});}});

// ---- VGM tab ----
let VG=[],proj='style',focus=new Set();
const vcv=document.getElementById('vcv'),vctx=vcv.getContext('2d'),vtip=document.getElementById('vtip');
function vx(p){return proj==='style'?p.sx:p.tx} function vy(p){return proj==='style'?p.sy:p.ty}
let vb={};
function vbounds(){const X=VG.map(vx),Y=VG.map(vy);vb={x0:Math.min(...X),x1:Math.max(...X),y0:Math.min(...Y),y1:Math.max(...Y)};}
const vpx=x=>50+(x-vb.x0)/(vb.x1-vb.x0||1)*(vcv.width-100),vpy=y=>vcv.height-46-(y-vb.y0)/(vb.y1-vb.y0||1)*(vcv.height-92);
function vdraw(){if(!VG.length)return;vctx.clearRect(0,0,vcv.width,vcv.height);
 if(proj==='style'){vctx.fillStyle='#888';vctx.font='12px sans-serif';
  vctx.fillText('orchestral -> chiptune',vcv.width/2-55,vcv.height-12);
  vctx.save();vctx.translate(15,vcv.height/2+45);vctx.rotate(-Math.PI/2);vctx.fillText('calm/town -> battle/intense',0,0);vctx.restore();}
 for(const p of VG){const on=focus.size===0||focus.has(p.series);
  vctx.fillStyle=on?hue(p.series):'#2c2f36';vctx.beginPath();vctx.arc(vpx(vx(p)),vpy(vy(p)),on?4:2.5,0,7);vctx.fill();}}
function vresize(){vcv.width=vcv.parentElement.clientWidth;vcv.height=vcv.parentElement.clientHeight;if(VG.length){vbounds();vdraw();}}
function toggleProj(){proj=proj==='style'?'tsne':'style';document.getElementById('pn').textContent=proj==='style'?'style axes':'t-SNE';vbounds();vdraw();}
function loadVGM(){fetch('/vgm').then(r=>r.json()).then(p=>{VG=p;
 const cnt={};VG.forEach(t=>cnt[t.series]=(cnt[t.series]||0)+1);
 const top=Object.keys(cnt).sort((a,b)=>cnt[b]-cnt[a]).slice(0,16);
 const lg=document.getElementById('legend');lg.innerHTML='';
 top.forEach(s=>{const c=document.createElement('span');c.className='chip';c.style.borderColor=hue(s);c.style.color=hue(s);
  c.textContent=s+' ('+cnt[s]+')';c.onclick=()=>{focus.has(s)?focus.delete(s):focus.add(s);
   c.style.background=focus.has(s)?hue(s):'transparent';c.style.color=focus.has(s)?'#000':hue(s);vdraw();};lg.appendChild(c);});
 vresize();});}
vcv.addEventListener('mousemove',e=>{const r=vcv.getBoundingClientRect(),mx=e.clientX-r.left,my=e.clientY-r.top;
 let b=null,bd=150;for(const p of VG){if(focus.size&&!focus.has(p.series))continue;const dx=vpx(vx(p))-mx,dy=vpy(vy(p))-my,dd=dx*dx+dy*dy;if(dd<bd){bd=dd;b=p;}}
 if(b){vtip.style.display='block';vtip.style.left=(mx+12)+'px';vtip.style.top=(my+12)+'px';
  vtip.innerHTML='<b>'+b.artist+' - '+b.title+'</b><br><span class=g>'+b.series+' &middot; '+b.type+'</span><br><span style="color:#9cf">'+b.label+'</span>';vcv._h=b;vcv.style.cursor='pointer';}
 else{vtip.style.display='none';vcv._h=null;}});
vcv.addEventListener('click',()=>{if(vcv._h)play({id:vcv._h.id,artist:vcv._h.artist,title:vcv._h.title,g:vcv._h.series});});
</script></body></html>"""


if __name__ == "__main__":
    app.run(host="127.0.0.1", port=5000)
