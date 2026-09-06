#!/usr/bin/env python3
"""Cut a stencil from a photograph.

    python3 pipeline/stencil.py photos/<slug>/*.jpg \\
        --keep 0.066 --speck 60 --long 800 --out app/img/<slug>

Not part of the build, and the one thing in pipeline/ that needs an install:
Pillow, to read the photograph and write the PNG. No numpy. The build only
needs the stencils this writes, which are committed; the photographs are not.

A stencil is the edges the camera will see, so the edge map here is the
player's edgeMap in app/lens.js: the same arithmetic in the same order, done
in plain Python over the pixel list. Not with ImageFilter.Kernel, which
refuses float images and clips a signed gradient to 0-255 on an L image, so
the Sobel cannot be done with it. A 600x800 frame takes a second or two
this way, which is fine offline.

Of the edge map the strongest fraction --keep of the interior is kept, then
every blob smaller than --speck pixels is dropped, because texture (granite,
gravel, foliage) survives the threshold as scattered specks while an outline
survives as one long piece. The lines are then thickened by one pixel to the
two or three the scorer's masks expect. Strong outlines make the stencil,
fine detail does not, and the preview written beside each PNG is where you
find out: a stencil is good when a person could tell what it is. Too much
texture: raise --speck first, then lower --keep, then ask for another photo.

For each photograph this writes <id>-stencil.png and <id>-stencil-preview.jpg
into --out and prints one JSON stencil entry to stdout, for pasting into the
hunt file. Everything that is not an entry goes to stderr, so the output can
be redirected and pasted whole.
"""

import argparse
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

BASE = Path(__file__).resolve().parent.parent
APP = BASE / "app"

ORANGE = (255, 61, 0, 255)      # every kept pixel; everything else is (0, 0, 0, 0)

# sqrt(2) x 4 x 255, the Sobel ceiling, as in lens.js. It fixes the width of
# the histogram's bins, so it has to be the same number there and here.
MAXMAG = 1443


def stencil_id(photo):
    """The photo's filename without its extension, lower-cased, spaces to
    hyphens, so it is safe as a stencil id and in a URL."""
    return photo.stem.lower().replace(" ", "-")


def fit_long(im, long):
    """Resize so the long side is `long` px, keeping the aspect ratio. Nearly
    every phone photo is 3:4, so the default 800 gives 600x800."""
    w, h = im.size
    k = long / max(w, h)
    size = (max(1, round(w * k)), max(1, round(h * k)))
    return im.resize(size, Image.Resampling.LANCZOS)


def edge_map(px, w, h):
    """Exactly what the player's edgeMap computes, over a list of (r, g, b)
    tuples: grey, a 3x3 box blur clamped at the border, a 3x3 Sobel over the
    interior, the magnitude, and a 256-bin histogram of the interior from
    which the 99th percentile is read and everything scaled so that it is
    one, clipped. The loops are the JavaScript's, line for line, so that a
    change to one is a change to both or a stencil that no longer matches
    the frame it is scored against."""
    n = w * h
    g = [0.0] * n
    for i in range(n):
        r, gg, b = px[i]
        g[i] = 0.299 * r + 0.587 * gg + 0.114 * b
    # The blur clamps at the border: a pixel outside the frame reads as its
    # nearest pixel inside, as in lens.js. Left at zero, the border makes the
    # Sobel see a bright line all the way round the frame, in the live view
    # and in every stencil alike, and a line that is always there is a match
    # for free: with the stencil filling the rectangle, a blank wall passed.
    b = [0.0] * n
    for y in range(h):
        r0, r1, r2 = max(0, y - 1) * w, y * w, min(h - 1, y + 1) * w
        for x in range(w):
            x0, x2 = max(0, x - 1), min(w - 1, x + 1)
            b[r1 + x] = (g[r0 + x0] + g[r0 + x] + g[r0 + x2]
                         + g[r1 + x0] + g[r1 + x] + g[r1 + x2]
                         + g[r2 + x0] + g[r2 + x] + g[r2 + x2]) / 9
    mag = [0.0] * n
    hist = [0] * 256
    sqrt = math.sqrt
    for y in range(1, h - 1):
        for x in range(1, w - 1):
            i = y * w + x
            gx = (-b[i - w - 1] + b[i - w + 1] - 2 * b[i - 1] + 2 * b[i + 1]
                  - b[i + w - 1] + b[i + w + 1])
            gy = (-b[i - w - 1] - 2 * b[i - w] - b[i - w + 1]
                  + b[i + w - 1] + 2 * b[i + w] + b[i + w + 1])
            mg = sqrt(gx * gx + gy * gy)
            mag[i] = mg
            hist[min(255, int(mg * 255 / MAXMAG))] += 1
    # The histogram holds the interior only: the one-pixel border has no
    # gradient. Counting to 99% of the whole frame instead would never get
    # there on a small frame, and the loop would run off the end and hand
    # back the Sobel ceiling as the "percentile".
    want = (w - 2) * (h - 2) * 0.99
    seen = 0
    bin = 0
    while bin < 255:
        seen += hist[bin]
        if seen >= want:
            break
        bin += 1
    p99 = max(1e-6, (bin + 1) * MAXMAG / 255)
    for i in range(n):
        mag[i] = min(1, mag[i] / p99)
    return mag


