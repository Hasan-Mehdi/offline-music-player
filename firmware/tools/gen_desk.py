"""Diorama's shelf and PC case as pixel art from the photo of the desk wall, the way the
posters are (gen_posters.py): what stands on the shelf (the succulents, the piranha plants,
the frame, the fern, the clock, Luigi, the block figures, the pothos) and the silver case
on its walnut foot. Each thing is cut out of the wall (GrabCut, inside a box drawn round it
by hand), its colour put right, smoothed into flat shapes, scaled to cells and cut to a
palette -> firmware/ui/desk_art.h.

  .venv\\Scripts\\python firmware\\tools\\gen_desk.py [photo] [--preview DIR]

The scene (th_dio.h) is drawn in cells at the photo's own scale along the shelf: the
shelf's 121 cells are its 1420 photo pixels, its top face is cell row 24; what stands
taller than the 24 rows above it is cut off by the top of the screen, as in a close-up.
'.' = see-through. The clock's face is left for the scene to draw (its hands move); where
it sits goes in the header.
"""
import argparse
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageEnhance, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parents[2]
PHOTO = Path.home() / "Downloads" / "20261011_1600340.jpg"
OUT = ROOT / "firmware" / "ui" / "desk_art.h"

SCALE = 1420 / 121                       # photo pixels per cell, from the shelf's width
SHELF_X0, SHELF_TOP = 1300, 428          # the shelf's left end and its top face, in the photo
SHELF_CELL_X0, SHELF_ROWS = 20, 24       # ... and in the scene: x, and the rows above it
SHELF_W = 127                            # cells: the shelf and the pothos past its end
CLOCK = (2200, 322, 86)                  # the clock in the photo: centre x, y, radius
# the things on the shelf, boxes in the photo (x0, y0, x1, y1), drawn round each by hand
THINGS = [
    (1325, 355, 1390, 438),              # the little green figure
    (1340, 278, 1505, 438),              # the aloe in its white pot
    (1490, 285, 1595, 438),              # the succulent in its white pot
    (1525, 120, 1665, 438),              # the piranha plant and its stalk
    (1585, 212, 1735, 432),              # the silver frame
    (1595, 325, 1875, 434),              # the blue disc, the green train
    (1660, 0, 2130, 430),                # the fern in its black pot
    (2105, 230, 2295, 418),              # the clock
    (2255, 185, 2470, 418),              # Luigi
    (2300, 40, 2470, 330),               # the second piranha plant
    (2430, 335, 2555, 410),              # the blue box figure
    (2540, 290, 2665, 404),              # the yellow block figure
    (2465, 0, 2800, 470),                # the pothos
]
CASE_BOX = (2822, 1498, 3228, 2018)      # the case and its walnut foot
CASE_CELLS = (25, 34)
KEYS = "0123456789abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ"


def cutout(img, boxes, region):
    """foreground mask inside `region` (photo coords): GrabCut, everything outside the
    boxes taken as wall"""
    x0, y0, x1, y1 = region
    a = cv2.cvtColor(np.asarray(img.crop(region)), cv2.COLOR_RGB2BGR)
    mask = np.full(a.shape[:2], cv2.GC_BGD, np.uint8)
    for bx0, by0, bx1, by1 in boxes:
        mask[max(0, by0 - y0):max(0, by1 - y0), max(0, bx0 - x0):max(0, bx1 - x0)] = cv2.GC_PR_FGD
    bgd, fgd = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
    cv2.grabCut(a, mask, None, bgd, fgd, 6, cv2.GC_INIT_WITH_MASK)
    fg = ((mask == cv2.GC_FGD) | (mask == cv2.GC_PR_FGD)).astype(np.uint8) * 255
    fg = cv2.morphologyEx(fg, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))
    return Image.fromarray(fg)


def painted(im, median=5, color=1.45, contrast=1.2, cutoff=1.0):
    """the room is dim and warm: autocontrast, flat shapes, colour back"""
    im = ImageOps.autocontrast(im, cutoff=cutoff)
    im = im.filter(ImageFilter.MedianFilter(median))
    im = ImageEnhance.Color(im).enhance(color)
    return ImageEnhance.Contrast(im).enhance(contrast)


def to_cells(im, size):
    return im.resize((size[0] * 3, size[1] * 3), Image.BOX).resize(size, Image.LANCZOS)


