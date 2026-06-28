# Scaling collection to ~50k — experiment results & plan (mid-2026)

Goal: grow the library toward ~50,000 tracks. I surveyed the methods (yt-dlp docs/issues
plus community reports) and ran controlled download tests. **Bottom line: download *speed* is not the
constraint — YouTube's per-IP request *budget* is — and the real unlock is using
non-YouTube sources for the VGM bulk.**

## Empirical tests (android_vr, anonymous, real candidates, kept+tagged)

| Config | Setup | Throughput | Errors |
|--------|-------|-----------:|--------|
| A | sequential, sleep 2/2 | 10.2 /min | 0 |
| B | sequential, sleep 0.4 | 23.9 /min | 0 |
| C | concurrency 3, no sleep | 83.7 /min | 0 |

All clean — but only because each was a small burst. **84/min ≈ 5,000/hr, ~16× over the
sustainable ceiling**, so it would trip the block within minutes. Per-track audio is
~3 MB (opus 251 ~144k).

## What the research found (verified vs yt-dlp wiki/issues)

**The binding limit is a per-IP request budget:**
- **~300 videos/hr anonymous**, **~2,000/hr with account cookies** (~6.5×).
- Exceeding it → "content isn't available, try again later" = session block **~1 hr**
  (24–48 hr under heavy abuse). **No confirmed permanent residential-IP ban** at personal
  scale (one report of a hard block only after ~124k videos). Router reboot / new DHCP
  lease clears it.
- Sustainable residential reality: **~2–4k/day** (anon), ~3–6k/day (throwaway cookies).

**What does NOT help (don't bother):**
- **aria2c** — useless/slower for small audio (maintainer-confirmed, #7962).
- **High concurrency / `-N`** — shares the per-IP budget, trips the block *sooner*, looks
  more bot-like; SABR is removing DASH audio so `-N` has little to parallelize. Cap 1–3.
- **PO tokens / premium cookies for speed** — tokens gate format *access*, not throughput.
  Premium 256k (opus 774) is ~inaudible vs 251 and carries account-ban risk. Skip.
- **Datacenter VPNs** — flagged *before* cookies; makes it worse. Only residential/mobile
  proxies help (scripted rotation), which is the only true way to exceed one IP's budget.

**What DOES help:**
- **`--download-archive`** (resumable, skips finished IDs with no request) — already used.
- **Sleep pacing** to stay under ~300/hr: `--sleep-requests ~1 --sleep-interval 3–8
  --max-sleep-interval ~15`. Sleep beats `--limit-rate` (detection is request-pattern).
- **External 429 backoff** (yt-dlp won't auto-retry 429): on block, sleep ≥1 hr, resume.
- **Multi-source** (the big one) — see below.
- A **throwaway** Google account's cookies raise the ceiling to ~2k/hr (never the main account).

## Recommended plan: split the load by source

Most of the library is **VGM**, which has dedicated **lossless, no-rate-limit** sources.
Pull the bulk there; use YouTube only for genuinely exclusive tracks.

| Source | Best for | Notes |
|--------|----------|-------|
| **Khinsider** (~3.1M VGM) | game OSTs | self-throttle ~1–2s, real UA |
| **OC ReMix / VGMRips / Zophar** | arrangements, chip rips | **official torrents = zero risk** |
| **Internet Archive** | OST collections | ZIP/torrent, no cap |
| **Bandcamp** | bought artists (Rozen, etc.), FLAC | ~3 concurrent |
| **YouTube** (anon, safe tier) | fan covers / future-funk / exclusives | ~250/hr, archive, sleep |

**Timeline:** all-YouTube ≈ 2–4 weeks. Multi-source: VGM OSTs/remixes arrive in days
(lossless, ban-free), leaving ~15–20k for YouTube → roughly halves the calendar.

## Recommended YouTube settings (safe tier)
```
player_client=android_vr (anonymous, no PO token needed — verified working here)
--download-archive  --sleep-interval 3 --max-sleep-interval 10 --sleep-requests 1
concurrency 1–2, opus 251.  On 429: pause ≥1 hr, then resume (archive makes it free).
```

## Decision (what we actually chose)

Multi-source (Khinsider/IA/OCReMix) was **declined** — it skews to official OSTs, and the
goal is curated discovery (covers, remixes, future-funk), not OST completion. So:

- **Acquire via public-playlist mining**, all through yt-dlp/YouTube (`harvest_playlists.py`
  → `build_queue.py` → `curate.py` → `download_tracks.py`).
- **Raise the rate ceiling with a throwaway-account cookie + the `tv` client** (~2k/hr vs
  ~300/hr anon). The `tv` client serves audio *without* a PO token and accepts cookies, so
  the bgutil/Deno PO-token-server route was dropped (it also failed to build in this env).
  `android_vr` (anon) still works as the no-cookie fallback but went erratic / started 403ing
  under heavy single-IP load — hence the cookie route. Never use the main Google account.
- Keep `--download-archive` + sleep pacing + 403/429 auto-backoff; run it in a real terminal
  (background jobs die on session idle). Multi-source remains a documented fallback if needed.

## Sources
yt-dlp Extractors wiki (rate limits) · PO-Token-Guide · issues #7962 (aria2c), #16128
(SABR), #10085 (account block), #9890 (124k IP block) · Khinsider/OCReMix/Internet Archive.
