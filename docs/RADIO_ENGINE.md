# Radio engine (autoplay v4, PC player)

Since 2026-10-11 the web player's autoplay and song radios work the way YouTube Music's do.
They choose for **the song the radio started on**, mostly from **what people play together**,
and they mix in songs you already know. The H2 runs it too. `scripts/radio_pack.py` ranks each card
song's radio on the PC into `radio.bin`, and `firmware/core/omp_radio.c` does `sequence()` and the
reject cost per pick. `firmware/tools/test_radio_parity.py` checks the two give the same picks, so a
change to `radio.py`'s constants or `sequence()` belongs in both.

## Why

We measured the old engine against 1,572 of your own signed-in YouTube Music radios (`data/radio_cache`)
and 4,983 back-to-back plays from your history. The old engine picked whatever sounded most like the
song that just ended, one step at a time.

| | YouTube Music radio | old walk | new radio |
|---|---|---|---|
| Same 25 songs as YT Music's radio (seed's own radio hidden) | (answer key) | 1.0% | **17.5%** |
| Sound-similarity to the start song, songs 1-5 → 11-25 | .56 → .52 | .60 → .35 | .58 → .58 |
| Sound-similarity between neighbours | .47 | .71 | .50 |
| Same channel as the start song | 20% | 0.4% | 24% |
| Same game series (when it has one) | 41% | 6% | 48% |
| Songs you already play | 34% | 5% | 34% |
| Sonic in non-Sonic radios | 1.5% | 2.6% | 1.9% |
| Top 1% of songs' share of all slots | 16% | 11% | 14% |
| Your next song in the top 10 / top 50 (plays after Aug 15) | | 0.3% / 1.2% | **10% / 18%** |

So the old engine drifted away from where you started. It almost never played a song you know, and it
needed a cooldown for each way that went wrong (fatigue, sameness, artist, franchise).

## How it picks

1. **Candidates** (`player_server/radio.py: candidates`): the seed's play-together neighbours, its
   song2vec neighbours, its nearest songs by sound, and the songs you play that sound nearest it.
   That comes to about 700 songs.
2. **Score** (`features`, `score`): a weighted sum of 15 features per candidate:
   - how often it shares a basket with the seed (raw and as a rank);
   - song2vec similarity;
   - sound similarity;
   - your taste;
   - how well you know it;
   - how many baskets hold it;
   - whether it has the same channel or game as the seed;
   - sound and song2vec again for candidates with no play-together evidence at all.
   The weights are a logistic regression fit to predict "is this in YT Music's radio for the seed",
   then deliberately softened. At full strength, sound made queues samey (neighbours .62) and
   popularity made a few hub songs appear everywhere: one Macross 82-99 track was in 18% of all
   radios.
3. **Order** (`sequence`): each slot takes the best score after three nudges and one rule:
   - songs you know get +0.3 per song the queue is short of a third, and −0.3 per song past it;
   - the seed's game costs 0.5 per song past 45% of the queue;
   - the seed's channel costs 0.75 per song past 30%;
   - the rule: at most two in a row from one channel.

   The game nudge counts at most 2 songs over, the channel nudge at most 4 (since 2026-10-19,
   below). Uncapped, or as hard caps, they forced bad fits whenever the songs that fit were all
   the capped kind: a J-pop song in a Pokémon radio, Herb Alpert at rank 172 in a Mario Kart
   one. The shares count the last 12 songs you heard, so a queue built at once and one built
   song by song come out alike.
4. **A seed's cached YT Music radio** is one basket of play-together evidence like any other.
   Until 2026-10-19 its members led the queue; see below for why they no longer do.
5. **Skips:** an early skip or a dislike makes songs that sound like it, or sit near it in song2vec,
   cost more for the rest of the sitting. If you skip the seed itself, the radio moves to the last
   song you kept.

## Skips, streaks, collaborations, versions (2026-10-15)

From the H2's own log, when it still ran the older walk (about 200 songs it picked):

| after... | the next pick was skipped | it sounded like the skipped song | like the last one you finished |
|---|---|---|---|
| a skip | 53% | 0.67 | 0.51 |
| a finish | 12% | - | 0.73 |

Your skips land a median 56 s in, and two thirds of them come after 15% of the song, the old
"early skip" line, so most skips counted as "keep going this way". The engine was a chain, too:
each next song was "what sounds like the last one you didn't reject". Even after early skips,
where it did move away, the next pick was still skipped 54% of the time. The problem was where
it looked, not only how it read the skip. A run of skips meant "change it up": by hand you'd
gone from rap to city pop to Sonic Mania.

