#!/usr/bin/env python3
"""Cut a stencil from a photograph.

    python3 pipeline/stencil.py photos/<slug>/*.jpg --out app/img/<slug>
    python3 pipeline/stencil.py photos/<slug>/*.jpg \\
        --keep 0.12 --speck 60 --long 800 --out app/img/<slug>

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
find out: a stencil is good when a person could tell what it is.

A kept pixel is not merely on: its alpha is its own edge strength, so a
faint line counts a little where a strong one counts fully, and the scorer
takes the mean under the stencil weighted by that alpha. That is what pays
for keeping so much more of the frame than an on-or-off stencil could carry
without the weak edges drowning the strong ones. A stencil cut before this,
alpha 255 on every kept pixel, scores exactly as it always did: every weight
is then one and the weighted mean is the plain mean.

Left to itself the tool chooses --speck per photograph: the limit rises
until most of what survives is strokes rather than specks. It says what it
chose, and it says when a photograph is sparse or dim. Give --speck to fix
it by hand; --keep is 0.12 unless given.

What it will not tell you any more is that a photograph is mostly texture.
Keeping 0.12 of the frame instead of 0.066 merges the specks into
components long enough to pass for strokes: over the twenty-five
photographs of the three hunts the climb now runs on two — foliage against
a dry-stone wall, and the contour lines of a map — and the note fires on
none, the wicker basket it was written for included, whose lines went from
half strokes to three quarters. Whether a stencil is worth walking to is
pipeline/audit.py's to say now, and it says it by scoring the stencil
against the photographs rather than by the shape of the lines.

For each photograph this writes <id>-stencil.png, <id>-stencil-hint.png (the
same with twice as much kept, for the hint button) and
<id>-stencil-preview.jpg into --out, and prints one JSON stencil entry to
stdout, for pasting into the hunt file. Everything that is not an entry goes to stderr, so the output can
be redirected and pasted whole.

The two PNGs are palette images with a tRNS chunk rather than RGBA: one
colour at sixteen alphas needs a byte a pixel, not four, and the hunt's main
screen loads every stencil of the hunt at once. Same pixels, two fifths off
the bytes.
"""

import argparse
import json
import math
import sys
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

BASE = Path(__file__).resolve().parent.parent
APP = BASE / "app"

