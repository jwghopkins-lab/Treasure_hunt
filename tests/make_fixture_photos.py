#!/usr/bin/env python3
"""Draw the fixture hunt's six "photographs" and its hand-drawn map.

    python3 tests/make_fixture_photos.py
    python3 pipeline/stencil.py photos/fixture/*.jpg --out app/img/fixture

Needs Pillow, like pipeline/stencil.py. Not part of the build: the build only
needs the stencils cut from these, which are committed, and the photographs
themselves are committed too because the fixture hunt is the one whose
answers may be public. A real hunt's photographs are gitignored.

Each scene is a synthetic 600x800 portrait photograph: a soft gradient for
the sky or the wall, a blurred shadow or two, a touch of lens softness,
grain, and one bold subject drawn in dark outlines a few pixels wide on a
lighter ground. The outlines are what section 2's recipe keeps and the rest
is what it must throw away, so the scenes stay free of hard texture and
their shadows are soft: a shadow's edge, blurred over thirty pixels, has a
gradient far below the grain's and never becomes a line. The six subjects
are drawn at different places and sizes in the frame so that the six
stencils cannot be mistaken for one another.

The map is a plan of an imaginary hall for the image-map fixture, drawn to
look hand-made: wobbled ink lines on paper, an italic hand, six numbered
spots and a key.
"""

import math
import random
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw, ImageFilter, ImageFont

BASE = Path(__file__).resolve().parent.parent
PHOTOS = BASE / "photos" / "fixture"
MAP = BASE / "app" / "img" / "fixture-image" / "map.png"

W, H = 600, 800
INK = (36, 30, 28)          # the outline colour, near-black and a little warm
LW = 4                      # the outline width the recipe was tuned for

SERIF_ITALIC = "/usr/share/fonts/truetype/freefont/FreeSerifItalic.ttf"
SERIF_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSerif-Bold.ttf"
SANS_BOLD = "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf"


# --- the photographic ground -------------------------------------------------

def mix(a, b, t):
    return tuple(round(p + (q - p) * t) for p, q in zip(a, b))


def gradient(stops, size=(W, H)):
    """A vertical gradient through (y, colour) stops: the light on a wall,
    the sky paling to the horizon, a path darkening towards the camera. A
    wide, gentle change gives a gradient of a fraction of a level per pixel,
    far under anything the edge map keeps."""
    w, h = size
    im = Image.new("RGB", size)
    d = ImageDraw.Draw(im)
    for y in range(h):
        for (y0, c0), (y1, c1) in zip(stops, stops[1:]):
            if y0 <= y <= y1:
                t = (y - y0) / max(1, y1 - y0)
                d.line([(0, y), (w, y)], fill=mix(c0, c1, t))
                break
        else:
            d.line([(0, y), (w, y)], fill=stops[-1][1] if y > stops[-1][0] else stops[0][1])
    return im


def soft_shape(im, points, colour, blur, alpha=255):
    """A shape blurred into the picture: a cast shadow, a patch of light, a
    tree too far off to have leaves. Blurred enough that its edge is a
    slope, not a step."""
    layer = Image.new("L", im.size, 0)
    ImageDraw.Draw(layer).polygon(points, fill=alpha)
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    return Image.composite(Image.new("RGB", im.size, colour), im, layer)


def soft_ellipse(im, box, colour, blur, alpha=255):
    layer = Image.new("L", im.size, 0)
    ImageDraw.Draw(layer).ellipse(box, fill=alpha)
    layer = layer.filter(ImageFilter.GaussianBlur(blur))
    return Image.composite(Image.new("RGB", im.size, colour), im, layer)


def vignette(im, strength=0.28):
    """Corners a little darker, as a phone lens leaves them."""
    w, h = im.size
    small = Image.new("L", (30, 40))
    px = small.load()
    for y in range(40):
        for x in range(30):
            r = math.hypot((x + 0.5) / 30 - 0.5, (y + 0.5) / 40 - 0.5) / math.hypot(0.5, 0.5)
            px[x, y] = round(255 * strength * r * r)
    mask = small.resize((w, h), Image.Resampling.BICUBIC)
    return Image.composite(Image.new("RGB", im.size, (12, 10, 10)), im, mask)


