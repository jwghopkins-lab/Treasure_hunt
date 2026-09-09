#!/usr/bin/env python3
"""Score a hunt's stencils against its photographs before anybody walks it.

    python3 pipeline/audit.py content/<slug>.json --photos photos/<slug>
    python3 pipeline/audit.py content/<slug>.json --photos photos/<slug> \\
        --json audit.json --floor 0.35

Until this the only check on a stencil was a person looking at the preview,
and a person cannot see the number the camera will read. On the first hunt
walked, two stencils would not pass where they were taken and one passed in
the wrong room. Measured afterwards, the two that failed are the two lowest
attainable scores of that house's nine photographs and the worst confusion
of the nine is one of them: the walk found nothing the arithmetic had not
already got.

So, per stencil, two numbers. The attainable score is what the stencil gets
against the very photograph it was cut from: the best the player can ever do
standing in the right place, since nobody holds a phone as steady as the
photograph does. The confusion is the best it reaches against any other
photograph of the hunt, which is what a player gets for standing somewhere
else entirely. Beside them are the on and off means at the winning
alignment, because off is the number that decides the outcome: it is the
edge activity beside the lines, and a stencil scores well only where its
lines are busier than their surroundings. A stencil cut from a photograph
with a lot going on around its subject scores badly however strong its own
edges are, which is why a poor score is answered with another photograph and
not with another --keep.

The scorer is app/lens.js's, in the working frame it runs in: the stencil
thickened at its own resolution and drawn to fill 240x320, the mask every
pixel the shape half covers, each weighted by the strength the tool wrote
there, the ring the same mask grown by six pixels and hollowed out, and the
best score over five scales and nine shifts. The edge map is stencil.py's,
imported rather than repeated, because the audit and the tool have to see
the same edges or the audit is measuring a different stencil. The mask is
built the way stencilMasks builds it for the same reason: the floor and the
confusion line below are the game's own numbers, and a number is only worth
comparing with them if it came off the same arithmetic.

It is a model of the phone and not the phone: the camera has the room's own
light, its own crop and a hand behind it, and a photograph holds still where
a hand does not. So a score here runs above what someone standing in the
room will hold, and the floor is a line across these numbers rather than a
prediction of the phone's.

Needs Pillow, like stencil.py, and is not part of the build.
"""

import argparse
import json
import math
import statistics
import sys
from array import array
from collections import namedtuple
from operator import mul
from pathlib import Path

from PIL import Image, ImageFilter, ImageOps

sys.path.insert(0, str(Path(__file__).resolve().parent))

import stencil    # noqa: E402  the edge map, so both see the same edges

BASE = Path(__file__).resolve().parent.parent
APP = BASE / "app"

W, H = 240, 320                                # the scorer's working frame
SHIFTS = (-5, 0, 5)                            # working-frame pixels
SCALES = (0.85, 0.925, 1, 1.075, 1.15)
RING = 6                                       # the ring is the mask grown by this much

FLOOR = 0.35        # under this a stencil is not worth walking to
# The lowest of the three pass lines: a stencil that reaches it against
# another photograph of the hunt can be passed standing in front of that one.
CONFUSION = 0.20

PHOTO_SUFFIXES = (".jpg", ".jpeg", ".png")

# A part of one alignment: the frame pixels it reads, the weight of each, and
# the weights' total, which is the divisor of the weighted mean.
Part = namedtuple("Part", "js ws total")
Alignment = namedtuple("Alignment", "mask ring")


class AuditError(Exception):
    """Something the person running this has to fix before there is anything
    to measure: a hunt file that names a stencil with no photograph, or a
    stencil PNG that is not there."""


def edge_frame(path):
    """One photograph as the camera screen sees a frame: upright, scaled into
    the working frame whole rather than cropped, and put through the same edge
    map the stencil was cut with."""
    with Image.open(path) as opened:
        im = ImageOps.exif_transpose(opened).convert("RGB")
    im = im.resize((W, H), Image.Resampling.LANCZOS)
    return stencil.edge_map(stencil.pixels(im), W, H)


