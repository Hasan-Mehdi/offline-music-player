# Download path — definitive state (2026-06-27)

## TL;DR
Download with **`android_vr`** (guest, no cookies). It is the only client that returns
clean native Opus (251, ~144k) with **no PO-token server and no DRM**. Run it from your
own terminal so it survives:

```powershell
powershell -ExecutionPolicy Bypass -File scripts\download.ps1
```

It paces itself, auto-backs-off on 403/rate-limits, and resumes via `data/downloaded.txt`
(safe to Ctrl+C and rerun). Default input is the diversified `data/download_queue.csv`;
pass `-InputCsv data\candidates.csv` for the radio pool.

## What we tested, and why the "fast" paths are dead ends
The goal was the authenticated ~6× higher rate ceiling (a cookie-capable client).
Every cookie-capable client failed:

| Client | Cookies? | Result |
|--------|----------|--------|
| **android_vr** | ignored | ✅ clean Opus 251, no DRM, no token — **USE THIS** (but guest ceiling) |
| `tv` | yes | ❌ **DRM-locked** for our session (yt-dlp #12563: YouTube A/B experiment applies DRM to *all* videos on the tv client). Briefly worked (25/25) then the experiment flipped on mid-run. |
| `mweb` | yes | ❌ requires a GVS **PO token** |
| `ios` | yes | ❌ requires a GVS **PO token** |
| `web`/`web_safari` | yes | ❌ require a PO token |

A PO token needs the **bgutil** provider, which needs either a native `canvas` build
(node-gyp + VS C++ build tools + Cairo on Windows — fails) or **Docker** (not installed).
So the authenticated ceiling is **not reachable for free** on this machine.

### The one genuinely useful discovery
The `tv` client's n-challenge/signature solving needs a JS runtime. The fix is NOT bgutil:
`pip install yt-dlp-ejs` + Node + `--js-runtime node` (wired into download_tracks.py).
This made `tv` work for ~25 downloads before the DRM experiment killed it. Kept enabled
by default (harmless for android_vr, which never invokes the solver). If YouTube ever
ends the tv DRM experiment, `tv`+cookies+node becomes the authenticated path again.

## Rate reality for the 50k goal
android_vr is a **guest** client → YouTube's per-IP guest ceiling (~300/hr in bursts,
roughly a couple thousand/day before soft-blocks; the backoff rides those out).
- The unified candidate pool is ~29k unique tracks today, so **reaching a literal 50k
  also needs more harvesting**, not just downloading.
- On a single home IP this is a **multi-week unattended grind**. The only real speed
  levers are (a) a working PO-token server → authenticated client, or (b) residential
  proxies (paid) to multiply the per-IP budget. Neither is set up.

## Diversification (honoring "not too much rap / don't focus on game OSTs")
`scripts/curate.py` now (rebuilt `download_queue.csv`, 10,146 tracks):
- caps hip-hop ≤12% (now ~7%) and **VGM/chiptune/orchestral covers ≤~15%** (genre- AND
  title-detected), down from ~35% — present, not dominant.
- **genre round-robin interleave** so the download ORDER is diverse from track 1 instead
  of front-loading thousands of VGM covers (many of which are DRM dead-ends on `tv`).
- version-preserving dedupe + per-artist cap (35) retained.

## Per-video guest login-locks (2026-07-05, ~30.8k/46.6k into the run)
"Sign in to confirm you're not a bot" turned out to be **per-video**, not an IP flag:
specific videos (official anime OPs — TOHO animation, YOASOBI; Sonic fangame OSTs)
bot-check on EVERY guest client (android_vr, web_embedded, web) while the rest of the
queue keeps downloading from the same IP. yt-dlp 2026.7.4 doesn't change it; these
videos need the authenticated/POT path.

Bug this exposed in `download_tracks.py`: the message matched neither the rate-limit
nor the age-gate classifier → classified "fail" → the search fallback fired an extra
(also-blocked) request per track and logged live tracks as MISSING at full speed.
Fixed with a third status `"auth"`:
- locked videos are skipped and logged to **`data/auth_required.csv`** (like
  age_restricted.csv, for the future authenticated run);
- the **search fallback still runs** for them — alternate uploads are often unlocked
  (a `new_id != vid` guard stops re-fetching the locked original, which is usually
  the top search hit);
- after 10 consecutive auth-locks a **canary probe** (known-good video) distinguishes
  a true IP-level bot-flag → escalating cool-down / abort as before.
