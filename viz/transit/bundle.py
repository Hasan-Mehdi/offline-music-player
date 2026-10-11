#!/usr/bin/env python3
"""Inline transit_data.json + the Archivo Black woff2 into transit.html
-> wayfinding_film.html (double-clickable, fully self-contained)."""
import base64
from pathlib import Path

HERE = Path(__file__).resolve().parent
html = (HERE / "transit.html").read_text(encoding="utf-8")
data = (HERE / "transit_data.json").read_text(encoding="utf-8")
data = data.replace("</", "<\\/")                     # keep '</script>' from closing the tag

font = base64.b64encode((HERE / "assets" / "archivo-black-400.woff2").read_bytes()).decode()
html = html.replace("url('assets/archivo-black-400.woff2')",
                    f"url('data:font/woff2;base64,{font}')")

marker = '<script>\n"use strict";'
assert marker in html, "main script marker not found"
html = html.replace(marker, f'<script>window.__TRANSIT_DATA__={data};</script>\n' + marker, 1)

out = HERE / "wayfinding_film.html"
out.write_text(html, encoding="utf-8")
print(f"wrote {out}  ({out.stat().st_size/1e6:.2f} MB, standalone)")
