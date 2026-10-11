#!/usr/bin/env python3
"""Inline coda_data.json, the fonts, every image and the three audio clips into coda.html
-> coda_film.html (double-clickable, works offline from disk, no network at all).

Rebuild:  .venv\\Scripts\\python viz\\coda\\bundle.py
"""
import base64
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
A = HERE / "assets"
MIME = {".png": "image/png", ".jpg": "image/jpeg", ".m4a": "audio/mp4", ".woff2": "font/woff2"}

html = (HERE / "coda.html").read_text(encoding="utf-8")
data = json.loads((HERE / "coda_data.json").read_text(encoding="utf-8"))


def uri(name):
    f = A / name
    return f"data:{MIME[f.suffix]};base64," + base64.b64encode(f.read_bytes()).decode()


for font in ["archivo-black-400", "archivo-400", "archivo-600", "inconsolata-500"]:
    ref = f"url('assets/{font}.woff2')"
    assert ref in html, ref
    html = html.replace(ref, f"url('{uri(font + '.woff2')}')")

names = (["covers.jpg", "cands.jpg", "pairs.jpg", "web.png", "fp_hero.jpg", "fp_near.jpg", "fp_far.jpg"]
         + [s + ".png" for s in data["media"]["screens"]] + data["media"]["boot"]
         + data["media"]["themes"] + [c["file"] for c in data["clips"].values()])
media = {n: uri(n) for n in names}

payload = (json.dumps(data, ensure_ascii=False).replace("</", "<\\/"),
           json.dumps(media).replace("</", "<\\/"))
marker = '<script>\n"use strict";'
assert marker in html, "main script marker not found"
html = html.replace(marker, f"<script>window.__CODA_DATA__={payload[0]};"
                            f"window.__CODA_MEDIA__={payload[1]};</script>\n" + marker, 1)
out = HERE / "coda_film.html"
out.write_text(html, encoding="utf-8")
print(f"wrote {out}  ({out.stat().st_size / 1e6:.2f} MB, standalone, {len(media)} media files)")