def threshold(mag, w, h, keep):
    """The pixels strictly above the value at the (1 - keep) quantile, as a
    list of 0/1 the size of the frame. Strictly above, so a frame with no
    gradient at all keeps nothing rather than everything.

    The quantile is taken over, and only ever set within, the pixels whose
    Sobel saw a blurred neighbour on every side: two pixels in from the
    edge. The blur is not computed on the one-pixel border, so the Sobel
    one pixel in sees a black frame and reports a strong edge all the way
    round the picture, blank or not. The player's frame has that ring too,
    and a stencil that carried it would score a match on any view."""
    inner = [mag[y * w + x] for y in range(2, h - 2) for x in range(2, w - 2)]
    mask = [0] * (w * h)
    if not inner:
        return mask
    inner.sort()
    at = min(len(inner) - 1, int(len(inner) * (1 - keep)))
    t = inner[at]
    for y in range(2, h - 2):
        for x in range(2, w - 2):
            i = y * w + x
            if mag[i] > t:
                mask[i] = 1
    return mask


def drop_specks(mask, w, h, speck):
    """Clear every 8-connected component of set pixels with fewer than
    `speck` pixels, in place. A plain stack, not recursion: an outline is
    one component thousands of pixels long and would blow the stack."""
    n = w * h
    # 1 is set and not yet visited, 2 is set and visited, so the visit needs
    # no second list the size of the frame.
    for start in range(n):
        if mask[start] != 1:
            continue
        comp = [start]
        mask[start] = 2
        stack = [start]
        while stack:
            i = stack.pop()
            x = i % w
            y = i // w
            for yy in (y - 1, y, y + 1):
                if yy < 0 or yy >= h:
                    continue
                for xx in (x - 1, x, x + 1):
                    if xx < 0 or xx >= w:
                        continue
                    j = yy * w + xx
                    if mask[j] == 1:
                        mask[j] = 2
                        stack.append(j)
                        comp.append(j)
        if len(comp) < speck:
            for i in comp:
                mask[i] = 0
    for i in range(n):
        if mask[i]:
            mask[i] = 1


def src_for(out, png):
    """What goes in the hunt file's `src`: relative to app/ when the stencil
    was written under it, which is where a shipped stencil lives, else the
    path as it was given, which is where a trial run or a test put it."""
    try:
        return png.resolve().relative_to(APP.resolve()).as_posix()
    except ValueError:
        return (Path(out) / png.name).as_posix()


def pixels(im):
    """The frame as one flat list of (r, g, b) tuples, row after row, the
    order the loops above index it in. Pillow 12 renamed getdata and warns
    on the old name; an older Pillow has only the old name."""
    if hasattr(im, "get_flattened_data"):
        return list(im.get_flattened_data())
    return list(im.getdata())


def make(photo, out, keep, speck, long):
    """One photograph to one stencil, its preview, and its hunt-file entry."""
    with Image.open(photo) as opened:
        # The EXIF orientation first, so a portrait photo is portrait: a
        # phone stores the sensor's landscape frame and a tag saying which
        # way up it was held.
        im = ImageOps.exif_transpose(opened).convert("RGB")
    im = fit_long(im, long)
    w, h = im.size

    mag = edge_map(pixels(im), w, h)
    mask = threshold(mag, w, h, keep)
    drop_specks(mask, w, h, speck)
    if not any(mask):
        print(f"{photo}: no edges found, the stencil is empty", file=sys.stderr)

    # Thicken by one pixel. MaxFilter on a 0/255 image gives back only 0
    # and 255, so the alpha it becomes is a clean mask with no half-values
    # for the scorer to threshold.
    lines = Image.new("L", (w, h))
    lines.putdata([255 if m else 0 for m in mask])
    lines = lines.filter(ImageFilter.MaxFilter(3))
    stencil = Image.merge("RGBA", (
        lines.point(lambda a: ORANGE[0] if a else 0),
        lines.point(lambda a: ORANGE[1] if a else 0),
        lines.point(lambda a: ORANGE[2] if a else 0),
        lines,
    ))

    sid = stencil_id(photo)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    png = out / f"{sid}-stencil.png"
    stencil.save(png, optimize=True)
    # The set fraction after thickening, at a glance: a stencil that is
    # mostly texture is a big number before it is a bad picture.
    filled = lines.histogram()[255] / (w * h)
    print(f"wrote {png} {w}x{h}, {filled:.1%} set", file=sys.stderr)

    preview = im.convert("RGBA")
    preview.alpha_composite(stencil)
    pv = out / f"{sid}-stencil-preview.jpg"
    preview.convert("RGB").save(pv, quality=82)
    print(f"wrote {pv}", file=sys.stderr)

    return {"id": sid, "src": src_for(out, png)}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Cut stencils from photographs for a treasure hunt.")
    ap.add_argument("photos", nargs="+", type=Path, help="the photographs")
    # 0.066 rather than the handoff's 0.06: a tenth more of the scene's edges,
    # after the first hunt showed the stencils needed more of their surroundings
    # to say where to stand.
    ap.add_argument("--keep", type=float, default=0.066,
                    help="fraction of the frame's interior to keep (default 0.066)")
    ap.add_argument("--speck", type=int, default=60,
                    help="drop blobs with fewer pixels than this (default 60)")
    ap.add_argument("--long", type=int, default=800,
                    help="resize so the long side is this many px (default 800)")
    ap.add_argument("--out", type=Path, required=True,
                    help="directory for the stencils, normally app/img/<slug>")
    args = ap.parse_args(argv)
    if not 0 < args.keep <= 1:
        ap.error("--keep must be above 0 and at most 1")
    if args.speck < 0:
        ap.error("--speck must not be negative")
    if args.long < 5:
        ap.error("--long must be at least 5, so the frame has an interior")
    for photo in args.photos:
        if not photo.is_file():
            ap.error(f"{photo}: no such file")
        print(json.dumps(make(photo, args.out, args.keep, args.speck, args.long)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
