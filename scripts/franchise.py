"""Game franchises, for autoplay's sense of proportion.

The library is game music heavy, and a listener thinks in franchises ("Sonic music",
"Pokémon music") where the ranker only sees sound. Measured 2026-10-11: walking 10 steps
from 80 history seeds, Sonic was 9.0% of the picks that landed outside the seed's own
franchise -- twice its library share (4.4%, swollen by big remix channels never played)
and over four times the listener's own share (2.0% of the last 90 days of YouTube Music).
Mario (6.1% / 3.6% / 5.7%) and Pokémon (5.6% / 4.5% / 7.0%) were in proportion. Not a
hub in the embedding space (its tracks' k-occurrence and density match other game music);
upbeat remixes just sit next to everything upbeat, and both the taste pull and fatigue's
push outward kept landing there.

franchise_of() tags a track from its title / album / channel (first rule wins; None for
everything that isn't a known game franchise). franchise_bias() turns your listening share
against what autoplay serves of a franchise (scripts/franchise_calibrate.py measures that;
the library share is the fallback, and a poor one -- Sonic gets 2x its library share, Zelda
1.1x) into a per-franchise entry bias in [FLOOR, 0]: franchises served no more than you
play them get nothing, over-served ones a capped penalty -- never a boost, never enough to
rule a franchise out. personalize.rank_next uses it (fr_bias) with a franchise cooldown
(fr_cool) scaled by the same bias, so only over-served franchises are kept from runs."""
from __future__ import annotations

import math
import re

RULES = [
    ("sonic", r"\bsonic\b|green hill|chemical plant|stardust speedway|ice cap zone|marble garden|hydrocity|"
              r"flying battery|mushroom hill|launch base|sandopolis|lava reef|angel island|studiopolis|"
              r"press garden|oil ocean|casino night|metropolis zone|spring yard|labyrinth zone|star light zone|"
              r"scrap brain|mirage saloon|palmtree panic|crisis city|city escape|\bzone act\b"),
    ("pokemon", r"pok[eé]mon|pokemon|\bpmd\b|mystery dungeon"),
    ("zelda", r"zelda|hyrule|majora|ocarina|link'?s awakening|breath of the wild|tears of the kingdom|"
              r"skyward sword|wind waker|twilight princess"),
    ("kirby", r"\bkirby\b|dream land|dreamland"),
    ("mario", r"\bmario\b|bowser|yoshi|luigi|wario|princess peach|bob-omb|\bsmb\b"),
    ("donkey_kong", r"donkey kong|\bdkc\b"),
    ("metroid", r"metroid|samus"),
    ("final_fantasy", r"final fantasy|\bff ?(?:i|ii|iii|iv|v|vi|vii|viii|ix|x|xi|xii|xiii|xiv|xv|xvi)\b"),
    ("persona", r"\bpersona\b|shin megami|\bsmt\b"),
    ("undertale", r"undertale|deltarune|toby fox"),
    ("chrono", r"chrono (?:trigger|cross)"),
    ("xenoblade", r"xenoblade"),
    ("castlevania", r"castlevania|悪魔城"),
    ("megaman", r"mega ?man|rockman"),
    ("fire_emblem", r"fire emblem"),
    ("smash", r"smash bros|super smash"),
    ("animal_crossing", r"animal crossing"),
    ("splatoon", r"splatoon"),
    ("dragon_quest", r"dragon quest"),
    ("kingdom_hearts", r"kingdom hearts"),
    ("earthbound", r"earthbound|mother 3"),
    ("street_fighter", r"street fighter"),
    ("touhou", r"touhou|東方"),
    ("ace_attorney", r"ace attorney|phoenix wright|逆転裁判"),
    ("genshin", r"genshin|honkai|star rail"),
    ("minecraft", r"minecraft|\bc418\b"),
    ("hollow_knight", r"hollow knight|silksong"),
    ("celeste", r"\bceleste\b"),
    ("octopath", r"octopath"),
    ("halo", r"\bhalo\b"),
]
NAMES = [n for n, _ in RULES]               # ids are 1 + this index (0 = none) on the device
_RX = [(n, re.compile(p, re.I)) for n, p in RULES]

SMOOTH = 0.005        # shares are smoothed by this before the log ratio
FLOOR = -1.0          # the strongest entry bias (a ratio of 1/e or less)


def franchise_of(title, artist="", album=""):
    s = f"{title or ''} | {album or ''} | {artist or ''}"
    for n, rx in _RX:
        if rx.search(s):
            return n
    return None


def franchise_bias(of, library, listens, exposure=None):
    """{franchise: bias in [FLOOR, 0]} from your share of `listens` (video ids, one per
    listen) against what autoplay serves of it: `exposure` {franchise: share of picks}
    from scripts/franchise_calibrate.py when there is one, else the share of `library`
    (video ids) each franchise holds. `of` is {video_id: franchise or None}."""
    lib_n, lis_n = {}, {}
    for v in library:
        f = of.get(v)
        if f:
            lib_n[f] = lib_n.get(f, 0) + 1
    for v in listens:
        f = of.get(v)
        if f:
            lis_n[f] = lis_n.get(f, 0) + 1
    L, N = max(1, len(library)), max(1, len(listens))
    out = {}
    for f, c in lib_n.items():
        served = exposure[f] if exposure and f in exposure else c / L
        r = math.log((lis_n.get(f, 0) / N + SMOOTH) / (served + SMOOTH))
        out[f] = max(FLOOR, min(0.0, r))
    return out