ORANGE = (255, 61, 0)      # the colour of every kept pixel; its alpha is the edge strength

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

    The quantile is taken over, and only ever set within, the pixels two
    in from the edge, where the Sobel had a full neighbourhood to read."""
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


def components(mask, w, h):
    """The 8-connected components of the set pixels, each a list of pixel
    indices, largest first. A plain stack, not recursion: an outline is one
    component thousands of pixels long and would blow the stack. The mask
    is left as it was."""
    n = w * h
    seen = bytearray(n)
    out = []
    for start in range(n):
        if not mask[start] or seen[start]:
            continue
        comp = [start]
        seen[start] = 1
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
                    if mask[j] and not seen[j]:
                        seen[j] = 1
                        stack.append(j)
                        comp.append(j)
        out.append(comp)
    out.sort(key=len, reverse=True)
    return out


def from_components(comps, w, h):
    mask = [0] * (w * h)
    for comp in comps:
        for i in comp:
            mask[i] = 1
    return mask


def drop_specks(mask, w, h, speck):
    """Clear every 8-connected component of set pixels with fewer than
    `speck` pixels, in place."""
    kept = [c for c in components(mask, w, h) if len(c) >= speck]
    mask[:] = from_components(kept, w, h)


# Choosing the speck limit by looking, the way the handoff has the owner do
# it, but done by the tool: raise the limit until most of what survives is
# strokes rather than specks. The numbers came from the first hunt: a door
# or a piano is a few components thousands of pixels long, a wicker basket
# or a cluttered cellar is hundreds under a hundred and fifty. The keep
# fraction is not climbed to make up for a sparse result: more of a textured
# picture is more texture, merged into blobs big enough to pass for strokes,
# and a plain subject already has its strong edges at the default keep. A
# sparse result is reported instead, because the answer is another
# photograph.
#
# STROKE_PX and STROKE_SHARE were read off the first hunt when a stencil kept
# 0.066 of the frame. At 0.12 the same photographs' lines merge — the wicker
# basket's longest component goes from 2,942 pixels to 14,052 and its stroke
# share from 0.51 to 0.74, the cluttered cellar's from 1,321 to 4,652 and
# 0.49 to 0.80 — so the climb runs on two of the three hunts' twenty-five
# photographs and none of them is called textured. They are left where they
# are: moving them by eye would change what is cut for the hunts about to be
# recut, and the question they were guessing at is the one audit.py measures.
SPECKS = [60, 80, 100, 130, 160, 200, 250, 300]
STROKE_PX = 300          # a component at least this long is a stroke, not a speck
STROKE_SHARE = 0.6       # the share of kept pixels that should be in strokes
# Under this share of what the keep asked for, the scorer has little to hold:
# most of what the threshold picked was specks and was dropped. A share
# rather than a fraction, because the fraction scales with --keep and the
# number was read off the first hunt at 0.066, where it stood for losing
# about half of it. Left as a fraction it would have gone on meaning "half"
# at 0.066 and "under a third" at 0.12, and quietly stopped firing.
#
# It is not the instrument for a bad photograph in general, and is not meant
# to be. Park gate's shot-7 is a map: its lines are dense rather than sparse,
# it says nothing here, and what refuses it is pipeline/audit.py measuring
# what it scores. This note is for the frame with almost nothing in it.
SPARSE_SHARE = 0.53
DIM = 60                 # mean brightness, of 255, under which a room is dark
HINT_TIMES = 2           # the hint keeps this many times the stencil's share of the frame


def choose(mag, w, h, keep, speck):
    """The mask, the speck used, and any notes about the photograph. A speck
    given as None is chosen here; keep is as given."""
    interior = max(1, (w - 4) * (h - 4))
    specks = [speck] if speck is not None else SPECKS
    comps = components(threshold(mag, w, h, keep), w, h)
    notes = []
    result = None
    for sp in specks:
        kept = [c for c in comps if len(c) >= sp]
        total = sum(len(c) for c in kept)
        share = (sum(len(c) for c in kept if len(c) >= STROKE_PX) / total) if total else 0.0
        result = (sp, kept, total / interior, share)
        if share >= STROKE_SHARE:
            break
    sp, kept, frac, share = result
    if share < STROKE_SHARE and speck is None:
        notes.append(f"mostly texture even at speck {sp} ({share:.0%} of its lines are strokes); "
                     "consider another photograph")
    elif frac < SPARSE_SHARE * keep:
        notes.append(f"sparse: {frac:.1%} of the frame before thickening; "
                     "a subject with bigger, plainer edges would give the camera more to hold")
    return from_components(kept, w, h), sp, notes


# The alpha is a weight in a mean over thousands of pixels, so it needs
# nothing like 256 levels, and a byte that takes every value compresses far
# worse than one that takes sixteen: quantising costs the score nothing
# measurable and takes a stencil from about 93 KB to about 55 KB, which is
# the difference between a hunt that opens on one bar of signal and one that
# does not.
ALPHA_LEVELS = 16
# The share of each frame's edges a stencil keeps. 0.12 rather than the 0.066
# a binary stencil could afford: counting every kept pixel the same, more of
# the frame meant more faint edges at the weight of strong ones, and the mean
# under the mask fell as fast as the mask grew. Weighted, a faint pixel costs
# almost nothing.
#
# The number is pipeline/audit.py's, over the seventeen photographs of the two
# hunts whose photographs are in hand, cut four ways: at each keep flat and
# weighted. Attainable median, worst attainable, worst confusion:
#
#     Snowman House   0.066 flat  0.630  0.536  0.200
#                     0.066 wtd   0.649  0.557  0.216
#                     0.12  flat  0.683  0.592  0.186
#                     0.12  wtd   0.725  0.633  0.188
#     Park gate       0.066 flat  0.498  0.191  0.259
#                     0.066 wtd   0.515  0.192  0.258
#                     0.12  flat  0.532  0.210  0.175
#                     0.12  wtd   0.568  0.215  0.163
#
# The keep is the larger lever and the weighting is worth about half as much
# again on top of it. Both hunts were swept further, and past 0.12 the
# attainable score keeps climbing while the confusion climbs with it: at 0.2
# Snowman House confuses at 0.260 and Park gate at 0.312, over the lowest
# pass line, which is a stencil that passes in the wrong place. 0.12 is where
# attainable is highest with confusion still at its lowest.
#
# It is not free for every photograph. Of the seventeen, fifteen improve and
# two lose: Park gate's shot-1 (0.265 to 0.215) and shot-7 (0.316 to 0.279),
# which are the two with the most going on beside their lines and were the
# two worst before. Keeping more of a cluttered frame keeps more clutter.
# Neither is worth walking to at any keep, and the answer to those is
# another photograph, which is what audit.py's floor says.
KEEP = 0.12


def orange(mask, mag, w, h, weighted=True):
    """The mask as the stencil PNG: thickened by one pixel, every kept pixel
    exactly ORANGE at an alpha that is its own normalised edge strength, and
    everything else fully transparent. The scorer divides that alpha by 255
    and weighs the pixel by it, which is why the floor is 1 and not 0: a
    kept pixel whose strength rounds away would otherwise drop out of the
    mask it was chosen for.

    The thickening runs over the alpha rather than over a flat mask, so the
    pixel a line grows into takes the strongest strength beside it instead
    of a value of its own. Nothing is antialiased into existence either way:
    a maximum filter leaves zero wherever its whole neighbourhood is zero,
    so a pixel neither kept nor grown into stays fully transparent."""
    # putdata takes a sequence shorter than the frame without a word and
    # leaves the rest of it at zero, so a caller that pairs a mask with the
    # magnitudes of some other frame would get the bottom of its stencil
    # quietly blanked and a PNG that still keeps the format contract.
    if len(mask) != w * h or len(mag) != w * h:
        raise ValueError(f"orange() wants {w * h} mask and magnitude values for a "
                         f"{w}x{h} frame, not {len(mask)} and {len(mag)}")
    step = 255 / ALPHA_LEVELS
    lines = Image.new("L", (w, h))
    if weighted:
        lines.putdata([max(1, round(round(255 * min(1, m) / step) * step)) if k else 0
                       for k, m in zip(mask, mag)])
    else:
        lines.putdata([255 if k else 0 for k in mask])
    lines = lines.filter(ImageFilter.MaxFilter(3))
    return Image.merge("RGBA", (
        lines.point(lambda a: ORANGE[0] if a else 0),
        lines.point(lambda a: ORANGE[1] if a else 0),
        lines.point(lambda a: ORANGE[2] if a else 0),
        lines,
    ))


def save_png(img, path):
    """An RGBA image written as small as it will go without moving a pixel.

    A stencil is one colour at a handful of alphas — sixteen levels and
    nothing in between — so it goes out as a palette image with a tRNS
    chunk: one byte a pixel instead of four, and the filters have far less
    to chew on. That is about two fifths off a stencil, which matters
    because the hunt's main screen loads every one of them at once and a
    ten-stencil hunt on one bar of signal is a wait a player can feel.

    tRNS carries each palette entry's alpha exactly, so the alpha the scorer
    reads back is the alpha the tool wrote — this is a smaller file and not a
    smaller stencil. Anything a palette cannot hold — more than 256 colours,
    or a mode whose colours are not RGBA tuples — is written as it came,
    which no stencil this tool cuts needs but the next caller might.
    """
    counts = img.getcolors(256) if img.mode == "RGBA" else None
    if counts is None:
        img.save(path, optimize=True)
        return
    # Transparent first, so index 0 is what a reader that ignores tRNS shows.
    colours = sorted((c for _, c in counts), key=lambda c: (c[3], c[:3]))
    index = {bytes(c): i for i, c in enumerate(colours)}
    raw = img.tobytes()
    pal = Image.frombytes("P", img.size,
                          bytes(index[raw[i:i + 4]] for i in range(0, len(raw), 4)))
    # The palette is handed over at exactly the length it needs. Padding it
    # to 256 entries, which is the obvious thing to write, costs far more
    # than the padding: Pillow takes the bit depth from the palette's length
    # rather than from the pixels, so a two-colour hint padded to 256 goes
    # out at eight bits a pixel with a 768-byte PLTE instead of one bit and
    # six. Over the three hunts cut here that padding was a tenth of the
    # stencils and a sixth of the hints, for nothing.
    pal.putpalette([v for c in colours for v in c[:3]])
    pal.save(path, optimize=True, transparency=bytes(c[3] for c in colours))


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

    px = pixels(im)
    mag = edge_map(px, w, h)
    mask, speck, notes = choose(mag, w, h, keep, speck)
    # The hint: the same picture with twice as much of it kept, at the same
    # speck limit, for the hint button to lay under the real stencil. It is
    # drawn flat rather than weighted — see where it is written below — since
    # the scorer never reads it and a flat alpha compresses far better.
    hint = threshold(mag, w, h, min(1.0, keep * HINT_TIMES))
    drop_specks(hint, w, h, speck)
    if not any(mask):
        print(f"{photo}: no edges found, the stencil is empty", file=sys.stderr)
    # A dark room is noise to the camera whatever the stencil says.
    mean = sum(0.299 * r + 0.587 * g + 0.114 * b for r, g, b in px) / len(px)
    if mean < DIM:
        notes.append(f"dim (mean brightness {mean:.0f} of 255); the camera will see noise in a dark room")

    stencil = orange(mask, mag, w, h)
    lines = stencil.split()[3]

    sid = stencil_id(photo)
    out = Path(out)
    out.mkdir(parents=True, exist_ok=True)
    png = out / f"{sid}-stencil.png"
    save_png(stencil, png)
    hint_png = out / f"{sid}-stencil-hint.png"
    # The hint is for the player's eye and the scorer never reads it, so it
    # carries no weights: a flat alpha compresses to a fifth of a weighted
    # one, and doubling what is kept has already doubled the ink.
    save_png(orange(hint, mag, w, h, weighted=False), hint_png)
    # The set fraction after thickening, at a glance: a stencil that is
    # mostly texture is a big number before it is a bad picture. Every pixel
    # with any alpha at all counts here, faint ones included, because every
    # one of them is in the mask the scorer reads.
    filled = (w * h - lines.histogram()[0]) / (w * h)
    print(f"wrote {png} {w}x{h}, {filled:.1%} set (keep {keep:g}, speck {speck})", file=sys.stderr)
    for note in notes:
        print(f"note: {photo}: {note}", file=sys.stderr)

    preview = im.convert("RGBA")
    preview.alpha_composite(stencil)
    pv = out / f"{sid}-stencil-preview.jpg"
    preview.convert("RGB").save(pv, quality=82)
    print(f"wrote {pv}", file=sys.stderr)

    return {"id": sid, "src": src_for(out, png), "hint": src_for(out, hint_png)}


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Cut stencils from photographs for a treasure hunt.")
    ap.add_argument("photos", nargs="+", type=Path, help="the photographs")
    # 0.12, where an on-or-off stencil could only afford 0.066. Counting
    # every kept pixel the same, keeping more of the frame meant keeping more
    # of the faint edges at the same weight as the strong ones, and the mean
    # under the mask fell as fast as the mask grew. Weighted, a faint pixel
    # costs little and still says where to stand: over the nine Snowman House
    # photographs the median attainable score went from 0.522 to 0.649 and the
    # worst from 0.293 to 0.374, while the worst score in the wrong place moved
    # only from 0.271 to 0.286. The speck limit, left out, is chosen per
    # photograph (see choose): from 60 up until the lines are strokes.
    ap.add_argument("--keep", type=float, default=KEEP,
                    help="fraction of the frame's interior to keep (default 0.12)")
    ap.add_argument("--speck", type=int, default=None,
                    help="drop blobs with fewer pixels than this (chosen per photo, from 60 up, if left out)")
    ap.add_argument("--long", type=int, default=800,
                    help="resize so the long side is this many px (default 800)")
    ap.add_argument("--out", type=Path, required=True,
                    help="directory for the stencils, normally app/img/<slug>")
    args = ap.parse_args(argv)
    if not 0 < args.keep <= 1:
        ap.error("--keep must be above 0 and at most 1")
    if args.speck is not None and args.speck < 0:
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