def palette_map(cells_im, alpha, n):
    """index map ('.' see-through) and the palette: n colours of the opaque cells' own"""
    a = np.asarray(cells_im).copy()
    if alpha is not None:
        a[~alpha] = a[alpha].mean(axis=0)            # see-through cells don't take a colour
    q = Image.fromarray(a).quantize(colors=n, method=Image.Quantize.MEDIANCUT, dither=Image.Dither.NONE)
    pal = q.getpalette()[: 3 * n]
    idx = np.asarray(q)
    h, w = idx.shape
    rows = ["".join(KEYS[idx[y, x]] if alpha is None or alpha[y, x] else "." for x in range(w)) for y in range(h)]
    return rows, [tuple(pal[3 * i: 3 * i + 3]) for i in range(n)]


def rgb565(c):
    r, g, b = c
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def emit(name, rows, cols, out):
    out.append(f"static const char {name}[{len(rows)}][{len(rows[0]) + 1}] = {{")
    out += [f'    "{r}",' for r in rows]
    out.append("};")
    out.append(f"static const px16 {name}_PAL[{len(cols)}] = {{ " +
               ", ".join(f"0x{rgb565(c):04x}" for c in cols) + " };")
    out.append("")


def preview(rows, cols, path, scale=6, bg=(0xd0, 0xbc, 0x9e)):
    h, w = len(rows), len(rows[0])
    im = Image.new("RGB", (w, h), bg)
    for y, r in enumerate(rows):
        for x, ch in enumerate(r):
            if ch != ".":
                im.putpixel((x, y), cols[KEYS.index(ch)])
    im.resize((w * scale, h * scale), Image.NEAREST).save(path)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photo", nargs="?", default=str(PHOTO))
    ap.add_argument("--preview", default=None)
    a = ap.parse_args()
    img = Image.open(a.photo).convert("RGB")

    # --- the shelf's things, standing on its top face
    region = (SHELF_X0, SHELF_TOP - int(SHELF_ROWS * SCALE), SHELF_X0 + int(SHELF_W * SCALE), SHELF_TOP)
    full = (SHELF_X0, 0, region[2], SHELF_TOP + 40)              # GrabCut sees the things whole
    fg = cutout(img, THINGS, full)
    fg = fg.crop((0, region[1], region[2] - region[0], region[3] - full[1]))
    size = (SHELF_W, SHELF_ROWS)
    cells = to_cells(painted(img.crop(region)), size)
    alpha = np.asarray(fg.resize(size, Image.BOX)) > 120
    cx, cy, cr = CLOCK
    ccx, ccy, ccr = (cx - region[0]) / SCALE, (cy - region[1]) / SCALE, cr / SCALE
    yy, xx = np.mgrid[0:SHELF_ROWS, 0:SHELF_W]
    alpha &= ((xx + .5 - ccx) ** 2 + (yy + .5 - ccy) ** 2) > (ccr + .5) ** 2   # the face is the scene's
    rows, cols = palette_map(cells, alpha, 32)
    print(f"shelf: {SHELF_W} x {SHELF_ROWS} cells, clock at ({SHELF_CELL_X0 + ccx:.1f}, {ccy:.1f}) r {ccr:.1f}")

    # --- the case: silver, the lattice front with its blue light, the walnut foot
    cfg = cutout(img, [(CASE_BOX[0] + 8, CASE_BOX[1] + 8, CASE_BOX[2] - 8, CASE_BOX[3] - 4)],
                 (CASE_BOX[0] - 40, CASE_BOX[1] - 40, CASE_BOX[2] + 40, CASE_BOX[3] + 20))
    cfg = cfg.crop((40, 40, 40 + CASE_BOX[2] - CASE_BOX[0], 40 + CASE_BOX[3] - CASE_BOX[1]))
    case = to_cells(painted(img.crop(CASE_BOX), median=3, color=1.15, contrast=1.3), CASE_CELLS)
    calpha = np.asarray(cfg.resize(CASE_CELLS, Image.BOX)) > 120
    crows, ccols = palette_map(case, calpha, 16)

    out = ["/* Diorama's shelf and PC case, from the photo of the desk (firmware/tools/gen_desk.py -- don't edit) */",
           "#ifndef CODA_DESK_ART_H", "#define CODA_DESK_ART_H", "",
           f"#define DA_SHELF_X {SHELF_CELL_X0}",
           f"#define DA_CLOCK_X {SHELF_CELL_X0 + ccx:.2f}f", f"#define DA_CLOCK_Y {ccy:.2f}f",
           f"#define DA_CLOCK_R {ccr:.2f}f", ""]
    emit("DA_SHELF", rows, cols, out)
    emit("DA_CASE", crows, ccols, out)
    out.append("#endif")
    OUT.write_text("\n".join(out) + "\n", encoding="utf-8")
    print("wrote", OUT)
    if a.preview:
        p = Path(a.preview)
        p.mkdir(parents=True, exist_ok=True)
        preview(rows, cols, p / "shelf.png")
        preview(crows, ccols, p / "case.png")


if __name__ == "__main__":
    main()
