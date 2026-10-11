# How major streaming platforms build recommenders (public-info research)

_Compiled 2026-06-30 via multi-source deep research (24/25 claims survived 3-vote adversarial verification). Strongest documentation: **YouTube** (peer-reviewed ACM papers) and **Spotify** (own papers + research blog + patents). Apple Music, Amazon Music, Deezer publish little — treat as undocumented. Some skip-labeling details are from 2023–24 academic papers on Spotify/Pandora **public datasets** — reproducible mechanisms, not confirmed production code._

## The shape everyone converges on
**Two-stage retrieve-then-rank:** a cheap **candidate-generation** model narrows the catalog (millions → hundreds) via learned embeddings + nearest-neighbor search, then a heavier **multitask ranking** model scores the few hundred by predicting several engagement/satisfaction outcomes and combining them. Exploration via **contextual bandits**. Autoplay/radio = a **sequence model** predicting the next *non-skipped* track.

## 1. Implicit-feedback signals
- **Skips are graded by timing.** Spotify logs `skip_1`/`skip_2`/`skip_3` (very brief / brief / most-of-track); `skip_2` is the binary skip label (WSDM Cup 2019). Common rule: **"skipped" = next event within ~30s of track start** (Seshadri et al., RecSys 2024). On a 1–3 strength scale, **only strengths 1–2 count as strong negatives**; late/weak skips are discarded, not treated as dislikes (arXiv 2309.11623).
- **Real "hard" negatives beat random negatives:** using actual skips/thumb-downs as targets cut training time ~60% and improved accuracy ~6% vs random negatives; too many random negatives cause false negatives that cap the lift below real negative feedback (Mei et al., UMAP 2024, arXiv 2406.04488).
- **Positives:** completion/play-through, replays (strong positive), saves/adds-to-playlist, follows — weighted above passive plays.
- **Pitfalls:** *position/selection bias* → learned **"shallow tower"** predicts a propensity term added in logit space, no randomized experiments needed (Zhao et al. 2019). *Popularity bias* → the most accurate CF model (SLIM) had the most popularity bias (Turnbull et al., arXiv 2208.09517). *Filter bubbles/feedback loops* → fixed with exploration + **counterfactual inverse-propensity** correction (McInerney, Spotify BaRT).

## 2. Candidate generation (retrieval)
- **YouTube:** extreme multiclass "predict next watch" → learns user/item embeddings → **approximate nearest-neighbor** serving (Covington et al., RecSys 2016).
- **Two-tower / dual-encoder:** separate user & item towers → embeddings → dot-product/cosine → ANN.
- **Confidence-weighted ALS** for implicit feedback: `C_ui = 1 + α·R_ui` (α≈40) (Hu-Koren-Volinsky).
- **Spotify:** CF via **playlist co-occurrence** over a very large playlist corpus (blog cites ~700M).

## 3. Ranking (multitask)
- YouTube's next-video ranker: **Multi-gate Mixture-of-Experts (MMoE)** predicting **engagement** (clicks → cross-entropy, watch/listen-time → regression) and **satisfaction** (likes, dismissals), combined into one score. **Watch-time weighting** optimizes time spent, not just clicks (Zhao et al., RecSys 2019). The exact combination function is undisclosed.

## 4. Exploration vs exploitation
- **Spotify BaRT** (_Explore, Exploit, Explain_, RecSys 2018): contextual bandit picks shelves/items using **factorization-machine reward models** (reward = streams), **stochastic exploration**, **counterfactual/propensity training**; jointly optimizes item + explanation.
- **Spotify 2025 homepage bandit:** ε-greedy chooses the optimal **content-type distribution**, then builds slates one item at a time under relevance + a **KL-divergence calibration penalty**.

## 5. Sequence / session modeling (autoplay/radio)
- Framed as session-based next-track prediction with **transformers (SASRec/BERT4Rec)**.
- Reframe: predict the next **positive (non-skipped)** track; split session into positive/negative sets; inject skips via an **InfoNCE contrastive** term: **L = α·L_NLL + β·L_NCE**. Consistently beats feedback-agnostic models (HR@1 +8.9%/+20.3%) (Seshadri et al., RecSys 2024).
- Spotify: **optimization-based sequencing** to order a chosen set by preference flow (2023).

## Caveats
Lopsided coverage (YouTube + Spotify only); YouTube papers are 2016/2019 (architecture has evolved); one claim refuted (commercial services do NOT demonstrably lack popularity bias); quantitative lifts are single-paper/dataset-specific.

## Highest-leverage borrowings for our engine
1. Graded, **time-thresholded skip logging** as real negatives (skip <~30s = strong negative; late skip = discard).
2. **Listen-time / completion-weighted** positive signal (not just "played").
3. A **skip-contrastive term** in the autoplay next-track model.

## Sources
- Covington, Adams, Sargin — *Deep Neural Networks for YouTube Recommendations*, RecSys 2016. https://research.google/pubs/deep-neural-networks-for-youtube-recommendations/
- Zhao et al. — *Recommending What Video to Watch Next: A Multitask Ranking System*, RecSys 2019. https://dl.acm.org/doi/10.1145/3298689.3346997
- McInerney et al. — *Explore, Exploit, Explain (BaRT)*, Spotify, RecSys 2018. https://jamesmc.com/blog/2018/10/1/explore-exploit-explain
- Spotify Research — *Calibrated Recommendations with Contextual Bandits on the Homepage*, 2025. https://research.atspotify.com/2025/9/calibrated-recommendations-with-contextual-bandits-on-spotify-homepage
- Mei, Bembom, Ehmann — *Negative Feedback for Music Personalization*, UMAP 2024. https://arxiv.org/pdf/2406.04488
- Seshadri, Shashaani, Knees — skip-aware sequential recommendation, RecSys 2024. https://arxiv.org/html/2309.11623v2 · https://dl.acm.org/doi/fullHtml/10.1145/3640457.3688188
- Spotify Sequential Skip Prediction Challenge (WSDM Cup 2019). https://www.aicrowd.com/challenges/spotify-sequential-skip-prediction-challenge
- Turnbull et al. — *Exploring Popularity Bias in Music Recommendation Models*, arXiv 2208.09517. https://arxiv.org/pdf/2208.09517
- Spotify Research — *Exploiting Sequential Music Preferences via Optimisation-Based Sequencing*, 2023. https://research.atspotify.com/2023/10/exploiting-sequential-music-preferences-via-optimisation-based-sequencing
