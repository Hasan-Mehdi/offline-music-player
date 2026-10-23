"""Diorama's two posters (the listener's Sekiro and Hollow Knight prints, over the desk)
as pixel art, from a photo of the wall: each poster cropped, scaled to cells, cut to 16
colours of its own -> firmware/ui/posters.h.

  .venv\\Scripts\\python firmware\\tools\\gen_posters.py [photo] [--preview DIR]

Two sizes each: the poster whole for Explore (72 x 84 cells, its two shelves pinned on
the two posters), and the strip of it that shows over the monitor on the desk (38 x 17
cells: the desk's monitor hides the rest, as the real one does). The photo is the
listener's room (2026-10-11, 4000 x 2252); the crops are where the posters are in it.
"""
import argparse
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps

ROOT = Path(__file__).resolve().parents[2]
PHOTO = Path.home() / "Downloads" / "20261011_1600340.jpg"

# photo boxes (x0, y0, x1, y1), clear of the pothos hanging over both: the poster for
# Explore, and the strip the desk shows over its monitor (Sekiro's face and blade, the
# Knight's mask among the moths)
POSTERS = {
    "SK": {"whole": (1590, 620, 1950, 1040), "strip": (1640, 718, 1940, 852), "tint": (1, 1, 1)},
    "HK": {"whole": (2120, 640, 2480, 1060), "strip": (2100, 935, 2400, 1069), "tint": (.84, .92, 1.2)},
}
WHOLE = (72, 84)
STRIP = (38, 17)


def cells(img, box, size, tint=(1, 1, 1)):
    """the crop, its colour put right (the room is dim and warm: tint cools the Knight's
    greys back to violet), the paint smoothed into flat shapes, then scaled down to cells"""
    im = ImageOps.autocontrast(img.crop(box), cutoff=1.5)
    if tint != (1, 1, 1):
        im = Image.merge("RGB", [ch.point(lambda v, k=k: min(255, int(v * k))) for ch, k in zip(im.split(), tint)])
    im = im.filter(ImageFilter.MedianFilter(7))
    im = ImageEnhance.Color(im).enhance(1.6)
    im = ImageEnhance.Contrast(im).enhance(1.25)
    return im.resize((size[0] * 2, size[1] * 2), Image.BOX).resize(size, Image.LANCZOS)


def rgb565(c):
    r, g, b = c[:3]
    return ((r >> 3) << 11) | ((g >> 2) << 5) | (b >> 3)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("photo", nargs="?", default=str(PHOTO))
    ap.add_argument("--preview", default=None, help="write enlarged PNGs here")
    a = ap.parse_args()
    img = Image.open(a.photo).convert("RGB")
    out = ["/* Diorama's posters, from a photo of the wall (firmware/tools/gen_posters.py -- don't edit) */",
           "#ifndef CODA_POSTERS_H", "#define CODA_POSTERS_H", ""]
    for name, boxes in POSTERS.items():
        whole = cells(img, boxes["whole"], WHOLE, boxes["tint"])
        strip = cells(img, boxes["strip"], STRIP, boxes["tint"])
        both = Image.new("RGB", (WHOLE[0], WHOLE[1] + STRIP[1]))
        both.paste(whole, (0, 0))
        both.paste(strip, (0, WHOLE[1]))
        pq = both.quantize(colors=16, method=Image.Quantize.MEDIANCUT, kmeans=3, dither=Image.Dither.NONE)
        pal = pq.getpalette()[:48]
        pal = [tuple(pal[i:i + 3]) for i in range(0, 48, 3)]
        idx = pq.load()
        out.append(f"static const px16 PO_{name}_PAL[16] = {{ " +
                   ", ".join(f"0x{rgb565(c):04x}" for c in pal) + " };")
        for label, (w, h), y0 in (("", WHOLE, 0), ("_STRIP", STRIP, WHOLE[1])):
            out.append(f"static const char PO_{name}{label}[{h}][{w + 1}] = {{")
            for y in range(h):
                row = "".join("0123456789abcdef"[idx[x, y0 + y]] for x in range(w))
                out.append(f'    "{row}",')
            out.append("};")
        if a.preview:
            d = Path(a.preview)
            d.mkdir(parents=True, exist_ok=True)
            pq.convert("RGB").resize((both.width * 6, both.height * 6), Image.NEAREST).save(d / f"{name}.png")
        out.append("")
    out += ["#endif", ""]
    dst = ROOT / "firmware" / "ui" / "posters.h"
    dst.write_text("\n".join(out), encoding="utf-8", newline="\n")
    print("wrote", dst)


if __name__ == "__main__":
    main()
