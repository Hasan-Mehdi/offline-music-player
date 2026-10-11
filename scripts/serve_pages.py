#!/usr/bin/env python3
"""LAN hub for the project's standalone HTML pages (review tools, demos, maps, films).

Serves viz/ plus data/purge_review.html on 0.0.0.0 so any device on the local
network can open them. Deliberately NOT rooted at the repo (cookies.txt, auth/
must never be reachable). HTML responses get their hard-coded 127.0.0.1:5000
audio-preview URLs rewritten to this machine's address, so previews work from
other devices whenever the player server is reachable on the network too.

Usage:
    python scripts/serve_pages.py [--port 8788]
"""
from __future__ import annotations

import argparse
import socket
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VIZ = ROOT / "viz"
PURGE = ROOT / "data" / "purge_review.html"

PAGES = [
    ("autoplay_ab.html", "Autoplay A/B — old vs new formula, side by side"),
    ("dupe_review.html", "Duplicate rips — review & export removal list"),
    ("/purge", "Purge audit — taste contamination review"),
    ("genre_map.html", "Genre map"),
    ("vgm_map.html", "VGM space"),
    ("film/embedding_space_film.html", "Embedding-space explainer film"),
    ("transit/transit.html", "Night Service — transit showcase"),
    ("think/think_film.html", "Watching it think — the autoplay engine, one decision at a time"),
]

INDEX = """<!doctype html><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>OMP — pages</title>
<style>
 body{background:#f4f4f0;color:#141414;font:16px/1.5 system-ui,sans-serif;
      max-width:640px;margin:48px auto;padding:0 20px}
 h1{font-family:"Archivo Black","Arial Black",sans-serif;font-size:40px;
    letter-spacing:-1px;margin:0 0 4px;border-bottom:6px solid #141414}
 p.k{color:#555;margin:6px 0 28px}
 a{display:block;color:#002fa7;text-decoration:none;font-weight:600;
   padding:14px 2px;border-bottom:1px solid #d8d8d2}
 a:hover{background:#ecece6}
 a span{display:block;color:#555;font-weight:400;font-size:13px}
</style>
<h1>OFFLINE MUSIC PLAYER</h1><p class="k">review tools &amp; demos on this network</p>
{LINKS}
"""


def lan_ip() -> str:
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        return s.getsockname()[0]
    except OSError:
        return "127.0.0.1"
    finally:
        s.close()


class Handler(SimpleHTTPRequestHandler):
    def do_GET(self):  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path in ("/", "/index.html"):
            links = "\n".join(
                f'<a href="{href}">{label.split(" — ")[0]}<span>'
                f'{label.split(" — ")[1] if " — " in label else ""}</span></a>'
                for href, label in PAGES
                if href == "/purge" or (VIZ / href).exists()
            )
            self._send_html(INDEX.replace("{LINKS}", links).encode("utf-8"))
            return
        if path == "/purge":
            if PURGE.exists():
                self._send_html(self._rewrite(PURGE.read_bytes()))
            else:
                self.send_error(404, "purge_review.html not generated yet")
            return
        if path.endswith(".html"):
            f = (VIZ / path.lstrip("/")).resolve()
            if VIZ.resolve() in f.parents and f.exists():
                self._send_html(self._rewrite(f.read_bytes()))
                return
        super().do_GET()

    def _rewrite(self, body: bytes) -> bytes:
        # preview links are baked as 127.0.0.1:5000; point them at this host
        # instead so they work from other devices on the network
        host = (self.headers.get("Host") or "").split(":")[0] or "127.0.0.1"
        return body.replace(b"127.0.0.1:5000", f"{host}:5000".encode())

    def _send_html(self, body: bytes):
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, fmt, *args):
        pass  # keep the background log quiet


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8788)
    args = ap.parse_args()
    srv = ThreadingHTTPServer(
        ("0.0.0.0", args.port), partial(Handler, directory=str(VIZ)))
    print(f"serving viz/ + /purge on:")
    print(f"  this machine   http://127.0.0.1:{args.port}/")
    print(f"  on the network http://{lan_ip()}:{args.port}/", flush=True)
    srv.serve_forever()


if __name__ == "__main__":
    main()
