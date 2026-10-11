# Music Player UI — Build Plan

Synthesized from a survey of the leading OSS players (Navidrome, Feishin, Supersonic, Koel,
Jellyfin, Tauon…) + research on discovery UIs, the front-end stack, and "pro-feel" details.
Goal: turn the current minimal Flask + vanilla-JS app into a real, polished, local-first player
that showcases our unique engine (MuQ-MuLan semantic search, embedding maps, hybrid autoplay).

## 0. Strategic framing — where we actually differentiate

Semantic/mood search and 2D embedding maps are **no longer a green field** as of mid-2026:
- **AudioMuse-AI** ships text→music search + a "Music Map" (but heavy: ~8GB RAM, Flask+worker+Postgres, plugin into other servers).
- **Familiar** ships CLAP natural-language search + Mood Grid / Music Map / 3D Explorer.

So we do **not** claim "first/only." Our real edges:
1. **Model quality** — MuQ-MuLan is newer/stronger than the CLAP/MusicNN/Deej-AI these use (we measured it: 9.6–14× artist coherence vs CLAP's 2.5×). Benchmark it as a concrete edge.
2. **Hybrid *sonic* radio/autoplay = the clearest white space.** Native "instant mix" (Navidrome/Jellyfin) is genre/artist-*metadata* only; AudioMuse is sonic but plugin-dependent; Familiar has **no radio at all**. A polished integrated sonic+collaborative radio is the least-served need.
3. **Cohesive all-in-one lightweight player** — every competitor is a plugin, middleware, or heavyweight backend. One clean app is itself a differentiator.
4. **"Discover within YOUR own collection"** — not "recommend music you don't own" (the ListenBrainz/Explo path). Distinct, well-supported framing.

The #1 documented gap in self-hosted players is exactly this discovery layer ("a library without a librarian"). That's our lane.

## 1. Stack decision (recommended)

| Concern | Choice | Why |
|---|---|---|
| Framework | **Svelte 5 + Vite** (SPA, `ssr:false`; not SvelteKit) | tiny runtime, compiler/fine-grained reactivity, gentlest ramp for a Python dev; a real player is too stateful for vanilla. Fallback: SolidJS. |
| Audio | native `<audio>` → `MediaElementAudioSourceNode` → `GainNode` | reliable seek (Range), free OS media keys (MediaSession), loudness + fades at zero memory cost. **Skip Howler** (stalled). |
| Map | **regl-scatterplot** (WebGL) | millions of points, built-in hover/click/lasso + density opacity; likely *deletes* our hand-rolled canvas. |
| Lists | **virtua** (virtualized) | render 50k tracks without melting the DOM. |
| State | Svelte 5 runes (+ nanostores if decoupling wanted) | single-user → no Redux-class tooling. |
| Library search | **server-side SQLite FTS5** | Fuse.js is linear/weak at 50k; FTS5 = inverted index + bm25, ~20ms. (Keep `/search` MuQ endpoint for *semantic* search — different feature.) |
| Persistence | **IndexedDB** via `idb` | queue/history/now-playing across reloads (localStorage too small/sync). |
| Packaging | localhost page → **PWA** → **Tauri v2** later | stays portable for the eventual device; not Electron. |
| Backend | **unchanged Flask** | it's already the right JSON + Range-audio contract. |

## 2. Information architecture — the three-zone "Spotify shell"

Every mature player converges here; copying it = zero learning curve.
- **Left sidebar (~240px, fixed):** Search · Home · Library (**Albums / Artists / Genres / Songs**) · Favorites · **Discover (Map / Mood / Radio)** · Playlists (drag-drop targets) · Settings (pinned bottom).
- **Center (scrolls):** album-art grid for browse; sortable **virtualized** track tables; **album & artist detail pages** (big art header + Play/Shuffle + track table); the **Map** view; **Mood-search** results.
- **Bottom now-playing bar (fixed, full width):** art + title/artist + like · shuffle/prev/**play**/next/repeat + **seek** · volume / **queue toggle** / fullscreen.
- **Right slide-out Queue panel** (drag-reorder) + a **full-screen Now-Playing** (art-color themed).

## 3. Feature set — phased

**P0 — MVP / table-stakes (makes it a real player):**
- Three-zone shell; album grid + virtualized track table; album/artist detail pages
- Server-side full-library search (FTS5)
- Queue with **"Play next" vs "Add to queue"** split (Supersonic pattern) + drag-reorder
- Now-playing bar: play/pause/**seek**/shuffle/repeat(+one)
- Playlists (create/add/remove/reorder); Favorites/stars
- **MediaSession** (OS media keys, lock-screen art) + keyboard shortcuts (space, ←/→ seek, ↑/↓ vol, etc.)
- Raw Opus + **HTTP Range** serving (`send_file(conditional=True)`)
- **Loudness normalization** (rsgain → Opus R128 tags; fixes "wildly different volumes")
- Queue/now-playing persistence (IndexedDB)

**P1 — the differentiators (our reason to exist):**
- **Mood search panel** (MuQ text→music): example prompt tiles, inline preview + play, per-result match + a one-line "why this matched", editable/iterative prompt, optional facet filters.
- **Map browser** (regl-scatterplot): default to a **MuQ-text-anchored valence×energy plane**; **hover-to-audition** + click-to-play; a typed mood **drops a labeled pin** among matches; **lasso a region → playlist**; **VGM sub-map colored by game series**; pan/zoom + semantic-zoom label declutter (fixing Every Noise's clutter).
- **Hybrid Radio / "carry the vibe"**: seed from a track *or* a mood; endless on-vibe queue (MuQ audio + collaborative co-occurrence); **coarse "explore" dial** (neighbor radius) + **per-track more/less-like-this**; draw the **autoplay trail on the map**; "why this song" line.
- **Play tracking** (scrobble-rule: >30s & ≥half or 4min; record skips as negative) → feeds the collaborative engine.

**P2 — polish (punch above weight):**
- Synced lyrics (LRCLIB); album-art color theming + full-screen NP
- Crossfade now / true gapless later (Web Audio AudioBuffer or Gapless-5) — matters for segue-heavy VGM
- Scrobbling to Last.fm / ListenBrainz; themes; multi-select bulk actions
- PWA install; precomputed waveform peaks (BBC audiowaveform) only if wanted

## 4. What we reuse vs. replace

- **Reuse:** the Flask backend + endpoints (`/map`, `/vgm`, `/search`, `/next`, `/audio`), MuQ embeddings (`muq_embeddings.npz`), `clusters.csv`, `vgm.csv`, `autoplay_config.json`, the autoplay/eval logic.
- **Replace:** the single inline-HTML page + hand-rolled canvas + raw `<audio>` → Svelte components + regl-scatterplot + the `<audio>`→GainNode engine module.
- **Add (backend):** FTS5 library index; album/artist/library JSON endpoints; play-tracking endpoint; rsgain loudness tags; confirm Range via `send_file(conditional=True)`.
- Keep the current `app.py` working alongside during the migration (incremental, view-by-view — no big-bang rewrite; backend doesn't move).

## 5. Build order

1. **Backend prep:** `send_file(conditional=True)` range audio; SQLite FTS5 index; album/artist/library JSON; play-tracking endpoint; rsgain-tag the Opus library for loudness.
2. **Frontend skeleton:** Vite + Svelte 5; three-zone shell talking to existing endpoints.
3. **Audio engine module:** `<audio>`→`GainNode`; queue (array+index); MediaSession; keyboard; IndexedDB persistence.
4. **Library views:** virtualized track table + album grid + album/artist detail + server search.
5. **Differentiators:** Mood search panel → Map browser (regl-scatterplot) → Hybrid Radio.
6. **Polish:** lyrics, theming, gapless, scrobbling, PWA.

## 6. Notes / risks

- iOS Safari plays Ogg-Opus only ≥18.4 — only matters if used on an iPhone; we control the browser otherwise.
- Don't transcode (single-user, local, Opus-native browser) — just serve raw bytes with Range.
- Don't claim "first" at semantic search; lead with radio + model quality + integrated UX.
