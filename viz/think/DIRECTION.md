# Film direction — "Watching it think" (one decision, dilated)

Third film in this repo. Per the anti-AI-slop rule the direction is committed BEFORE code,
and per the repo's own history the STRUCTURE has to be new, not a reskin.

## What the two existing films are, and why this is neither

1. `viz/film/` — **chaptered explainer.** Chapter card, scene, chapter card, scene. A god
   camera over a t-SNE atlas of the embedding space.
2. `viz/transit/` — **one continuous ride.** No chapters, but still a camera moving across
   a static 2-D world (the same atlas, skinned as a city), with stops and reroutes.

Both are *a camera travelling over a map*. This one has **no map and no camera move at all.**
The frame is fixed like a printed sheet; what moves is the *field of candidates*, shoved
around by the formula. Where transit was "the player goes somewhere", this is
"the player makes up its mind".

## The structure: DILATE → SNAP → CHAIN

**Act 0 · THE GAP (0–14.6 s).** A track is ending. The now-bar's hairline runs out, the
audio stops, and the film freezes in the silence between two songs. On screen: the real
measured wall-clock of one `/api/next` decision on this machine. That silence is the
whole subject.

**Act 1 · THE DILATION (14.6–102.6 s).** That one real decision, stretched by ~10⁴.

*Where they come from (14.6–21.2 s).* Retrieval prints 54,045 → 800 → 400, compressed to
six seconds. It is a count, not a lesson.

*Three rows first (21.2–77.2 s).* **Three** of those 400 lift out of the retrieval band
and become named rows on the score axis, big type, generous space. Then the twelve terms
act on **just those three**, one at a time, in formula order. Every beat is a question in
ordinary words held alone for 2.4 s — "same artist too recently?" — with no number
anywhere on the sheet, not even the term's weight in the formula ladder; then the term is
named, read and weighed; then it shoves the three rows; then, only once they have stopped,
one line of verdict lands per row: *koteon played 2 tracks ago — barred*, *the last six
already sound like this — struck*. Under them, one line about the decision (the lead
changing hands) and one small line of the field's own numbers (*29 of 400 moved,
strongest −0.500*), which is the wall being trailed. The five terms that touch none of the
three collapse into a single **NO OPINION** beat that says why each is quiet, instead of
five separate shrugs — and they stay struck through in the formula ladder afterwards, so a
term that said nothing can never read as a term that pushed.

The three rows are not authored. The page picks them out of the decision itself: every row
that ever holds the running lead is a real protagonist, and of those it takes the one a
guardrail (cooldown / skip / pref_artist) hits hardest and the one the fatigue-heard
machinery hits hardest; the winner is the third. In this pinned decision that is
*purrfect day :3* (koteon, barred by cooldown −0.500), *Strawberry Shortcake*
(Golden Grooves, the winner) and *i love cats :3* (yawn., struck by fatigue −0.288) — and
the lead genuinely changes hands twice inside the three, at cooldown and again at fatigue.
The walk ends on the arithmetic that actually decided it: **it wins by losing least**
(+1.418 −0.389 = 1.029 against +1.495 −0.961 and +1.449 −0.482).

*The reveal (77.2–91.2 s).* The other 397 **slam in around the three**, which keep their
exact positions on the axis and glide into their ledger rows; one big field-shove sound,
not 400 ticks. Everything rewinds to zero, and the whole cascade replays at field scale in
8.4 s with **not one word of explanation** — a payoff, not a lesson. Then `argmax`: the
field re-sorts by score (the only "camera move" in the film is 400 rows sorting
themselves), the ε draw prints, and the winner locks.

**Act 2 · THE SNAP (102.6–135.6 s).** Time returns to ×1. The same anatomy, now three
seconds a decision, ten times in a row — the cascade a ripple instead of a lecture. Each
winner drops onto a growing tape of sleeves at the foot of the page. One of the ten is a
real ε draw under 0.15: the argmax gets struck through in red and the engine takes the
first never-played track in the top twelve instead. That is the only red-dominant frame in
the film. This act's pace is deliberately untouched — the fast chain was never the part
that lost anyone.

**Act 3 · THE LOG (135.6–151 s).** A printed excerpt from `data/next_trace.jsonl` — an ε
swerve that actually happened during real listening, with its real timestamp — then the
closing slug.

### Why the teaching was rebuilt (cut 3)

Cut 1 was "hard to understand, too speedy". Cut 2 added the plain-language questions and
halved the speed, and the verdict was that it "needs more work than that quick pass". The
diagnosis was not pace: Act 1 was teaching twelve terms on a 400-row field, which is a
wall of ticks at any speed, and it spent 15 s on a *HOW TO READ THIS* primer that existed
only to survive that wall. Cut 3 keeps the film's identity (dilate → snap → chain, the
same pinned decision, real data only, Acts 2–3 untouched) and moves the teaching onto
three real rows, where a term's effect is one line of English instead of a statistical
distribution. The primer is gone — the three rows arriving at zero *are* the grammar
lesson, in 4.6 s. Teaching better came out shorter: 180 s → 151 s.

## Materials (record-shop poster, per docs/DESIGN_NOTES.md)

- Paper `#f4f4f0`, ink `#141414`, IKB `#002fa7` = a term pushing a track UP,
  signal red `#e0301e` = a term pushing it DOWN. Exactly the `viz/autoplay_ab.html` key.
  Album art is the only other colour on the page.
- Type: Archivo Black for the display slugs and the term names (huge, tight, uppercase);
  Consolas mono for every number. No third face.
- Layout devices: hairline rules, crop marks, a single vertical zero-axis, tally ticks,
  solid black strips. Sheet is fixed; nothing pans, nothing zooms.
- Motion: transform-only shoves with a hard mechanical ease. Terms land like a stamp.
  No easing-in-out drift, no glow, no particles, no gradients.
- Sound: the dilated act is nearly silent on purpose (print-machine ticks only) — the
  gap is meant to feel like a held breath. One question = one tick, one term name = one
  stamp, one shove = one triangle-wave slide, and the whole field arriving = a single
  low `slam`, synthesised identically in `think.html` (WebAudio) and `mux.py` (numpy) so
  the page and the mp4 sound the same. Music returns the instant a winner locks:
  real snippets of the real winning tracks, each moved by its own `r128_gain_db` to the
  player's −14 LUFS target, so the tape is level-matched the way the player is. The
  player's rule is attenuate-only (it never boosts), so `build_data.py` measures what
  that produced and adds a bounded make-up — at most 12 dB — to any snippet the clamp
  left inaudible. The r128 tag still sets the relative levels.

## Avoided

No dark+neon, glow, glassmorphism, scanlines, HUD ticks, techy fonts, sidebar shell.
No chapter cards (film 1's tell), no travelling camera over an atlas (film 2's tell).
