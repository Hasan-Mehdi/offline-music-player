#!/usr/bin/env python3
"""Inline think_data.json + the Archivo Black woff2 into think.html
-> think_film.html (double-clickable, works offline from disk, no network at all).

Rebuild:  .venv\\Scripts\\python viz\\think\\bundle.py
"""
import base64
from pathlib import Path

HERE = Path(__file__).resolve().parent
html = (HERE / "think.html").read_text(encoding="utf-8")
data = (HERE / "think_data.json").read_text(encoding="utf-8")
data = data.replace("</", "<\\/")            # keep a '</script>' inside a title from closing the tag

font = base64.b64encode((HERE / "assets" / "archivo-black-400.woff2").read_bytes()).decode()
assert "url('assets/archivo-black-400.woff2')" in html, "font url not found"
html = html.replace("url('assets/archivo-black-400.woff2')",
                    f"url('data:font/woff2;base64,{font}')")

marker = '<script>\n"use strict";'
assert marker in html, "main script marker not found"
html = html.replace(marker, f'<script>window.__THINK_DATA__={data};</script>\n' + marker, 1)

out = HERE / "think_film.html"
out.write_text(html, encoding="utf-8")
print(f"wrote {out}  ({out.stat().st_size / 1e6:.2f} MB, standalone)")
