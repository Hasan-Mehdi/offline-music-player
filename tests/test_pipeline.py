"""Sanity/regression tests for the pipeline. Run: .venv\\Scripts\\python -m pytest -q tests"""
import csv
import sys
from pathlib import Path

import numpy as np
import pytest

sys.path.insert(0, "scripts")


# ---- pure logic (no data files needed) ----

def test_takeout_helpers():
    from parse_takeout_history import video_id_from_url, clean_artist, clean_title
    assert video_id_from_url("https://music.youtube.com/watch?v=ABCDEFGHIJK") == "ABCDEFGHIJK"
    assert video_id_from_url("") is None
    assert clean_artist({"subtitles": [{"name": "Foo - Topic"}]}) == "Foo"
    assert clean_artist({}) == ""
    assert clean_title({"title": "Watched Bar Baz"}) == "Bar Baz"


def test_znorm_zero_mean():
    from eval_methods import znorm
    z = znorm({"a": 1.0, "b": 3.0, "c": 5.0})
    assert abs(sum(z.values())) < 1e-6
    assert z["c"] > z["a"]


def test_rank_eval_perfect_and_miss():
    from eval_methods import rank_eval
    # both relevant items at the very top -> recall 1.0
    out = rank_eval({"a": 3, "b": 2, "c": 1, "d": 0}, set(), {"a", "b"})
    assert out["r@50"] == 1.0 and out["nDCG@100"] > 0.99
    # relevant item absent from ranking universe -> recall 0
    out2 = rank_eval({"a": 3, "b": 2}, set(), {"zzz"})
    assert out2["r@50"] == 0.0


# ---- data-backed sanity (skip gracefully if a stage hasn't run) ----

def test_muq_embeddings_normalized():
    p = Path("data/muq_embeddings.npz")
    if not p.exists():
        pytest.skip("no MuQ embeddings yet")
    X = np.load(p, allow_pickle=False)["embeddings"]
    assert X.shape[1] == 512
    assert np.allclose(np.linalg.norm(X, axis=1), 1.0, atol=1e-2)


def test_seed_tracks_schema():
    p = Path("data/seed_tracks.csv")
    if not p.exists():
        pytest.skip("no seed_tracks.csv yet")
    row = next(csv.DictReader(open(p, encoding="utf-8-sig")))
    for col in ("video_id", "title", "artist", "play_count", "score"):
        assert col in row


def test_candidates_cooccurrence_sorted():
    p = Path("data/candidates.csv")
    if not p.exists():
        pytest.skip("no candidates.csv yet")
    co = [int(r["co_occurrence"]) for r in csv.DictReader(open(p, encoding="utf-8-sig"))]
    assert co == sorted(co, reverse=True)        # harvester writes ranked output
    assert co[0] >= 1
