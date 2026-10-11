#!/usr/bin/env python3
"""Create ytmusicapi browser auth (auth/browser.json) from pasted request headers,
without the awkward interactive paste-then-EOF flow.

Steps:
  1. In Firefox, logged into https://music.youtube.com:
       F12 -> Network tab -> click any POST request to a `/browse` URL
       -> right-click -> Copy -> Copy Request Headers
     (Chrome: copy the request as cURL, or copy the raw headers block.)
  2. Paste that whole block into  auth/headers_raw.txt
  3. Run:  .venv\\Scripts\\python scripts/setup_auth.py

The generated auth/browser.json is what harvest_radios.py uses. It contains your
session cookie -- it's gitignored; keep it private.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from ytmusicapi import setup as ytmusic_setup
from ytmusicapi.helpers import get_authorization, sapisid_from_cookie

RAW = Path("auth/headers_raw.txt")
OUT = Path("auth/browser.json")


def ensure_authorization(out: Path) -> None:
    """ytmusicapi only detects BROWSER auth when an `authorization: SAPISIDHASH ...`
    header is present, but cookie-only requests (e.g. /api/stats/playback) don't carry
    one. The real value is recomputed from the cookie on every request, so we just need
    *an* authorization entry present for detection. Derive it from the cookie."""
    data = json.loads(out.read_text(encoding="utf-8"))
    if any(k.lower() == "authorization" for k in data):
        return
    cookie = next((v for k, v in data.items() if k.lower() == "cookie"), None)
    origin = next((v for k, v in data.items() if k.lower() == "origin"),
                  "https://music.youtube.com")
    if not cookie:
        raise SystemExit("error: no cookie found in headers — copy headers from a "
                         "logged-in YouTube Music request.")
    try:
        sapisid = sapisid_from_cookie(cookie)
    except KeyError:
        raise SystemExit("error: cookie has no __Secure-3PAPISID — make sure you're "
                         "logged in and copied the full Cookie header.")
    data["authorization"] = get_authorization(sapisid + " " + origin)
    out.write_text(json.dumps(data, indent=4, sort_keys=True), encoding="utf-8")


def main() -> int:
    if not RAW.exists():
        print(f"error: {RAW} not found.\n"
              f"Paste your YouTube Music request headers into {RAW} first "
              f"(see this script's docstring).", file=sys.stderr)
        return 1
    raw = RAW.read_text(encoding="utf-8").strip()
    if not raw:
        print(f"error: {RAW} is empty.", file=sys.stderr)
        return 1
    OUT.parent.mkdir(parents=True, exist_ok=True)
    ytmusic_setup(filepath=str(OUT), headers_raw=raw)
    ensure_authorization(OUT)
    print(f"Wrote {OUT}")
    print("Test it:  .venv\\Scripts\\python -c \"from ytmusicapi import YTMusic; "
          "print(len(YTMusic('auth/browser.json').get_liked_songs(limit=5)['tracks']), 'liked tracks')\"")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
