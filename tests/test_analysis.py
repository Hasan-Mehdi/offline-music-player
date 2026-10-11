"""Tests for the analysis descriptors (scripts/scan_analysis.py) and the OST album-gain
math (scripts/album_gain.py). Everything runs on synthetic signals and hand-made numbers —
no library.db, no .opus files, no ffmpeg.
Run: .venv\\Scripts\\python -m pytest -q tests/test_analysis.py
"""
import math
import sys

import numpy as np

sys.path.insert(0, "scripts")

import album_gain as ag        # noqa: E402
import scan_analysis as sa     # noqa: E402

SR = sa.SR


# ------------------------------------------------------------------ signal helpers

def _silence(secs):
    return np.zeros(int(secs * SR), dtype=np.float32)


def _noise(secs, db, seed=0):
    rng = np.random.default_rng(seed)
    return (rng.standard_normal(int(secs * SR)) * 10 ** (db / 20)).astype(np.float32)


def _click_track(bpm, secs=30.0):
    y = np.zeros(int(secs * SR), dtype=np.float32)
    n = int(0.01 * SR)
    imp = (np.exp(-np.linspace(0, 8, n)) * np.sin(2 * np.pi * 1000 * np.arange(n) / SR))
    imp = imp.astype(np.float32)
    t, per = 0.0, 60.0 / bpm
    while t < secs - 0.1:
        i = int(t * SR)
        y[i:i + n] += imp
        t += per
    return y


def _tone(midi, secs):
    f = 440.0 * 2 ** ((midi - 69) / 12)
    t = np.arange(int(secs * SR)) / SR
    y = sum(a * np.sin(2 * np.pi * f * k * t) for k, a in ((1, 1.0), (2, 0.4), (3, 0.2)))
    fade = np.minimum(1.0, np.minimum(np.arange(t.size) / (0.01 * SR),
                                      (t.size - np.arange(t.size)) / (0.05 * SR)))
    return (y * fade * 0.3).astype(np.float32)


def _arpeggio(root_midi, degrees, reps=8, note_s=0.4):
    return np.concatenate([_tone(root_midi + d, note_s) for d in degrees] * reps)


# ------------------------------------------------------------------ album LUFS math

def test_track_lufs_recovers_loudness_from_tag_gain():
    # tag gain is relative to the -23 LUFS R128 reference
    assert ag.track_lufs(-9.0) == -14.0
    assert ag.track_lufs(0.0) == -23.0
    assert ag.track_lufs(3.5) == -26.5


def test_album_lufs_uniform_album_is_that_loudness():
    members = [(120.0, -16.0), (200.0, -16.0), (45.0, -16.0)]
    assert abs(ag.album_lufs(members) - (-16.0)) < 1e-9
    assert abs(ag.album_gain(members) - (-23.0 + 16.0)) < 1e-9


def test_album_lufs_known_two_track_case():
    # equal durations, -20 and -10 LUFS -> 10*log10((1e-2 + 1e-1)/2)
    expect = 10 * math.log10((10 ** -2.0 + 10 ** -1.0) / 2)
    assert abs(ag.album_lufs([(60.0, -20.0), (60.0, -10.0)]) - expect) < 1e-9
    assert abs(expect - (-12.5964)) < 1e-3


def test_album_lufs_is_energy_weighted_not_a_dB_average():
    # one loud track pulls the album above the arithmetic mean of the dB values
    a = ag.album_lufs([(60.0, -30.0), (60.0, -10.0)])
    assert a > -20.0
    assert a < -10.0


def test_album_lufs_weights_by_duration():
    short_loud = ag.album_lufs([(10.0, -8.0), (300.0, -24.0)])
    long_loud = ag.album_lufs([(300.0, -8.0), (10.0, -24.0)])
    assert short_loud < long_loud
    assert abs(long_loud - (-8.0)) < 1.0        # the long track dominates the integration


def test_album_lufs_empty_or_zero_duration():
    assert ag.album_lufs([]) is None
    assert ag.album_lufs([(0.0, -14.0)]) is None
    assert ag.album_gain([]) is None


def test_ost_grouping_matches_server_shape():
    # sanity on the copied helpers: title-parsed name, suffix stripping, min group size
    assert ag._ost_name("", "Battle Theme - Chrono Trigger OST") == "Chrono Trigger"
    assert ag._clean_ost("Celeste (Original Soundtrack)") == "Celeste"
    assert ag._ost_name("", "no separator here") is None
    rows = [{"video_id": f"v{i}", "title": f"T{i} - Undertale OST", "album": ""}
            for i in range(4)]
    rows += [{"video_id": "x", "title": "Solo - Tiny Game OST", "album": ""}]
    groups = ag.ost_groups(rows, {})
    assert set(groups) == {"undertale"}          # the 1-track group is dropped
    assert len(groups["undertale"]) == 4


# ------------------------------------------------------------------ silence + hook

def _padded_burst():
    """2 s digital silence | 3 s quiet | 15 s loud | 20 s quiet | 2 s silence  (42 s)"""
    return np.concatenate([_silence(2.0), _noise(3.0, -30, 1), _noise(15.0, -6, 2),
                           _noise(20.0, -30, 3), _silence(2.0)])


def test_silence_bounds_find_the_audible_span():
    y = _padded_burst()
    dur = y.size / SR
    lead, tail = sa.silence_bounds(sa.rms_frames(y), dur)
    assert abs(lead - 2.0) < 0.2                 # audio starts when the quiet part does
    assert abs(tail - 40.0) < 0.2                # and ends before the trailing silence
    assert 0.0 <= lead < tail <= dur