def noise(size, sigma, seed):
    """Gaussian noise about 128, as an L image. Seeded, so the fixture is
    the same picture every time it is drawn."""
    rng = random.Random(seed)
    w, h = size
    g = rng.gauss
    return Image.frombytes("L", (w, h), bytes(
        min(255, max(0, round(128 + g(0, sigma)))) for _ in range(w * h)))


def grain(im, sigma, seed):
    """Photographic grain: noise on every channel alike, pixel by pixel."""
    n = noise(im.size, sigma, seed)
    return ImageChops.add(im, Image.merge("RGB", (n, n, n)), 1.0, -128)


def mottle(im, sigma, seed, cell=3):
    """Paper: the same noise drawn small and scaled up, so the fibres are a
    few pixels across. Grain the size of a pixel would look like a scan and
    cost a megabyte of PNG; this looks like paper and compresses."""
    w, h = im.size
    n = noise((w // cell + 1, h // cell + 1), sigma, seed)
    n = n.resize((w, h), Image.Resampling.BICUBIC)
    return ImageChops.add(im, Image.merge("RGB", (n, n, n)), 1.0, -128)


def finish(im, seed, sigma=4.5):
    """What every scene gets last: a little lens softness, the vignette, the
    grain. The softness comes before the grain, as it does in a camera."""
    im = im.filter(ImageFilter.GaussianBlur(0.6))
    im = vignette(im)
    return grain(im, sigma, seed)


# --- the six scenes ----------------------------------------------------------

def door():
    """A red panelled door in a pale frame with a fanlight over it, seen
    square on from the path. It fills the frame."""
    im = gradient([(0, (208, 194, 172)), (420, (198, 184, 162)), (799, (184, 168, 146))])
    # The pavement, its edge feathered so it is a change of tone and not a line.
    im = soft_shape(im, [(0, 738), (W, 738), (W, H), (0, H)], (168, 163, 156), 14)
    # The shadow the frame throws to the right, from a sun over the left shoulder.
    im = soft_shape(im, [(462, 112), (532, 150), (532, 730), (462, 712)], (40, 30, 26), 16, 110)
    d = ImageDraw.Draw(im)

    # The architrave, then the opening: a fanlight over a slab.
    d.rectangle((140, 108, 460, 714), fill=(196, 188, 170), outline=INK, width=5)
    cx, cy, r = 300, 270, 128
    d.pieslice((cx - r, cy - r, cx + r, cy + r), 180, 360, fill=(212, 222, 230), outline=INK, width=LW)
    d.rectangle((172, 270, 428, 714), fill=(218, 96, 80), outline=INK, width=LW)
    # The fanlight's bars: five spokes and an inner ring.
    for deg in (202, 236, 270, 304, 338):
        a = math.radians(deg)
        d.line([(cx, cy), (cx + r * math.cos(a), cy + r * math.sin(a))], fill=INK, width=LW)
    d.arc((cx - 58, cy - 58, cx + 58, cy + 58), 180, 360, fill=INK, width=LW)
    d.line([(172, 270), (428, 270)], fill=INK, width=6)
    # Six panels, two across and three down. One outline each: the ink on
    # the red is a weaker edge than the ink on the wall, and the recipe's 6%
    # goes to the strongest edges first, so the door is kept to the lines
    # that must survive rather than given a bevel that would push them out.
    for x0, x1 in ((200, 288), (312, 400)):
        for y0, y1 in ((300, 398), (424, 544), (570, 690)):
            d.rectangle((x0, y0, x1, y1), fill=(196, 76, 62), outline=INK, width=LW)
    # The knob on the right stile, and the step under the whole thing.
    d.ellipse((403, 474, 425, 496), fill=(232, 200, 118), outline=INK, width=3)
    d.rectangle((148, 714, 452, 734), fill=(190, 184, 176), outline=INK, width=3)
    return finish(im, 1)


def window():
    """An arched window with glazing bars, high and to the left in a plain
    stone wall, with a sill and a soft shadow under it."""
    im = gradient([(0, (192, 186, 176)), (400, (200, 194, 182)), (799, (178, 170, 158))])
    # A patch of sunlight low on the right; the window is in shade.
    im = soft_shape(im, [(380, 520), (W, 420), (W, H), (300, H)], (216, 208, 192), 40, 160)
    im = soft_shape(im, [(96, 646), (420, 646), (440, 700), (110, 700)], (60, 52, 46), 18, 120)
    d = ImageDraw.Draw(im)

    cx, top, r = 250, 300, 130
    x0, x1, bottom = cx - r, cx + r, 620
    # The stone surround, well proud of the opening, so its arch and the
    # opening's are two lines and not one thick one once the stencil is small.
    m = 26
    d.pieslice((x0 - m, top - r - m, x1 + m, top + r + m), 180, 360, fill=(212, 206, 194))
    d.rectangle((x0 - m, top, x1 + m, bottom), fill=(212, 206, 194))
    d.arc((x0 - m, top - r - m, x1 + m, top + r + m), 180, 360, fill=INK, width=5)
    d.line([(x0 - m, top), (x0 - m, bottom)], fill=INK, width=5)
    d.line([(x1 + m, top), (x1 + m, bottom)], fill=INK, width=5)
    # The glass, then the opening's own outline.
    d.pieslice((x0, top - r, x1, top + r), 180, 360, fill=(170, 192, 206))
    d.rectangle((x0, top, x1, bottom), fill=(170, 192, 206))
    d.arc((x0, top - r, x1, top + r), 180, 360, fill=INK, width=LW)
    d.line([(x0, top), (x0, bottom)], fill=INK, width=LW)
    d.line([(x1, top), (x1, bottom)], fill=INK, width=LW)
    # Glazing bars: three uprights, three rails, and a fan in the arch.
    for x in (cx - 43, cx, cx + 43):
        d.line([(x, top), (x, bottom)], fill=INK, width=LW)
    for y in (top, 380, 460, 540):
        d.line([(x0, y), (x1, y)], fill=INK, width=LW)
    for deg in (206, 238, 270, 302, 334):
        a = math.radians(deg)
        d.line([(cx, top), (cx + r * math.cos(a), top + r * math.sin(a))], fill=INK, width=LW)
    d.arc((cx - 62, top - 62, cx + 62, top + 62), 180, 360, fill=INK, width=LW)
    # The sill.
    d.rectangle((x0 - m - 8, bottom, x1 + m + 8, bottom + 26), fill=(196, 190, 178), outline=INK, width=LW)
    return finish(im, 2)


def lamp():
    """A lamp post against the sky, tall and to the right of the frame, its
    lantern near the top, with a far-off tree as a soft dark shape."""
    im = gradient([(0, (146, 176, 210)), (300, (186, 204, 224)), (540, (222, 224, 222)),
                   (640, (184, 178, 164)), (799, (156, 148, 134))])
    im = soft_ellipse(im, (-80, 300, 250, 640), (96, 112, 84), 26, 200)
    im = soft_ellipse(im, (300, 700, 520, 740), (60, 52, 46), 14, 110)
    d = ImageDraw.Draw(im)

    cx = 392
    # The post, its two collars, and the plinth it stands on.
    d.rectangle((cx - 8, 214, cx + 8, 660), fill=(48, 44, 44), outline=INK, width=2)
    d.rectangle((cx - 14, 330, cx + 14, 342), fill=INK)
    d.rectangle((cx - 14, 560, cx + 14, 572), fill=INK)
    d.rectangle((cx - 22, 640, cx + 22, 700), fill=(56, 52, 50), outline=INK, width=3)
    d.rectangle((cx - 34, 690, cx + 34, 714), fill=(66, 62, 58), outline=INK, width=3)
    # The lantern: a collar, a tapered glass box with a bar across, a roof, a finial.
    d.rectangle((cx - 12, 200, cx + 12, 216), fill=INK)
    d.polygon([(cx - 30, 204), (cx + 30, 204), (cx + 44, 130), (cx - 44, 130)],
              fill=(242, 228, 168), outline=INK, width=LW)
    d.line([(cx, 130), (cx, 204)], fill=INK, width=3)
    d.line([(cx - 37, 168), (cx + 37, 168)], fill=INK, width=3)
    d.polygon([(cx - 54, 130), (cx + 54, 130), (cx, 84)], fill=(50, 46, 44), outline=INK, width=LW)
    d.ellipse((cx - 8, 68, cx + 8, 84), fill=INK)
    return finish(im, 3)


def bench():
    """A slatted park bench with cast ends, across the lower half of the
    frame, a hedge behind it and a path in front."""
    im = gradient([(0, (84, 108, 70)), (300, (104, 126, 82)), (470, (120, 138, 92)),
                   (560, (178, 168, 150)), (799, (156, 146, 128))])
    im = soft_ellipse(im, (60, 40, 400, 420), (72, 96, 60), 30, 150)
    im = soft_shape(im, [(80, 660), (540, 660), (560, 720), (70, 720)], (60, 52, 46), 18, 120)
    d = ImageDraw.Draw(im)

    wood = (156, 112, 64)
    xl, xr = 112, 488
    # Three slats in the back and three in the seat, with daylight between.
    for y in (386, 420, 454):
        d.rectangle((xl, y, xr, y + 18), fill=wood, outline=INK, width=3)
    for y in (524, 556, 588):
        d.rectangle((xl, y, xr, y + 18), fill=wood, outline=INK, width=3)
    # The cast-iron ends: an upright, an arm, a leg, a foot, at each side.
    for x in (100, 500):
        d.rectangle((x - 7, 372, x + 7, 608), fill=(52, 48, 48), outline=INK, width=2)
        d.rectangle((x - 24, 484, x + 24, 498), fill=INK)
        d.rectangle((x - 7, 608, x + 7, 668), fill=(52, 48, 48), outline=INK, width=2)
        d.rectangle((x - 22, 664, x + 22, 676), fill=INK)
    return finish(im, 4)


def sign():
    """A signpost with two boards, one pointing each way, high against the
    sky and a little left of centre; a tree and a low sun off to the right."""
    im = gradient([(0, (168, 190, 218)), (360, (206, 214, 224)), (600, (230, 226, 212)),
                   (690, (176, 166, 144)), (799, (158, 148, 128))])
    im = soft_ellipse(im, (360, 380, 700, 700), (98, 110, 82), 28, 190)
    im = soft_ellipse(im, (200, 726, 340, 752), (60, 52, 46), 12, 120)
    d = ImageDraw.Draw(im)

    cx = 252
    d.rectangle((cx - 9, 118, cx + 9, 730), fill=(78, 62, 46), outline=INK, width=3)
    d.ellipse((cx - 15, 92, cx + 15, 122), fill=(206, 172, 82), outline=INK, width=3)
    board = (238, 228, 198)
    # The upper board points right, the lower one left, each with a chevron tip.
    d.polygon([(cx + 10, 186), (518, 186), (556, 220), (518, 254), (cx + 10, 254)],
              fill=board, outline=INK, width=LW)
    d.polygon([(cx - 10, 300), (58, 300), (20, 334), (58, 368), (cx - 10, 368)],
              fill=board, outline=INK, width=LW)
    font = ImageFont.truetype(SANS_BOLD, 40)
    d.text((cx + 34, 220), "FOUNTAIN", font=font, fill=INK, anchor="lm")
    d.text((cx - 34, 334), "LAKE", font=font, fill=INK, anchor="rm")
    return finish(im, 5)


def fountain():
    """A three-tiered fountain, centred and low, a hedge behind it and
    paving in front."""
    im = gradient([(0, (170, 192, 216)), (330, (216, 222, 220)), (420, (98, 118, 82)),
                   (520, (110, 130, 88)), (600, (176, 170, 158)), (799, (150, 144, 132))])
    im = soft_ellipse(im, (-40, 300, 300, 540), (80, 102, 66), 24, 160)
    im = soft_ellipse(im, (40, 776, 600, 800), (60, 52, 46), 14, 120)
    d = ImageDraw.Draw(im)

    stone, water = (202, 196, 184), (150, 190, 202)
    # The plinth, then each tier: a bowl, the water in it, the stem above.
    d.rectangle((30, 768, 570, 792), fill=(178, 172, 160), outline=INK, width=LW)
    d.chord((60, 620, 540, 780), 0, 180, fill=stone, outline=INK, width=5)
    d.ellipse((60, 664, 540, 736), fill=water, outline=INK, width=5)
    d.rectangle((284, 586, 316, 700), fill=stone, outline=INK, width=3)
    d.chord((150, 470, 450, 590), 0, 180, fill=stone, outline=INK, width=LW)
    d.ellipse((150, 502, 450, 558), fill=water, outline=INK, width=LW)
    d.rectangle((288, 438, 312, 530), fill=stone, outline=INK, width=3)
    d.chord((215, 340, 385, 440), 0, 180, fill=stone, outline=INK, width=LW)
    d.ellipse((215, 372, 385, 408), fill=water, outline=INK, width=LW)
    d.rectangle((292, 336, 308, 390), fill=stone, outline=INK, width=3)
    d.ellipse((280, 296, 320, 338), fill=stone, outline=INK, width=LW)
    d.line([(300, 270), (300, 296)], fill=INK, width=5)
    return finish(im, 6)


SCENES = [("door", door), ("window", window), ("lamp", lamp),
          ("bench", bench), ("sign", sign), ("fountain", fountain)]


# --- the hand-drawn map -------------------------------------------------------

MW, MH = 900, 1200
PAPER = (246, 240, 224)
PEN = (52, 42, 36)


def wobble(d, points, width, rng, colour=PEN, closed=False):
    """A pen line: each segment walked in ten-pixel steps, every step nudged
    a pixel or so sideways, the whole drawn twice slightly apart. A ruler
    would give a line the edge map likes; a hand gives this."""
    pts = list(points) + ([points[0]] if closed else [])
    for pass_ in range(2):
        path = []
        for (x0, y0), (x1, y1) in zip(pts, pts[1:]):
            n = max(1, int(math.hypot(x1 - x0, y1 - y0) / 10))
            for k in range(n + 1):
                t = k / n
                path.append((x0 + (x1 - x0) * t + rng.gauss(0, 1.1) + pass_ * 1.5,
                             y0 + (y1 - y0) * t + rng.gauss(0, 1.1) - pass_ * 1.0))
        d.line(path, fill=colour, width=width, joint="curve")


def wobble_circle(d, cx, cy, r, width, rng, colour=PEN):
    pts = [(cx + r * math.cos(a), cy + r * math.sin(a))
           for a in (math.radians(t) for t in range(0, 360, 12))]
    wobble(d, pts, width, rng, colour, closed=True)


def hall_map():
    rng = random.Random(11)
    im = Image.new("RGB", (MW, MH), PAPER)
    # A fold and a few fingerprints of light, so the paper is not flat.
    im = soft_shape(im, [(0, 0), (MW, 0), (MW, 90), (0, 130)], (232, 224, 204), 30, 150)
    im = soft_ellipse(im, (500, 900, 1000, 1300), (236, 228, 208), 40, 200)
    d = ImageDraw.Draw(im)
    title = ImageFont.truetype(SERIF_ITALIC, 72)
    hand = ImageFont.truetype(SERIF_ITALIC, 34)
    small = ImageFont.truetype(SERIF_ITALIC, 26)
    num = ImageFont.truetype(SERIF_BOLD, 30)

    d.text((70, 60), "The Hall", font=title, fill=PEN)
    wobble(d, [(70, 150), (390, 146)], 4, rng)
    wobble(d, [(74, 158), (300, 156)], 2, rng)

    # The walls: the hall's outline with a porch on the south side and a bow
    # on the east, a wall across the middle with a wide doorway in it, and
    # the courtyard walled off in the south-east corner.
    wobble(d, [(120, 220), (780, 220), (780, 380)], 7, rng)
    bow = [(780 + 90 * math.sin(math.radians(t)), 480 - 100 * math.cos(math.radians(t)))
           for t in range(0, 181, 12)]
    wobble(d, bow, 7, rng)
    wobble(d, [(780, 580), (780, 1080), (520, 1080)], 7, rng)
    wobble(d, [(380, 1080), (120, 1080), (120, 220)], 7, rng)
    wobble(d, [(380, 1080), (380, 1150), (520, 1150), (520, 1080)], 5, rng)
    wobble(d, [(120, 600), (300, 600)], 6, rng)
    wobble(d, [(430, 600), (780, 600)], 6, rng)
    wobble(d, [(560, 640), (560, 900), (780, 900)], 5, rng)
    wobble(d, [(560, 640), (620, 640)], 5, rng)
    wobble(d, [(700, 640), (780, 640)], 5, rng)
    # The stairs in the north-west corner: eight treads and a rail.
    for k in range(8):
        wobble(d, [(140, 250 + k * 22), (260, 250 + k * 22)], 3, rng)
    wobble(d, [(260, 240), (260, 430), (140, 430)], 4, rng)
    # Four columns down the gallery, drawn as little circles.
    for x in (330, 450, 570, 690):
        wobble_circle(d, x, 400, 13, 3, rng)
    # The door swings: the front door and the doorway in the middle wall.
    swing = [(380 + 140 * math.cos(math.radians(t)), 1080 - 140 * math.sin(math.radians(t)))
             for t in range(0, 91, 9)]
    wobble(d, swing, 3, rng)
    wobble(d, [(380, 1080), (380, 940)], 4, rng)
    # Windows: three short bars each, on the east bow and the north wall.
    for x in (500, 620):
        for k in range(3):
            wobble(d, [(x + k * 12, 214), (x + k * 12, 228)], 3, rng)
    for y in (440, 500):
        for k in range(3):
            wobble(d, [(868, y + k * 12), (880, y + k * 12)], 3, rng)
    # The fountain in the courtyard: two rings and a dot.
    wobble_circle(d, 668, 770, 54, 4, rng)
    wobble_circle(d, 668, 770, 30, 3, rng)
    d.ellipse((662, 764, 674, 776), fill=PEN)

    # The rooms, named in the same hand.
    for text, xy in (("Gallery", (400, 300)), ("Great Room", (250, 720)),
                     ("Courtyard", (600, 690)), ("Stairs", (150, 450)),
                     ("Porch", (400, 1105)), ("Bow", (800, 470))):
        d.text(xy, text, font=hand, fill=PEN)

    # The six spots, numbered in the hunt's order: the door, the window, the
    # lamp, the bench, the sign, the fountain.
    spots = [(450, 1030), (750, 470), (300, 320), (200, 860), (450, 500), (668, 850)]
    for n, (x, y) in enumerate(spots, 1):
        d.ellipse((x - 26, y - 26, x + 26, y + 26), fill=(252, 248, 236))
        wobble_circle(d, x, y, 26, 4, rng)
        d.text((x, y + 1), str(n), font=num, fill=PEN, anchor="mm")

    # North, top right, and a key at the foot.
    wobble(d, [(820, 160), (820, 70)], 4, rng)
    wobble(d, [(806, 90), (820, 66), (834, 90)], 4, rng)
    d.text((820, 176), "N", font=hand, fill=PEN, anchor="mt")
    key = ["1  Door", "2  Window", "3  Lamp", "4  Bench", "5  Sign", "6  Fountain"]
    for k, text in enumerate(key):
        d.text((570 + (k // 3) * 160, 1090 + (k % 3) * 34), text, font=small, fill=PEN)
    wobble(d, [(120, 1160), (320, 1160)], 3, rng)
    for x in (120, 220, 320):
        wobble(d, [(x, 1152), (x, 1168)], 3, rng)
    d.text((220, 1142), "10 m", font=small, fill=PEN, anchor="mb")

    im = im.filter(ImageFilter.GaussianBlur(0.5))
    # A palette PNG without dithering: ink on paper has few colours, and the
    # file is committed and shipped, so it is kept to about a hundred
    # kilobytes. Dithering would put the grain back and quadruple the size.
    return mottle(im, 3.0, 99, cell=20).quantize(32, dither=Image.Dither.NONE)


if __name__ == "__main__":
    PHOTOS.mkdir(parents=True, exist_ok=True)
    for name, draw in SCENES:
        out = PHOTOS / f"{name}.jpg"
        draw().save(out, quality=88)
        print(f"wrote {out}")
    MAP.parent.mkdir(parents=True, exist_ok=True)
    hall_map().save(MAP, optimize=True)
    print(f"wrote {MAP}")