What the radio does now, on the PC and the H2 alike:

- **A skip turns a song down for the sitting** if it comes before 80% of the song
  (`KEEP_FRAC`), or the song is disliked. Its sound and song2vec neighbourhood cost more for the
  rest of the sitting. Long-term taste still only counts early skips
  (`personalize.STRONG_SKIP`).
- **Three turned down in a row (`STREAK`) and the radio moves to a fresh seed**: of your 200
  most played lately (`RESEED_POOL`; the Wheel's order on the H2), the ones that sound no
  closer than 0.25 (`AWAY_SIM`) to what you turned down, and of those the one most like what
  you kept this sitting (with nothing kept: the most played, also away from the old seed).
  The vibe you were in, from somewhere else in your own music; the radio stays with it. It
  moves on each full run of three (`reseed_now`: 3, 6, ...), so skipping the fresh seed's
  first pick isn't another three. The PC client adopts it from `radio_seed` in the
  `/api/next` reply.
- **If you turn down the song you started on,** the radio follows the last song you kept since
  you started it. With none, it moves to a fresh seed. Before, it went back to the last song
  kept before your pick, i.e. the direction you'd just left.
- **A collaboration counts for each artist it credits** (`credits()`, two at most). An
  OmarCameUp radio was 13 of 15 OmarCameUp, half of them as "Shofu, OmarCameUp" and
  "Daddyphatsnaps, OmarCameUp", which got past the two-in-a-row rule and the 30% share.
- **One version of a song per sitting** (`work_key()`: the title without "instrumental",
  "slowed", "sped up", "official audio"..., plus its first artist). The same radio had led with
  the instrumental of the song you'd just started.

Replaying the H2's sittings at the 37 moments right after a skip:

| | sounds like the song skipped | a song you know |
|---|---|---|
| older walk (what played) | 0.68 | 19% |
| radio, old reading of skips | 0.34 | 38% |
| radio, now | 0.04 | 65% |

Same radio as before when it isn't moving (0.21 / 0.28 like the skipped / the last finished); a
fresh seed in 17 of the 37. The YT Music benchmark is unchanged (P@25 17.2% vs 17.4%, every
shape number the same). Replay: `scripts/eval_h2_skips.py` (rerun it on new H2 logs); tests in
`tests/test_radio.py`; on the H2, `firmware/host/test_brain_radio.c` over a real card's pack.

### The fresh seed keeps the vibe (2026-10-18)

On the H2, a Tazmilian Woods radio (irikachana, a gentle MOTHER 3-inspired piece, finished)
had three picks turned down; the fresh seed was the most played song far from them and from
the seed, a rap remix, and one skip later (four in a row) a second one, Coronet Highlands, and
Legends: Arceus from there. "It didn't match the vibe I started on." Now it moves away only
from what you turned down and keeps the sound of what you kept (there: Rozen's Kakariko
Village, 0.51 like Tazmilian Woods), and once per run of three. Replay of the H2's 49 moments
right after a skip (`scripts/eval_h2_skips.py`):

| | like the skipped | like the last finished | a song you know | fresh seeds |
|---|---|---|---|---|
| fresh seed away from everything, every skip past 3 | 0.00 | 0.06 | 57% | 23 |
| fresh seed like what you kept, each run of 3 | 0.09 | 0.20 | 45% | 17 |

## The pool, stale radios, and one channel taking over (2026-10-19)

YT Music's queue for Tazmilian Woods on 10-19 next to ours, and next to what you actually
play around it (32 plays in 31 sittings, `data/listens.csv`):

- **Our play-together candidates were the wrong songs.** `candidates()` read `C.vocab` at
  positions in `related()`'s result instead of at the indices it returns, so the "300
  play-together neighbours" were whatever songs came first in the vocabulary. For Tazmilian
  Woods, 2 of the 300 were real neighbours. The songs you play with it most (Katamari renoise
  and "look at me" 10x, Palmtree Panic 9x, Blood Drain 9x, irikachana's Our Best Future 6x)
  were never candidates. The tests missed it because their toy library is smaller than the
  pools. Every number above this section was measured with the bug.
- **The cached June radio led the queue** (`OWN_RADIO_W` 3.0: "what YouTube would play").
  YT Music's own radio for the seed now shares 1 of 25 songs with it, and its lead picks (Ria,
  Jeanluke pt2) were what you skipped on 10-18. On your plays since Aug 15 the lead didn't help
  either. It is 0 now; the radio still counts as a basket, and at half weight every benchmark
  got worse, so that stays.
- **One channel could take the queue.** Half the playlist cache is upload lists (an album, a
  channel's uploads: one channel holds 80%+ of the tracks), so a channel's songs were tied
  together twice: as `same_artist` and again as "played together". With the seed-channel
  nudge capped at a 1.5 cost, they filled 20 of 30 slots without the June radio. Over your
  sittings since Aug 15, 27% of radios were more than 40% the seed's channel (YT Music's
  radios: 10%; your own sittings: 12%). Upload lists are now their own source at 0.25
  (`collab.SOURCE_W`), and the channel nudge counts up to 4 songs over (`ARTIST_OVER_CAP`).

YT Music's 10-19 queue itself is mostly Pokémon DS-era arrangements (The Zame, Mewmore), 17 of
25 songs you know, sounding little like the seed (0.19). Only 5 of them ever shared a sitting
with it in your history, so it isn't the target. What you play around it is the chip/tracker
scene, Sonic CD covers and irikachana's MOTHER 3 restorations.

| | before | after |
|---|---|---|
| Your next song in the radio, seed = the song before (top 10 / 50 / 200) | 6.7 / 13.7 / 25.0% | **9.0 / 16.8 / 29.0%** |
| ... seed = the sitting's first song | 2.5 / 8.3 / 16.5% | **3.7 / 9.8 / 18.7%** |
| A sitting's songs in its first song's 25-song radio (123 sittings since Aug 15) | 1.89% | **1.98%** (recall 4.7 -> 5.4%) |
| Radios over 40% the seed's channel (those sittings) | 27% | **3%** |
| P@25 vs YT Music's June radios (held out) | 17.3% | 16.9% |
| ... same channel / one channel's share (YT Music 20.2 / 24.6%) | 24.0 / 30.2% | 19.8 / 26.4% |
| Tazmilian Woods: songs you played with it, in its 25 | 3 | **9** |

The uploader weight, measured over 0 / 0.25 / 0.5 / 1: your next song from the sitting's first,
top 50, 8.7 / 9.8 / 9.3 / 8.8%; sittings 1.43 / 1.98 / 1.92 / 1.85%; vs YT Music 17.2 / 16.9 /
16.9 / 17.0%. At 0 many songs lose their only link. The weights were refit with the fixed pool:
`collab` went from 0.03 to 0.15 now that its candidates are real. The H2 skip replay is unchanged
(after a skip: 0.07 like the skipped song, 0.18 like the last finished, a fresh seed in 17 of
49; a song you know 67%, was 45%).

The 10-18 change (a fresh seed keeps the vibe of what you kept) stays: it is what to do after
three skips. This is why the first three were skipped.

## Play-together data (`player_server/collab.py`)

| Source | Baskets | What it is |
|---|---|---|
| `data/radio_cache` | ~2,000 | YT Music's "Up next" for a song (signed in, June 2026) |
| `data/playlist_cache` | ~4,300 | public playlists that contain one of your seeds: someone's mix ("playlist", weight 1) or an upload list, 80%+ one channel ("upload", 0.25) |
| `data/listens.csv` | your sittings | your YT Music plays, split at 12-minute gaps, in overlapping 8-song chunks |

Together they cover 42,546 of the 42,850 library songs. The model is rebuilt when any input changes,
which takes about 15 s, and is cached in `data/collab_model.pkl`.

## Checking it

```
.venv\Scripts\python scripts\eval_ytm.py radio --old 200      # vs YT Music's radios (5-fold, held out)
.venv\Scripts\python scripts\eval_ytm.py radio --write        # refit -> data/radio_weights.json
                                                              # (also --w-upload, --w-radio ...)
.venv\Scripts\python scripts\eval_ytm.py next                 # your next song, plays after --cut
.venv\Scripts\python -m pytest -q tests/test_radio.py
```

Refit after a big change to the radios, playlists or library. Without `data/radio_weights.json` the
server uses the weights built into `radio.py`.

`PLAYER_RADIO=0` brings back the old walk. Genre stations still use the walk.

## Limits

- **Coverage:** with a seed's own radio hidden, only 30% of YT Music's picks share any basket with the
  seed. For songs without a cached radio, matching YT Music song-for-song tops out low. The table's
  shape numbers matter as much as the 17%.
- **Thin songs:** a song with few baskets, mostly your own sittings, gets a looser radio. It also
  inherits cross-genre jumps you made yourself, e.g. OmarCameUp after Coronet Highlands, played back
  to back in three sittings.
- **Old radios:** they're from June, before the shift toward sped-up rap. Fetching radios for what you
  play now is track lists only, not audio, but it uses your signed-in account.