def test_silence_bounds_ignore_a_short_blip():
    # a 0.1 s click (< SUSTAIN_S) in the middle of silence must not count as the start
    y = np.concatenate([_silence(2.0), _noise(0.1, -6, 4), _silence(3.0),
                        _noise(10.0, -10, 5), _silence(2.0)])
    lead, tail = sa.silence_bounds(sa.rms_frames(y), y.size / SR)
    assert lead > 4.0                            # not 2.0 — the blip was rejected
    assert abs(lead - 5.1) < 0.2
    assert abs(tail - 15.1) < 0.2


def test_silence_bounds_all_silent():
    y = _silence(10.0)
    assert sa.silence_bounds(sa.rms_frames(y), 10.0) == (0.0, 10.0)


def test_hook_lands_on_the_loud_window():
    y = _padded_burst()
    hook = sa.hook_seconds(sa.rms_frames(y), y.size / SR)
    assert abs(hook - 5.0) < 1.0                 # the 15 s loud section starts at 5 s


def test_hook_clamped_into_range():
    # a 10 s track: the [3, duration-20] clamp collapses to exactly 3 s
    y = np.concatenate([_silence(1.0), _noise(9.0, -6, 6)])
    assert sa.hook_seconds(sa.rms_frames(y), 10.0) == 3.0
    # loud right at the top of a long track -> still never before 3 s
    y2 = np.concatenate([_noise(15.0, -6, 7), _noise(60.0, -30, 8)])
    assert sa.hook_seconds(sa.rms_frames(y2), 75.0) >= 3.0


# ------------------------------------------------------------------ energy

def test_energy_db_ignores_digital_silence():
    core = np.concatenate([_noise(3.0, -30, 9), _noise(15.0, -6, 10)])
    short = sa.energy_db(sa.rms_frames(np.concatenate([_silence(2.0), core, _silence(2.0)])))
    long = sa.energy_db(sa.rms_frames(np.concatenate([_silence(30.0), core, _silence(30.0)])))
    assert abs(short - long) < 0.05              # padding with silence must not move it
    assert -12.0 < short < -4.0                  # dominated by the -6 dBFS section


def test_energy_db_tracks_level():
    quiet = sa.energy_db(sa.rms_frames(_noise(5.0, -30, 11)))
    loud = sa.energy_db(sa.rms_frames(_noise(5.0, -12, 12)))
    assert abs((loud - quiet) - 18.0) < 1.0
    assert sa.energy_db(np.array([])) == -120.0


# ------------------------------------------------------------------ bpm

def test_bpm_on_a_120_click_track():
    bpm = sa.estimate_bpm(_click_track(120.0), SR)
    assert abs(bpm - 120.0) < 5.0                # tempogram bins are ~2.5 BPM apart here


def test_bpm_follows_the_click_rate():
    slow = sa.estimate_bpm(_click_track(90.0), SR)
    fast = sa.estimate_bpm(_click_track(150.0), SR)
    assert abs(slow - 90.0) < 6.0
    assert abs(fast - 150.0) < 6.0


# ------------------------------------------------------------------ key

def test_key_on_major_arpeggios():
    assert sa.estimate_key(_arpeggio(60, [0, 4, 7, 12]), SR) == "C"
    assert sa.estimate_key(_arpeggio(62, [0, 4, 7, 12]), SR) == "D"
    assert sa.estimate_key(_arpeggio(66, [0, 4, 7, 12]), SR) == "F#"


def test_key_on_minor_arpeggios():
    assert sa.estimate_key(_arpeggio(69, [0, 3, 7, 12]), SR) == "Am"
    assert sa.estimate_key(_arpeggio(64, [0, 3, 7, 12]), SR) == "Em"


def test_key_from_chroma_profiles_are_well_formed():
    assert sa.KS_MAJOR.shape == (12,) and sa.KS_MINOR.shape == (12,)
    # a perfect C-major-profile chroma must read back as C, and every rotation as its tonic
    for i, note in enumerate(sa.NOTES):
        assert sa.key_from_chroma(np.roll(sa.KS_MAJOR, i)) == note
        assert sa.key_from_chroma(np.roll(sa.KS_MINOR, i)) == note + "m"
    assert sa.key_from_chroma(np.zeros(12)) is None
    assert sa.key_from_chroma(np.ones(12)) is None       # flat chroma -> no key


# ------------------------------------------------------------------ end-to-end (no io)

def test_analyze_audio_returns_the_full_row():
    # a 120 BPM click over a continuous -24 dBFS bed (bare clicks are too short to count
    # as "sustained" audio, so the bed is what lead/tail should latch onto)
    body = _click_track(120.0, 40.0) * 0.5 + _noise(40.0, -24, 13)
    y = np.concatenate([_silence(2.0), body.astype(np.float32), _silence(2.0)])
    a = sa.analyze_audio(y, SR, y.size / SR)
    assert set(a) == {"bpm", "key", "energy_db", "hook_sec", "lead_sec", "tail_sec"}
    assert abs(a["bpm"] - 120.0) < 5.0
    assert abs(a["lead_sec"] - 2.0) < 0.3
    assert abs(a["tail_sec"] - 42.0) < 0.3
    assert 3.0 <= a["hook_sec"] <= max(3.0, y.size / SR - 20.0)
    assert a["energy_db"] < 0.0
