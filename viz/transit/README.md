# Night Service — one ride through a music library

~129 s motion film over real MuQ-MuLan embeddings of this library. One continuous
camera ride follows the player's actual autoplay formula (1.0·sound + 0.3·co-play −
artist cooldown(6), ε 0.20) through 17 real stops with a real clip crossfading at
every one. Genre districts are neighbourhoods you cross; text→music search is a
mid-ride REQUEST STOP that reroutes the bus; the duplicate upload is something you
pass; the only overview is the final pull-up revealing the whole route. Ends in an
explorable map (hover stations, click red rings to hear them). Direction:
`DIRECTION.md`. Companion piece to `viz/film/` (same data, different structure and
material world).

## Artifacts
- `wayfinding_film.html` — standalone, double-clickable, full sound
- `wayfinding_film.mp4` — rendered video with soundtrack

## Rebuild
```
python viz/transit/build_data.py   # numpy-only; reuses viz/film/_cache.npz (no GPU)
python viz/transit/bundle.py       # inline data+font -> wayfinding_film.html
node capture.js preview [t ...]    # design stills (headless Edge)
node capture.js render 30          # frames/ + audio_cues.json
python mux.py                      # soundtrack from cues + mux -> wayfinding_film.mp4
```
`smoke.js` click-plays headless and checks clock/audio/errors; `smoke2.js t0 t1`
probes continuous playback through a window.
