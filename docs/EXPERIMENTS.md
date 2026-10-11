# Algorithm experiments & findings

Rigorous offline evaluation on the real library (mid-2026). Two signal families were
tested: **collaborative** (YouTube radio co-occurrence) and **content** (audio/text
embeddings). Leave-out protocol: hold out 20% of known favourites (played >=3x), score
from the rest, measure how highly the held-out favourites rank.

## 1. Collaborative ranking (`scripts/eval_methods.py`)

510 strong-seed radios, 8 random splits. Metrics in % (higher better):

| method | r@50 | r@100 | nDCG@100 |
|--------|-----:|------:|---------:|
| count (raw co-occurrence, baseline) | 7.4 | 14.3 | 15.6 |
| idf-weighted | 7.4 | 14.3 | 15.6 (no help) |
| **pos** (inverse-rank: early-in-radio = more related) | 8.5 | 15.6 | 18.5 |
| song2vec alone (PPMI + truncated SVD) | weak | weak | weak |
| **hybrid (pos + song2vec)** | **9.7** | **15.7** | **19.0** |

**Winner: pos + song2vec hybrid — +32% r@50, +21% nDCG over the raw baseline.**
song2vec is weak alone (the radio graph is shallow: one basket per seed) but adds
complementary signal. Score per-seed via mean cosine to the *top-k nearest* seeds, NOT
the centroid — taste is multi-cluster (VGM / future-funk / chiptune), so a centroid is
mush. vs random, the headline leave-out lift is ~19-20x (see `viz/03_collaborative.png`).

## 2. Content embeddings — CLAP vs MuQ-MuLan

| model | artist-coherence@5 | text->music | notes |
|-------|-------------------:|-------------|-------|
| CLAP (laion/larger_clap_music) | 2.5x | **broken** | anisotropic: all pairwise cos ~0.98; every text prompt returns identical results, even after whitening |
| **MuQ-MuLan (OpenMuQ/MuQ-MuLan-large)** | **9.6x** | **works** | well-spread embedding; semantic search correct across genres |

MuQ-MuLan text->music examples (full library): "vaporwave future funk" -> Night Tempo
"Plastic Love", YUNG BAE; "chiptune battle" -> real sound-chip tracks (HuC6280, N163,
VRC6); "epic orchestral" -> OCTOPATH TRAVELER theme; "relaxing piano" -> Rozen piano
reflections. See `viz/01_embedding_map.png` (clean clusters + typed moods placed by match),
`viz/04_content_models.png` (MuQ coherence + spread vs CLAP), `viz/05_text_to_music.png`.

**Decision: MuQ-MuLan is the content model. CLAP is abandoned.** (MuQ weights CC-BY-NC,
fine for personal use. Runs on GPU — RTX 5080, cu128.)

## 3. Autoplay (`scripts/autoplay.py`)

