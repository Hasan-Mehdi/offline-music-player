# Offline Music Player

A personal, fully-offline music player with YouTube-Music-style autoplay (semantic
similarity + collaborative association) over a self-collected library. Built and
**validated on real data** — see `docs/EXPERIMENTS.md` for measured findings,
`docs/COLLECTION_SCALING.md` for the download-scaling research, and `docs/REPORT.md`
for the latest full-suite run.

Personal side project, still active. This repo is code, docs, and measured results only —
the audio library, the MuQ/CLAP embeddings, and the model weights are **not included**
(too big, and partly personal). Bring your own music: drop `.opus` files in a folder and
point the scripts at it with the `MUSIC_DIR` env var (defaults to `./music`).

## Status

- **Collection:** ~2,000+ tracks downloaded; a ~13k diversified queue ready. Target: **~50k**.
  Sources, in confidence order: YT history (Takeout) → song radios → public-playlist mining.
  The only real bottleneck is YouTube's per-IP rate limit (~300/hr anon, ~2k/hr with a
  throwaway-account cookie) — so downloading is a multi-day background grind, not a code limit.
- **Algorithm:** custom hybrid, all measured offline:
  - Collaborative `pos + song2vec` — **+32%** recall@50 over raw co-occurrence.
  - Content **MuQ-MuLan** — artist-coherence **~10–14×**, working **text→music** (CLAP failed, dropped).
  - Hybrid **autoplay** (audio vibe + collaborative + diversity + exploration).
- **Frontend:** local Flask web player (`app.py`) — genre map, mood search, autoplay, VGM Space tab.

## Architecture — we built our own stack

Originally the plan was to "buy" the algorithm layer (AudioMuse-AI). Experiments showed a
custom stack does better for this library, so we build:

| Layer | Choice | Why |
|-------|--------|-----|
| Playlist / daily-mix | collaborative `pos + song2vec` | +32% vs baseline, rigorously measured |
| Semantic search ("type a mood") | MuQ-MuLan text→music | works; CLAP was anisotropic/broken |
| Autoplay | MuQ audio vibe + collaborative + MMR diversity + ε-explore | coherent, on-taste journeys |
| Browse UI | personal "Every Noise" genre map + VGM sub-space | interpretable axes + interactive |

MBIDs (beets/MusicBrainz) remain an optional bridge if we later add ListenBrainz/Troi.

## Scripts

**Collection (acquire the library — all yt-dlp / ytmusicapi)**
- `parse_takeout_history.py` — Takeout watch-history → frequency/recency-weighted seeds
- `setup_auth.py` — YT Music browser auth (cookie → `auth/browser.json`)
- `harvest_radios.py` — drain song radios → co-occurrence-ranked candidates
- `harvest_playlists.py` — mine public playlists your songs appear in (search → **verify** →
  collect), ranked by `curated_freq` (real curated mixes only; OST dumps demoted)
- `build_queue.py` — merge radio + playlist candidates → `data/unified_candidates.csv`
- `curate.py` — version-preserving dedupe + artist caps + genre caps → `data/download_queue.csv`
- `download_tracks.py` — yt-dlp download + clean tags + search fallback for dead videos;
  resumable archive + 403/429 auto-backoff (`--sleep`, `--sleep-requests`, `--backoff`, `--client`)

**Curation / labeling (LLM-assisted)**
- `llm_prep.py` / `llm_merge.py` — chunk titles for LLM VGM/series classification, then merge → `data/llm_series.csv`
- `label_artists.py` / `merge_artist_genre.py` — chunk artists for genre labeling, then merge (feeds genre caps)

**Algorithm / analysis**
- `muq_run.py` — incremental MuQ-MuLan embedding (GPU) → `data/muq_embeddings.npz`
- `eval_methods.py` — collaborative method benchmark (leave-out recall@K, MRR, nDCG)
- `autoplay.py` — hybrid autoplay (`--text "mood"` or `--seed-contains "track"`)
- `genre_map.py` — interpretable genre map → `viz/genre_map.html` + `viz/06_genre_map.png` + `data/clusters.csv`
- `vgm_space.py` — within-VGM sub-space (series/style) → `viz/07_vgm_map.png` + `viz/vgm_map.html` + `data/vgm.csv`
- `tune_autoplay.py` — sweep autoplay weights → `data/autoplay_config.json`
- `visualize.py` — figure suite → `viz/01..05`
- `make_playlists.py` — genre + mood `.m3u` mixes → `viz/playlists/`
- `dl_bench.py` — download-throughput benchmark harness (produced `docs/COLLECTION_SCALING.md`)
- `analyze_playlists.py` — diagnostic: OST-dump vs curated-mix split of harvested playlists

**Frontend / suite**
- `app.py` — local web player (Player + VGM Space tabs) → http://127.0.0.1:5000
- `run_all.py` — runs every embed + eval + map + playlists + tune + figures + tests → `docs/REPORT.md`
- `tests/` — pytest sanity/regression tests

## Run

```powershell
# one-time setup
python -m venv .venv
.venv\Scripts\python -m pip install -r requirements.txt -r requirements-ml.txt   # see requirements-ml.txt for the GPU/torch install order

# refresh the whole algorithm layer (embed new tracks + eval + maps + playlists + tune + figures + tests)
.venv\Scripts\python scripts\run_all.py

# try the autoplay engine
.venv\Scripts\python scripts\autoplay.py --text "rainy late-night lo-fi" --n 20

# launch the local web player, then open http://127.0.0.1:5000
.venv\Scripts\python scripts\app.py
```

**Collection loop (toward 50k — run the download in your OWN terminal so it survives idle):**
```powershell
.venv\Scripts\python scripts\harvest_playlists.py --max-seeds 800 --sleep 1.5   # FIND songs (resumes from cache)
.venv\Scripts\python scripts\build_queue.py                                      # merge radio + playlist pools
.venv\Scripts\python scripts\curate.py --input data\unified_candidates.csv       # dedupe + caps → download_queue.csv
.venv\Scripts\python scripts\download_tracks.py --input data\download_queue.csv --sleep 5 --sleep-requests 1   # DOWNLOAD (best-first, resumable)
```

## Outputs

- `viz/01_embedding_map.png` … `07_vgm_map.png`, `viz/genre_map.html`, `viz/vgm_map.html` (interactive), `viz/playlists/*.m3u`
- `data/`: `seed_tracks.csv`, `candidates.csv`, `download_queue.csv`, `clusters.csv`, `vgm.csv`, `muq_embeddings.npz`, `autoplay_config.json`
- `docs/EXPERIMENTS.md` (findings), `docs/COLLECTION_SCALING.md` (scaling research), `docs/REPORT.md` (latest suite run)

## Notes

- The audio library lives outside the repo (a separate big drive in my setup). Set
  `MUSIC_DIR` to wherever your `.opus` files are; it defaults to `./music`. Tracks are Opus ~144k.
- GPU stack (torch cu128, muq, MuQ-MuLan): see `requirements-ml.txt` — install order matters.
- `auth/`, `data/`, `music/`, and model weights are gitignored (credentials + personal data + large files) — see `.gitignore`.
- Long downloads/harvests should run in your own terminal: a background job in an editor or agent session can get killed when it goes idle.
