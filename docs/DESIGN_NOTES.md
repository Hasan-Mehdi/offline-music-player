# Design notes — why AI-built UIs all look the same, and how to not

Distilled from the AI Labs video on design skills (2026-07), keeping only what applies
to this project (a personal offline music player, not a landing page).

## The core diagnosis

Models trained on the same corpus reach for the statistically safest design choice at
every decision point. Each choice looks fine; the sum is the same site everyone else got.
The fix is NOT better taste per-decision — it's **committing to one specific design
direction before writing any code, then staying consistent with it even when a "safer"
choice appears mid-build.**

## The recognized AI-slop tells (avoid all of these)

- Overused fonts: Inter, Space Grotesk, Chakra Petch, JetBrains Mono as "personality"
- Purple/neon gradients, glow effects, glassmorphism blur panels
- Dark theme + single neon accent as the default "cool" move
- Decorative tech noise: scanlines, chamfered corners, `//` prefixes, HUD tick marks,
  uppercase letterspaced microlabels on everything
- The Spotify shell reflex: top bar + left sidebar + card grids in `auto-fill` columns
- Hover states that are always "background lightens + tiny lift"
- Scroll-reveal as the only animation idea
- One general idea of "good design" applied regardless of what the product is

## Principles worth keeping

1. **Direction first.** Write the direction down (one sentence + a materials list:
   palette, type, layout devices, motion rules). Every component obeys it or gets cut.
2. **Design for the product's actual character.** A personal record collection wants a
   record-collection language (sleeves, liner notes, crate dividers, receipts, print),
   not a SaaS dashboard language. Match the design system to the domain, per the
   "industry-tuned" idea — don't inherit a generic one.
3. **Functional UI ≠ marketing UI.** Library tables, queues, transport controls should
   be boring-correct and dense where density serves use; personality lives in layout,
   type, and materials — not in making buttons weird.
4. **Motion: few, physical, cheap.** Animate only transform/opacity (compositor-friendly,
   the GSAP skill's actual performance lesson). Motion should express a mechanism
   (a record spins, a needle settles), not decorate a scroll.
5. **Don't shrink desktop onto the handheld.** The small-touchscreen build has its own
   rules: thumb-reach placement for primary controls, fewer simultaneous surfaces.
6. **Real assets over placeholders.** We have 10k+ real album covers — the art IS the
   visual wealth; the chrome should get out of its way.

## Directions already tried and REJECTED (do not revisit)

1. YT-Music clone (red accent, emojis) — session A
2. Electric violet `#7c6bff` on black, disc logo — "AI-ish"
3. Warm cream + editorial serif + amber ("analog hi-fi") — "classic claude design same
   font and everything lol. Embarassing." → cream+serif territory is BANNED
4. Mint-on-true-black techno HUD ("night drive": Chakra Petch/Space Grotesk, scanlines,
   chamfers, chronograph bezel, keycap buttons, neon spectrum ring) — "still looks so ai
   generated"

What survived every round came from the user: the click wheel, auto sneak-peek, sound
effects. Rejections were always the skin — and every skin was pasted on the same
unchanged Spotify shell (topbar + left sidebar + card grids + bottom bar).

## Direction committed (2026-07-01): "record-shop poster"

Swiss/gig-poster print language on stark white — NOT cream, NOT serif, NOT dark+neon:
- Ground `#f4f4f0` white, ink `#141414`, accent International Klein Blue `#002fa7`,
  signal red `#e0301e` strictly for live/playing/dislike markers. Album art supplies
  all other color.
- Display type: Archivo Black (heavy poster grotesk), tight tracking, huge sizes.
  Body: system-ui. Durations in plain mono, no letterspacing games.
- Structure: masthead + big nav words (NO left sidebar), content edge-to-edge,
  bottom now-bar as a solid black strip. Genres/stations as giant text lists with
  hairline rules (crate dividers), not colored tiles.
- Art: butted edge-to-edge mosaics, square corners, no borders/shadows/hover-lift.
  Hover/active = print inversion (black↔white / blue).
- Wheel: keep all interaction + sfx; re-materialize as covers with hard white gaps,
  black vinyl-silhouette hub, white ink sunburst visualizer, round art "label" center.
  No gradients, glow, bezel ticks, or HUD microcopy.
- Motion: quick mechanical transform/opacity only; no float/pulse/glow loops.