def drawn(img, scale):
    """One image drawn into the working frame at one scale, centred, as the
    camera screen draws the stencil to fill the view."""
    tw, th = max(1, round(W * scale)), max(1, round(H * scale))
    small = img.resize((tw, th), Image.Resampling.LANCZOS)
    canvas = Image.new("L", (W, H), 0)
    canvas.paste(small, ((W - tw) // 2, (H - th) // 2))
    return canvas


def radius(native_w, scale):
    """The thickening the scorer applies at the stencil's own resolution:
    enough of it to come out two working pixels wide once the stencil has
    been drawn down, which is what nativeMask asks for."""
    per_native = W * scale / native_w         # working pixels per stencil pixel
    if not per_native > 0:
        return 1
    return min(64, max(1, math.ceil(2 / per_native)))


def native(alpha, r):
    """What nativeMask hands back: the shape the mask is cut from, and the
    strength each of its pixels carries. Both are grown at the stencil's own
    resolution and only then drawn small, because a line three pixels wide on
    a six-hundred-pixel stencil is barely one pixel wide in the working frame
    and thresholding after the shrink would leave nothing of it."""
    thick = alpha.filter(ImageFilter.MaxFilter(2 * r + 1))
    return thick.point(lambda v: 255 if v else 0), thick


def shifted(idx, wts, dx, dy):
    """One list of frame pixels moved by (dx, dy), the pixels that fall off an
    edge dropped along with their weights. The shift is applied to the mask
    rather than to the frame, as in lens.js, and the row check is on x alone
    because y out of range lands outside the frame's pixels anyway."""
    js, ws = array("i"), array("f")
    off = dy * W + dx
    for i, w in zip(idx, wts):
        x = i % W + dx
        if x < 0 or x >= W:
            continue
        j = i + off
        if 0 <= j < W * H:
            js.append(j)
            ws.append(w)
    return Part(js, ws, sum(ws))


def alignments(alpha):
    """Every alignment the search tries, the mask and its ring for each. Built
    once per stencil and scored against every photograph of the hunt, because
    moving tens of thousands of pixels about is most of the work and the
    stencil does not change between photographs.

    The mask is the shape, thresholded at half after the shrink exactly as
    stencilMasks thresholds it, and each of its pixels is weighted by the
    strength drawn alongside it over the shape drawn beneath it. Two images
    rather than one is what keeps the two questions apart: which pixels the
    mask covers, which is a matter of where the lines are, and how much each
    one counts, which is a matter of how strong its edge was. A stencil cut
    before the tool carried strength has alpha 255 everywhere it is set, so
    its shape and its strength are the same image, every weight is exactly
    one, and the weighted mean is the plain mean the game has always taken.
    The ring is unweighted: it asks what is going on beside the lines, and
    every pixel beside them counts."""
    out = []
    for sc in SCALES:
        shape_img, strength_img = native(alpha, radius(alpha.width, sc))
        a = stencil.pixels(drawn(shape_img, sc))
        wt = stencil.pixels(drawn(strength_img, sc))
        mask = [i for i, v in enumerate(a) if v >= 128]
        if not mask:
            continue
        # The shrink mixes coverage into whatever it is given, and into both
        # images alike: dividing the strength by the shape takes it back out
        # and leaves the strength the tool wrote, which is the weight.
        weights = [min(1.0, wt[i] / a[i]) for i in mask]
        lit = Image.new("L", (W, H))
        lit.putdata([255 if v >= 128 else 0 for v in a])
        grown = stencil.pixels(lit.filter(ImageFilter.MaxFilter(2 * RING + 1)))
        ring = [i for i, v in enumerate(grown) if v and a[i] < 128]
        ones = [1.0] * len(ring)
        for dy in SHIFTS:
            for dx in SHIFTS:
                out.append(Alignment(shifted(mask, weights, dx, dy),
                                     shifted(ring, ones, dx, dy)))
    return out


def mean(E, part):
    """The mean of the edge map over one part, weighted. The gather and the
    multiply are left to map(), which matters: this runs ninety times per
    stencil and photograph."""
    if not part.total:
        return 0.0
    return sum(map(mul, part.ws, map(E.__getitem__, part.js))) / part.total


def score(E, aligns):
    """The best score this stencil can find in this frame, with the on and off
    means that produced it. The score is clamped at zero, as the camera
    screen clamps it, but the alignment is chosen before the clamp so that a
    frame with nothing in it still reports the means it was judged on."""
    best = None
    for a in aligns:
        on = mean(E, a.mask)
        off = mean(E, a.ring)
        v = (on - off) / (on + off + 0.001)
        if best is None or v > best[0]:
            best = (v, on, off)
    if best is None:
        return 0.0, 0.0, 0.0
    return max(0.0, best[0]), best[1], best[2]


def find_photos(stencils, photos):
    """The photograph each stencil was cut from, matched by id the way
    stencil.py made the id in the first place. A stencil with no photograph
    is the whole audit failing rather than a row quietly missing from the
    table: the hunt cannot be judged on the stencils that happen to be
    measurable."""
    if not photos.is_dir():
        raise AuditError(f"no photographs at {photos}")
    by_id = {}
    for path in sorted(photos.iterdir()):
        if path.suffix.lower() in PHOTO_SUFFIXES:
            by_id.setdefault(stencil.stencil_id(path), path)
    missing = [s["id"] for s in stencils if s["id"] not in by_id]
    if missing:
        raise AuditError(f"no photograph in {photos} for: " + ", ".join(missing))
    return {s["id"]: by_id[s["id"]] for s in stencils}


def load_alpha(src):
    """A stencil PNG's alpha channel. `src` is relative to app/, as the hunt
    file means it, unless it is a path that stands on its own, which is what
    a trial run outside the repository writes."""
    path = Path(src)
    if not path.is_absolute():
        path = APP / path
    if not path.is_file():
        raise AuditError(f"no stencil at {path}")
    with Image.open(path) as im:
        return im.convert("RGBA").split()[3]


def measure(hunt_path, photos):
    """Every stencil against every photograph. The edge maps are computed once
    and reused, the alignments once per stencil."""
    hunt = json.loads(Path(hunt_path).read_text(encoding="utf-8"))
    if not isinstance(hunt, dict):
        raise AuditError(f"{hunt_path} is not a hunt file")
    stencils = hunt.get("stencils") or []
    if not stencils:
        raise AuditError(f"{hunt_path} has no stencils")
    for s in stencils:
        if not s.get("id") or not s.get("src"):
            raise AuditError(f"{hunt_path} has a stencil with no id or no src: {s}")
    found = find_photos(stencils, photos)
    frames = {sid: edge_frame(path) for sid, path in found.items()}
    rows = []
    for s in stencils:
        sid = s["id"]
        aligns = alignments(load_alpha(s["src"]))
        against = {}
        for other in frames:
            v, on, off = score(frames[other], aligns)
            against[other] = round(v, 3)
            if other == sid:
                attainable, own_on, own_off = v, on, off
        elsewhere = {k: v for k, v in against.items() if k != sid}
        worst_at = max(elsewhere, key=elsewhere.get) if elsewhere else None
        confusion = elsewhere[worst_at] if worst_at else 0.0
        # Rounded once, and the margin taken from the rounded number, so that
        # the margin is the difference of the two columns printed beside it
        # however close the raw score sits to a rounding boundary.
        attainable = against[sid]
        rows.append({
            "id": sid,
            "photo": str(found[sid]),
            "attainable": attainable,
            "on": round(own_on, 3),
            "off": round(own_off, 3),
            "confusion": confusion,
            "confused_with": worst_at,
            "margin": round(attainable - confusion, 3),
            "against": against,
        })
    return hunt, rows


def table(rows, out):
    """The rows as a table, the id column as wide as the longest id, so the
    numbers line up whatever the stencils are called."""
    w = max([len("stencil")] + [len(r["id"]) for r in rows])
    a = max([len("against")] + [len(r["confused_with"] or "-") for r in rows])
    print(f"{'stencil':<{w}}  attainable      on     off  confusion  "
          f"{'against':<{a}}  margin", file=out)
    for r in rows:
        print(f"{r['id']:<{w}}  {r['attainable']:10.3f}  {r['on']:6.3f}  {r['off']:6.3f}  "
              f"{r['confusion']:9.3f}  {r['confused_with'] or '-':<{a}}  {r['margin']:6.3f}",
              file=out)


def summarise(rows, out):
    """The line to read if only one line is read: the median attainable score,
    the worst of them, and the worst confusion in the hunt."""
    attainable = [r["attainable"] for r in rows]
    worst = min(rows, key=lambda r: r["attainable"])
    confused = max(rows, key=lambda r: r["confusion"])
    line = (f"{len(rows)} stencils: attainable median {statistics.median(attainable):.3f}, "
            f"worst {worst['attainable']:.3f} ({worst['id']})")
    if confused["confused_with"]:
        line += (f"; confusion worst {confused['confusion']:.3f} "
                 f"({confused['id']} on {confused['confused_with']})")
    print(line, file=out)


def judge(rows, floor, out=sys.stderr):
    """Nought or one, and why. The verdict goes where the notes go, so that
    the table on stdout can be redirected and kept. A floor of 0 turns the
    judgement off and reports the hunt as it stands, which is what a hunt
    already in the field wants, or one cut being compared with the next: a
    number rather than an instruction to go back out."""
    if floor <= 0:
        print(f"{len(rows)} stencils measured, none judged (--floor 0)", file=out)
        return 0
    low = [r for r in rows if r["attainable"] < floor]
    confused = [r for r in rows if r["confusion"] >= CONFUSION]
    if low:
        print(f"audit: under the {floor:g} floor: "
              + ", ".join(f"{r['id']} ({r['attainable']:.3f})" for r in low)
              + " — photograph these again, with a subject that stands out"
                " from what is round it", file=out)
    if confused:
        print(f"audit: passes in the wrong place: "
              + ", ".join(f"{r['id']} ({r['confusion']:.3f} on {r['confused_with']})"
                          for r in confused),
              file=out)
    return 1 if low or confused else 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Score a hunt's stencils against its photographs.")
    ap.add_argument("hunt", type=Path, help="the hunt file, content/<slug>.json")
    ap.add_argument("--photos", type=Path, required=True,
                    help="the directory the photographs were cut from, photos/<slug>")
    ap.add_argument("--json", type=Path, default=None,
                    help="write the numbers here as well as printing them")
    ap.add_argument("--floor", type=float, default=FLOOR,
                    help=f"refuse an attainable score under this (default {FLOOR}); "
                         "0 measures without judging")
    args = ap.parse_args(argv)
    if args.floor < 0:
        ap.error("--floor must not be negative")
    try:
        hunt, rows = measure(args.hunt, args.photos)
    except AuditError as err:
        print(f"audit error — {err}", file=sys.stderr)
        return 2
    except FileNotFoundError as err:
        print(f"missing file — {err}", file=sys.stderr)
        return 2
    # Exit 1 is the verdict, "these stencils are not worth walking to", and a
    # hunt file that will not parse or a src pointing at the preview .jpg say
    # nothing of the sort. They go out the same door as a missing photograph.
    except json.JSONDecodeError as err:
        print(f"unreadable hunt file — {args.hunt}: {err}", file=sys.stderr)
        return 2
    except OSError as err:
        print(f"unreadable file — {err}", file=sys.stderr)
        return 2
    table(rows, sys.stdout)
    summarise(rows, sys.stdout)
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps(
            {"hunt": hunt.get("id"), "floor": args.floor, "stencils": rows},
            indent=1), encoding="utf-8")
        print(f"wrote {args.json}", file=sys.stderr)
    return judge(rows, args.floor)


if __name__ == "__main__":
    sys.exit(main())