Hybrid next-track score = MuQ audio "vibe" (cosine to current) + collaborative boost
(in current track's radio) + artist-cooldown diversity + epsilon exploration. Seedable
by track or by mood phrase (text -> MuQ-MuLan -> nearest track). Produces coherent,
on-taste, artist-diverse sequences that drift naturally (verified live).

## 4. Hum-to-search / query by humming (`scripts/melody_match.py`)

Hum/whistle a melody into the mic (Songs view) → ranked matches from the library.
Pipeline: per-track predominant-melody index (`build_melody_index.py`: ffmpeg → 150–2000 Hz
band-pass → CREPE-full on GPU at 20 Hz → periodicity gate → notes) matched against the
pyin-tracked hum with repeat-collapsed **absolute-pitch subsequence DTW** over a ±5-semitone
key-offset search (interval-bigram prefilter above 1.2k tracks; numba). basic-pitch was
rejected (won't install on py3.13); first-order interval DTW was rejected (a dropped note
corrupts two cells — absolute pitch lifted hard tier 32%→64%).

Synthetic-hum eval (`eval_hum.py`, n≈120/tier, full pipeline, 500-track index):

| tier (perturbation) | top-1 | top-5 | top-10 | MRR@10 |
|---|---|---|---|---|
| easy (light vibrato) | 84% | 84% | 85% | 0.84 |
| medium (±5 st transpose, ×0.8–1.25 tempo, jitter, 10% dropout) | 66% | 77% | 79% | 0.71 |
| hard (medium + interval errors, 20% dropout) | 42% | 59% | 64% | 0.49 |

**Extraction quality is the ceiling, not matching** (easy tops out at 85% where CREPE locks
onto bass/pads instead of the lead; the small easy→medium gap shows matcher robustness).
Query latency ~340 ms warm; indexing 1.07 s/track (RTX 5080). Serving: `POST /api/hum`
(webm/wav body) → `{results, query}`; UI mic button lives in the Songs search row.

## Autoplay engine v3 (2026-10-10)

An audit of the live ranker (v2.2) on the 56k library found it was no longer deciding by
sound. Fixes and their measurements (`scripts/eval_autoplay.py`; 30 walks x 25 steps seeded
from the listening history):

**Anisotropy.** MuQ unit vectors share one direction: ||mean|| = 0.525, random pairs sit at
cosine 0.275 (centered: 0.00). Every centroid of many tracks (taste, skip, session mood)
collapsed onto it — taste·mean 0.77, skip·mean 0.78, taste·skip 0.73 — i.e. they scored
*typicality*. Temporal holdout (`eval_autoplay.py taste`: history before 2026-07-26 →
predict the 410 library tracks first heard after it):

| taste model | AUC | recall@1000 | recall@5000 |
|---|---|---|---|
| random | 0.515 | 0.015 | 0.098 |
| history centroid, raw | 0.539 | 0.037 | 0.139 |
| **history centroid, centered** | **0.669** | **0.063** | **0.202** |
| k-means mixtures (4/8/16, centered) | 0.57–0.59 | ≤0.027 | ≤0.10 |

Centering costs nothing on neighbours (artist@10 0.077 → 0.079, genre@10 0.294 → 0.296,
88% top-50 overlap), so the whole ranker runs centered. Weights log1p(plays) x 1-year
recency beat raw plays, uniform, and 30/60-day half-lives.

**Density drift.** At 20k tracks the vibe range in a candidate window was ~0.35; at 56k ~0.13,
so fixed-magnitude terms had tripled in relative weight (removing tempo/taste/skip changed the
pick in 56/75/72% of seeds, vibe only 37%). v3 expresses weights relative to vibe's spread in
the current list (`scale="window"`).

**Signals.** 59/131 logged skips were under 3 s and 103/216 track changes under 10 s —
browsing, counted as the strongest negatives. The client now logs `switch` for navigation;
legacy sub-3 s skips carry no weight. The skip outcome used to reach the server *after*
/api/next had already ranked the skipped track's neighbours; it now rides on the request and
the walk continues from the last kept track. Like/unlike is read as state (a mis-tapped
like→unlike had netted +1.5; unliking an old like had produced a dislike).

| walk metric | v2 | v3 |
|---|---|---|
| "sound" given up by the pick (median / p90, sd) | 0.23 / 0.70 | **0.12 / 0.39** |
| step similarity (raw cos, mean) | 0.813 | 0.811 |
| clones (≥0.92) | 1.3% | 0.9% |
| seed similarity after 20 steps | 0.493 | 0.585 |
| tempo match (≤5%) | 81% | 75% |
| after an early skip, next pick nearer the kept anchor than the skipped track | 88%* | **98%** |

\*v2 run through the new decision function, which already re-anchors; before v3 the walk
always continued from the skipped track.

**Exploration cost.** About 18% of picks are exploration: a Thompson draw over the 16
genre-map clusters, then that cluster's best unheard track within the top 40. The cluster
was chosen without regard to where its track ranked, so the worst picks came from ranks
21–37 and sounded like a different station (live: Gusty Garden → lounge jazz). Forcing the
explore branch at all 750 decisions of the 30-seed sim:

| explore policy | sound given up p90 | > 0.75 sd | other cluster |
|---|---|---|---|
| exploit (rank 1), for reference | 0.35 sd | 0.4% | – |
| Beta(1,1) arms, top 40 (before) | 0.51 sd | 2.8% | 48% |
| pooled prior n=10 only | 0.54 sd | 3.2% | 52% |
| window cut to 12 | 0.41 sd | 0.8% | 39% |
| **sound budget 0.5 sd** (+ pooled prior) | **0.39 sd** | **0.0%** | 45–48% |

A stronger prior alone makes it worse: it evens the arms out, so deep-ranked clusters win
more often. The fix is the budget (`choose_next_explained(sound_budget=0.5)`); the pooled
prior (`prior_n=10`) is kept for what it is, a correction for 2-of-2 clusters drawing from
Beta(3,1) and out-bidding the 9-of-21 cluster you actually play (91% → 62% of draws), at
no measured cost under the budget. Live engine, 60 fresh seeds: explore picks over
0.75 sd 2.7% → 0%, p90 0.46 → 0.41 sd, other-cluster share 47% → 49%; walk metrics
unchanged. Arm stats can't yet be limited to system picks: 147 of 155 logged verdicts
predate the `source` column.

## Recommended architecture

- **Daily-mix / playlist generation:** collaborative `pos + song2vec` hybrid (backbone).
- **Semantic search ("type a mood"):** MuQ-MuLan text->music.
- **Autoplay:** centered MuQ audio vibe + listening-history taste + collaborative association
  + session skips + diversity + exploration (engine v3 above).

## Open / next

- **Content's contribution to *recommendation* (not autoplay) is not yet proven** — we
  only have audio for favourites, so a fair collab-vs-content rec test needs audio for
  non-favourite distractors (download + MuQ-embed candidate pool).
- Headline numbers were measured on ~510 tracks (early in the download). The library is
  now ~2,000+ and growing; re-run `scripts/run_all.py` to refresh metrics on the full set.
