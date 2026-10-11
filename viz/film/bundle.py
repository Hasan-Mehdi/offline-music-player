#!/usr/bin/env python3
"""Inline film_data.json into film.html -> embedding_space_film.html (double-clickable,
fully self-contained: font + covers + audio are already base64 inside the JSON)."""
from pathlib import Path

HERE = Path(__file__).resolve().parent
html = (HERE / "film.html").read_text(encoding="utf-8")
data = (HERE / "film_data.json").read_text(encoding="utf-8")
data = data.replace("</", "<\\/")                       # keep any '</script>' from closing the tag

marker = '<script>\n"use strict";'
assert marker in html, "main script marker not found"
inject = f'<script>window.__FILM_DATA__={data};</script>\n' + marker
html = html.replace(marker, inject, 1)

out = HERE / "embedding_space_film.html"
out.write_text(html, encoding="utf-8")
print(f"wrote {out}  ({out.stat().st_size/1e6:.2f} MB, standalone)")
