# The Shape of a Music Library — an embedding-space motion film

A ~99-second motion-graphics film that explains the recommendation engine to a person,
built entirely from **real data** in this repo: 8,000 tracks sampled from the MuQ-MuLan
audio embeddings, projected with t-SNE, semantically genre-labelled by the model's own
text encoder, with **real audio snippets and real cover art** from `D:\OfflineMusic`.

Design direction: `DIRECTION.md` ("star-atlas plate in motion"). Motion technique follows
standard motion-graphics craft (eased/staggered particle→position morph, additive-glow
bokeh depth, log-space virtual camera, kinetic clip-up type) — see `../../docs` context.

## Watch it
- **`embedding_space_film.html`** — double-click it. Self-contained (font + covers + audio
  all inlined, ~2.3 MB). Click **PLAY THE FILM** for sound. Space = play/pause, R = replay.
- **`embedding_space_film.mp4`** — the rendered video with the real audio muxed in (shareable).

## The seven beats
1. **Hook** — one point in the dark: "What does a music library actually look like?"
2. **Build** — 8,000 tracks fly in as points ("512 numbers for how each one sounds").
3. **Reveal** — the cloud sorts itself into genre constellations; labels ignite. *No genres
   were given to the model* — the structure is what it heard.
4. **Zoom** — camera dives into the future-funk / city-pop neighbourhood; real covers bloom
   (Snail's House, Toshikii, Mario/Sonic chiptune, Protocols).
5. **Text→music** — type a feeling ("nostalgic future funk at night"); a beam lands among the
   true matches; a panel shows the real top-3 with cosine scores.
6. **Autoplay** — a red path walks the space by audio-similarity, staying in the mood.
7. **Payoff** — pull back to the whole labelled galaxy: "A library you can wander by feel."

## Rebuild (from repo root)
```
python viz/film/build_data.py            # -> film_data.json (+ assets/*.m4a clips, cover art)
                                         #    add --force to recompute t-SNE/MuQ (else cached)
python viz/film/bundle.py                # -> embedding_space_film.html (standalone)
node   viz/film/capture.js render 30     # -> frames/*.png  (+ audio_cues.json)
python viz/film/mux.py video 30          # frames + real-audio master -> embedding_space_film.mp4
```
`capture.js preview [t...]` renders stills at given times → `preview/` (for iterating).

## Files
- `build_data.py` — data precompute (sample, MuQ genre labels, t-SNE, autoplay walk, mood
  queries, clip + art extraction). Caches the heavy stage in `_cache.npz`.
- `film.html` — the film engine (canvas + WebAudio, frame-driven deterministic clock).
- `capture.js` — headless-Edge harness (preview stills / full frame render / cue dump).
- `mux.py` — builds the master audio from cues+clips and muxes with frames (ffmpeg).
- `bundle.py` — inlines the data into a single double-clickable HTML.
