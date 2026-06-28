# Suite report

_generated 2026-06-27 19:32_

## MuQ embedding (incremental) — OK

```
MuQ-MuLan on cuda: 2022 tracks in library
  reusing 1098 cached embeddings
  embedded 100 new...
  embedded 200 new...
  embedded 300 new...
  embedded 400 new...
  embedded 500 new...
  embedded 600 new...
  embedded 700 new...
  embedded 800 new...
  embedded 900 new...
saved (2022, 512) (924 new) -> data/muq_embeddings.npz
artist-coherence@5: 16.5%  (baseline 0.84%, lift 19.6x)
```

## Collaborative method eval — OK

```
seeds with radios: 510 | avg basket: 50.2

method          r@50     r@100     r@200     r@500       MRR  nDCG@100
----------------------------------------------------------------------
count           7.23     14.34     20.83     30.39      0.01     15.64
pos             8.46     15.56     21.08     31.50      0.01     18.48
s2v_cent        1.23      1.35      2.82      7.23      0.00      2.01
s2v_topk        1.72      2.33      4.04      7.23      0.01      4.68
hybrid          9.68     15.69     21.57     29.90      0.02     19.00

(r@K and nDCG in %, MRR raw. Higher is better.)
```

## Genre map + clustering — OK

```
2022 tracks
clusters (16):
  city pop (Shiny Mewtube)  -  56 tracks
  drum and bass (SEGA SOUND TEAM)  -  87 tracks
  city pop (Artzie Music)  -  39 tracks
  hip hop rap (OmarCameUp)  -  204 tracks
  soundtrack (Braxton Burks)  -  156 tracks
  pop (The Noble Demon)  -  138 tracks
  ambient (Cha Chingo Christ.)  -  162 tracks
  pop (Miki Matsubara)  -  125 tracks
  city pop (WiiPlayz)  -  89 tracks
  pop (DJ EXE)  -  105 tracks
  8-bit video game music (RRThiel)  -  148 tracks
  jazz (Cha Chingo Christ.)  -  91 tracks
  pop (Mewmore)  -  159 tracks
  soundtrack (Rozen)  -  127 tracks
  pop (Macross 82-99)  -  188 tracks
  soundtrack (Rozen)  -  148 tracks

wrote viz/genre_map.html, viz/06_genre_map.png, data/clusters.csv
```

## Playlists (m3u) — OK

```
2022 library files indexed
16 genre playlists
6 mood mixes
playlists -> viz/playlists
```

## Autoplay tuning — OK

```
obj  smooth  adiv  cdiv   beta cd eps
 0.44    0.87  0.93  0.17    0.3  6  0.2
 0.44    0.87  0.89  0.18    0.3  6  0.1
 0.43    0.86  0.85  0.19    0.6  4  0.2
 0.43    0.86  0.87  0.16    1.0  4  0.2
 0.43    0.87  0.87  0.18    0.6  2  0.2
 0.43    0.87  0.88  0.16    0.6  6  0.2
 0.43    0.89  0.93  0.20    0.0  4  0.2
 0.42    0.87  0.88  0.16    0.6  6  0.1
 0.42    0.87  0.85  0.17    0.3  4  0.2
 0.42    0.88  0.92  0.13    1.0  6  0.0

best -> {'alpha': 1.0, 'beta': 0.3, 'cooldown': 6, 'epsilon': 0.2} (written to data/autoplay_config.json)
```

## Visualizations — OK

```
t-SNE...
01 done
02 done
03 done
04 done
05 done
all figures written to viz/
```

## Unit tests (pytest) — OK

```
......                                                                   [100%]
6 passed in 0.99s
```
