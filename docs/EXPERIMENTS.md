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

## Recommended architecture

- **Daily-mix / playlist generation:** collaborative `pos + song2vec` hybrid (backbone).
- **Semantic search ("type a mood"):** MuQ-MuLan text->music.
- **Autoplay:** MuQ audio vibe + collaborative association + MMR diversity + exploration.

## Open / next

- **Content's contribution to *recommendation* (not autoplay) is not yet proven** — we
  only have audio for favourites, so a fair collab-vs-content rec test needs audio for
  non-favourite distractors (download + MuQ-embed candidate pool).
- Headline numbers were measured on ~510 tracks (early in the download). The library is
  now ~2,000+ and growing; re-run `scripts/run_all.py` to refresh metrics on the full set.
