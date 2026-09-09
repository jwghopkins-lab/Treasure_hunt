#!/usr/bin/env python3
"""pipeline/stencil.py, run as the owner runs it.

    python3 -m unittest discover -s tests -p 'test_*.py'

The fixture door is the checked-in sample: its stencil must be the size of
the resized photograph, drawn in one colour over a transparent ground, and
neither empty nor noise. That colour and the alpha beside it are the format
contract the scorer reads, and the alpha is a weight rather than a flag, so
both halves of it are pinned here: on the written PNG, where the colour
channels must be exactly (255, 61, 0) wherever the alpha is above zero, and
on orange() called on its own, where a kept pixel must never come out at
alpha 0 and a pixel that was neither kept nor thickened into must stay
fully transparent. The set fraction the tool prints is pinned to that same
mask, because it is the number the operator judges a photograph by. A blank
image must come out empty with a message rather than a crash, a portrait
photograph must stay portrait through its EXIF orientation, and a filename
must become a slug-safe id.
"""

import json
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw, ImageOps

BASE = Path(__file__).resolve().parent.parent
STENCIL = BASE / "pipeline" / "stencil.py"
DOOR = BASE / "photos" / "fixture" / "door.jpg"

# Everything else here runs the tool as a subprocess; the weighting rules are
# too small and too exact to read off a photograph, so orange() is called
# directly for those.
sys.path.insert(0, str(BASE / "pipeline"))
import stencil    # noqa: E402

ORANGE = (255, 61, 0)      # the colour of every kept pixel, at whatever alpha
CLEAR = (0, 0, 0, 0)


def run(*args):
    """stencil.py as a subprocess, the way it is used, so the command line
    and the exit code are tested along with the arithmetic."""
    return subprocess.run([sys.executable, str(STENCIL), *map(str, args)],
                          capture_output=True, text=True, cwd=BASE)


def entries(proc):
    """The JSON entries on stdout, one per line, and nothing else there."""
    return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]


def colours(png):
    """A written stencil as the browser decodes it. The tool writes a palette
    PNG with a tRNS chunk, which is a smaller file of the same pixels: every
    reader that matters, the canvas the scorer draws it on included, hands
    back RGBA with the alpha the tool wrote. So the contract below is checked
    on the decoded pixels rather than on the mode the bytes happen to be in."""
    im = Image.open(png).convert("RGBA")
    return im, {c for _, c in im.getcolors(im.width * im.height)}


def weights(seen):
    """The alphas a stencil is drawn at, the transparent ground left out."""
    return {c[3] for c in seen if c[3]}


def ink(im):
    """How much of the stencil the scorer will read: every pixel with an
    alpha at all, the faintest counted with the strongest, because the mask
    is every pixel above alpha 0 and the alpha only says how much it weighs.
    Bin 768 of an RGBA histogram is the alpha channel's zero."""
    return im.width * im.height - im.histogram()[768]


def contract(case, png):
    """The format contract, on a written PNG as it decodes: the colour
    channels exactly ORANGE wherever the alpha is above zero, and nothing but
    a fully transparent (0, 0, 0, 0) where they are not. The scorer takes the mask
    from the alpha and the weight from its value, so a second colour or a
    coloured pixel at alpha 0 is a stencil that scores as something else."""
    im, seen = colours(png)
    case.assertLessEqual({c[:3] for c in seen if c[3]}, {ORANGE}, seen)
    case.assertLessEqual({c for c in seen if not c[3]}, {CLEAR}, seen)
    return im, seen


class DoorTest(unittest.TestCase):
    """The recipe's defaults on the fixture door, run once for the class."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "out"
        cls.proc = run(DOOR, "--out", cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_exits_cleanly_with_one_entry(self):
        self.assertEqual(self.proc.returncode, 0, self.proc.stderr)
        self.assertEqual(entries(self.proc), [
            {"id": "door", "src": str(self.out / "door-stencil.png"),
             "hint": str(self.out / "door-stencil-hint.png")}])

    def test_the_shipped_recipe_is_what_runs_with_no_flags(self):
        # 0.12 is the keep a weighted stencil is cut at; the door is plain
        # enough that the speck limit stays where it starts.
        self.assertIn("(keep 0.12, speck 60)", self.proc.stderr)

    def test_png_is_the_photo_size_in_one_colour_over_transparency(self):
        with Image.open(DOOR) as photo:
            w, h = ImageOps.exif_transpose(photo).size
        k = 800 / max(w, h)
        im, seen = contract(self, self.out / "door-stencil.png")
        self.assertEqual(im.size, (round(w * k), round(h * k)))
        self.assertEqual(im.size, (600, 800))
        self.assertEqual({c[:3] for c in seen if c[3]}, {ORANGE}, seen)

    def test_the_alpha_is_a_weight_and_not_a_flag(self):
        im, seen = colours(self.out / "door-stencil.png")
        # A binary stencil has one alpha and a weighted one has a spread of
        # them, up the ladder the tool quantises to: fewer means the
        # strengths were rounded away, more means they are not quantised at
        # all and the PNG is half as big again for nothing. The floor of 1,
        # for a strength that would round to nothing, is off the ladder.
        self.assertGreater(len(weights(seen)), stencil.ALPHA_LEVELS // 2, sorted(weights(seen)))
        self.assertLessEqual(len(weights(seen)), stencil.ALPHA_LEVELS + 1, sorted(weights(seen)))
        # And the faint edges the keep fraction buys are really there, drawn
        # faint, rather than kept at the strength of a strong line.
        self.assertLess(min(weights(seen)), 64, sorted(weights(seen)))

    def test_set_fraction_is_lines_not_noise_and_not_nothing(self):
        im = Image.open(self.out / "door-stencil.png").convert("RGBA")
        frac = ink(im) / (im.width * im.height)
        self.assertGreaterEqual(frac, 0.04, frac)
        self.assertLessEqual(frac, 0.25, frac)

    def test_the_set_fraction_on_stderr_is_the_mask_the_scorer_reads(self):
        # The number the operator judges a stencil by, and the one output
        # whose meaning changed with the weights: it counts every pixel with
        # an alpha at all, because that is the mask. Counted over the
        # full-strength pixels alone it is a fraction of this, and a good
        # stencil reported that way looks starved.
        im = Image.open(self.out / "door-stencil.png").convert("RGBA")
        self.assertIn(f"{ink(im) / (im.width * im.height):.1%} set", self.proc.stderr)

    def test_preview_is_written_beside_it(self):
        with Image.open(self.out / "door-stencil-preview.jpg") as pv:
            self.assertEqual(pv.size, (600, 800))


class OrangeTest(unittest.TestCase):
    """The alpha rules, on made-up masks where every value is known: the
    scorer divides these numbers by 255 and multiplies the frame by them.
    The strengths land on a ladder of ALPHA_LEVELS steps, which is why a
    fifth of full weight is written as 48 rather than 51."""

    def alphas(self, w, h, kept):
        """orange()'s alpha channel for {(x, y): normalised magnitude}."""
        mask = [0] * (w * h)
        mag = [0.0] * (w * h)
        for (x, y), m in kept.items():
            mask[y * w + x] = 1
            mag[y * w + x] = m
        im = stencil.orange(mask, mag, w, h)
        self.assertLessEqual({c[:3] for _, c in im.getcolors(w * h) if c[3]}, {ORANGE})
        return stencil.pixels(im.split()[3])

    def test_alpha_is_the_edge_strength_and_never_zero_where_kept(self):
        a = self.alphas(9, 9, {(2, 2): 0.5, (6, 6): 0.0004})
        self.assertEqual(a[2 * 9 + 2], 128)
        # 255 x 0.0004 rounds to nothing, and a kept pixel at alpha 0 would
        # fall out of the mask it was chosen for, so the floor is 1.
        self.assertEqual(a[6 * 9 + 6], 1)

    def test_a_strength_above_one_is_clipped_to_full_weight(self):
        a = self.alphas(9, 9, {(4, 4): 1.0, (2, 7): 1.4})
        self.assertEqual(a[4 * 9 + 4], 255)
        self.assertEqual(a[7 * 9 + 2], 255)

    def test_the_thickening_takes_the_strongest_alpha_beside_it(self):
        a = self.alphas(11, 11, {(4, 4): 1.0, (5, 4): 0.2})
        self.assertEqual(a[4 * 11 + 5], 255)      # both, so the stronger
        self.assertEqual(a[4 * 11 + 6], 48)       # the faint one only
        self.assertEqual(a[3 * 11 + 3], 255)      # thickened from the strong

    def test_nothing_is_antialiased_into_existence(self):
        a = self.alphas(11, 11, {(4, 4): 1.0})
        for x, y in ((4, 2), (2, 4), (6, 6), (0, 0)):
            self.assertEqual(a[y * 11 + x], 0, (x, y))

    def test_a_mask_and_magnitudes_of_different_lengths_are_refused(self):
        # Pillow fills a frame from a short sequence without complaining and
        # leaves the rest at zero, so the mistake a caller with two arrays
        # can make would otherwise be a stencil missing its bottom half and
        # no word about it.
        with self.assertRaises(ValueError):
            stencil.orange([1] * 81, [1.0] * 80, 9, 9)
        with self.assertRaises(ValueError):
            stencil.orange([1] * 80, [1.0] * 81, 9, 9)


class WeightTest(unittest.TestCase):

    def test_a_strong_edge_outweighs_a_faint_one(self):
        # Two rectangles of the same size, one against its background and
        # one barely off it. Written as a PNG: JPEG would smear the faint
        # one away before the tool ever saw it.
        with tempfile.TemporaryDirectory() as tmp:
            photo = Path(tmp) / "both.png"
            im = Image.new("RGB", (300, 400), (170, 170, 170))
            d = ImageDraw.Draw(im)
            d.rectangle([20, 40, 130, 360], outline=(10, 10, 10), width=6)
            d.rectangle([170, 40, 280, 360], outline=(150, 150, 150), width=6)
            im.save(photo)
            proc = run(photo, "--long", "400", "--out", Path(tmp) / "out")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            with Image.open(Path(tmp) / "out" / "both-stencil.png") as opened:
                st = opened.convert("RGBA")
                w = st.width
                a = stencil.pixels(st.split()[3])
            strong = [v for i, v in enumerate(a) if v and i % w < w // 2]
            faint = [v for i, v in enumerate(a) if v and i % w >= w // 2]
            self.assertTrue(strong and faint, (len(strong), len(faint)))
            self.assertGreater(sum(strong) / len(strong),
                               2 * sum(faint) / len(faint))
            self.assertGreater(max(strong), 200)


class SavePngTest(unittest.TestCase):
    """save_png is a smaller file and not a smaller stencil. The scorer reads
    the alpha of every pixel and weighs it, so a writer that moved one alpha
    by a level would quietly change what the game scores; and the reason for
    it — a palette instead of four bytes a pixel — is worth nothing if the
    file does not actually come out smaller."""

    def written(self, img, **kw):
        with tempfile.TemporaryDirectory() as tmp:
            pal, rgba = Path(tmp) / "p.png", Path(tmp) / "r.png"
            stencil.save_png(img, pal)
            img.save(rgba, optimize=True, **kw)
            with Image.open(pal) as got:
                mode = got.mode
                same = got.convert("RGBA").tobytes() == img.tobytes()
            return mode, same, pal.stat().st_size, rgba.stat().st_size

    def a_stencil(self):
        """A stencil as the tool writes one: one colour, sixteen alphas, most
        of the frame empty."""
        w, h = 240, 320
        mask, mag = [], []
        for y in range(h):
            for x in range(w):
                on = abs(x - y) < 2 or x in (30, 150) or y in (40, 200)
                mask.append(1 if on else 0)
                mag.append(((x + y) % 17) / 16)
        return stencil.orange(mask, mag, w, h)

    def test_the_alpha_survives_the_palette(self):
        mode, same, small, plain = self.written(self.a_stencil())
        self.assertEqual(mode, "P")
        self.assertTrue(same, "the palette write moved a pixel")
        self.assertLess(small, plain, "the palette write is not smaller")

    def test_a_flat_stencil_survives_it_too(self):
        w, h = 64, 64
        flat = stencil.orange([1] * (w * h), [1.0] * (w * h), w, h, weighted=False)
        mode, same, _, _ = self.written(flat)
        self.assertEqual(mode, "P")
        self.assertTrue(same)

    def test_too_many_colours_is_written_as_it_came(self):
        """Nothing this tool cuts has more than seventeen colours, but a
        caller that hands over a photograph should get a correct PNG rather
        than a palette that cannot hold it."""
        im = Image.new("RGBA", (40, 40))
        im.putdata([(x * 6 % 256, y * 6 % 256, (x * y) % 256, 255)
                    for y in range(40) for x in range(40)])
        self.assertIsNone(im.getcolors(256), "the fixture is not over the palette limit")
        mode, same, _, _ = self.written(im)
        self.assertEqual(mode, "RGBA")
        self.assertTrue(same)


class BlankTest(unittest.TestCase):

    def test_uniform_image_gives_empty_stencil_and_a_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            blank = Path(tmp) / "wall.png"
            Image.new("RGB", (300, 400), (128, 128, 128)).save(blank)
            proc = run(blank, "--out", Path(tmp) / "out")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn(f"{blank}: no edges found, the stencil is empty", proc.stderr)
            im, seen = contract(self, Path(tmp) / "out" / "wall-stencil.png")
            self.assertEqual(im.size, (600, 800))
            self.assertEqual(seen, {CLEAR})
            self.assertEqual(entries(proc), [
                {"id": "wall", "src": str(Path(tmp) / "out" / "wall-stencil.png"),
                 "hint": str(Path(tmp) / "out" / "wall-stencil-hint.png")}])


def scene(size):
    """A small picture with something in it, so a stencil is not empty."""
    im = Image.new("RGB", size, (200, 190, 170))
    d = ImageDraw.Draw(im)
    w, h = size
    d.rectangle((w // 4, h // 4, 3 * w // 4, 3 * h // 4), outline=(30, 30, 30), width=3)
    d.ellipse((w // 3, h // 3, 2 * w // 3, 2 * h // 3), outline=(30, 30, 30), width=3)
    return im


class OrientationTest(unittest.TestCase):

    def test_portrait_photo_stays_portrait(self):
        # A phone stores the sensor's landscape frame and an EXIF tag saying
        # the phone was upright: orientation 6 is a quarter turn.
        with tempfile.TemporaryDirectory() as tmp:
            photo = Path(tmp) / "held-upright.jpg"
            exif = Image.Exif()
            exif[0x0112] = 6
            scene((400, 300)).save(photo, "JPEG", exif=exif.tobytes())
            proc = run(photo, "--long", "400", "--out", Path(tmp) / "out")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            with Image.open(Path(tmp) / "out" / "held-upright-stencil.png") as im:
                self.assertEqual(im.size, (300, 400))
            with Image.open(Path(tmp) / "out" / "held-upright-stencil-preview.jpg") as pv:
                self.assertEqual(pv.size, (300, 400))


class IdTest(unittest.TestCase):

    def test_id_is_lower_cased_with_hyphens(self):
        with tempfile.TemporaryDirectory() as tmp:
            photo = Path(tmp) / "Red Door.jpg"
            scene((300, 400)).save(photo, "JPEG")
            proc = run(photo, "--long", "400", "--out", Path(tmp) / "out")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertEqual(entries(proc)[0]["id"], "red-door")
            self.assertTrue((Path(tmp) / "out" / "red-door-stencil.png").is_file())
            self.assertTrue((Path(tmp) / "out" / "red-door-stencil-preview.jpg").is_file())

    def test_src_is_relative_to_app_when_written_under_it(self):
        # The one case that matters for the hunt file: written into
        # app/img/<slug>, the entry says img/<slug>/<id>-stencil.png.
        out = Path(tempfile.mkdtemp(prefix="tmp-test-", dir=BASE / "app" / "img"))
        try:
            with tempfile.TemporaryDirectory() as tmp:
                photo = Path(tmp) / "Red Door.jpg"
                scene((300, 400)).save(photo, "JPEG")
                proc = run(photo, "--long", "400", "--out", out)
                self.assertEqual(proc.returncode, 0, proc.stderr)
                self.assertEqual(entries(proc), [
                    {"id": "red-door", "src": f"img/{out.name}/red-door-stencil.png",
                     "hint": f"img/{out.name}/red-door-stencil-hint.png"}])
        finally:
            shutil.rmtree(out)


class ChoiceTest(unittest.TestCase):
    """The speck limit chosen per photograph when --speck is left out."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.out = Path(self.tmp.name) / "out"
        self.photos = Path(self.tmp.name) / "photos"
        self.photos.mkdir()

    def tearDown(self):
        self.tmp.cleanup()

    def shapes(self):
        """A door-like drawing: a few long outlines on a plain ground."""
        im = Image.new("RGB", (300, 400), (200, 196, 188))
        d = ImageDraw.Draw(im)
        d.rectangle([60, 40, 240, 380], outline=(40, 30, 30), width=5)
        d.rectangle([90, 80, 210, 200], outline=(40, 30, 30), width=4)
        d.rectangle([90, 230, 210, 350], outline=(40, 30, 30), width=4)
        d.ellipse([215, 200, 235, 220], fill=(40, 30, 30))
        p = self.photos / "shapes.jpg"
        im.save(p, quality=92)
        return p

    def texture(self):
        """Wicker, more or less: a dense grid of small dark blobs and
        nothing else, which is specks all the way down."""
        import random
        rnd = random.Random(7)
        im = Image.new("RGB", (300, 400), (190, 160, 110))
        d = ImageDraw.Draw(im)
        for y in range(10, 390, 9):
            for x in range(10, 290, 9):
                if rnd.random() < 0.85:
                    d.ellipse([x, y, x + 4, y + 3], fill=(90, 60, 30))
        p = self.photos / "wicker.jpg"
        im.save(p, quality=92)
        return p

    def chosen(self, proc):
        m = [line for line in proc.stderr.splitlines() if line.startswith("wrote") and "speck" in line]
        self.assertEqual(len(m), 1, proc.stderr)
        return int(m[0].rsplit("speck ", 1)[1].rstrip(")"))

    def test_clean_outlines_keep_the_default_limit(self):
        proc = run(self.shapes(), "--out", self.out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.chosen(proc), 60)
        self.assertNotIn("note:", proc.stderr)

    def test_a_hint_stencil_is_written_with_more_of_the_picture(self):
        proc = run(self.shapes(), "--out", self.out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        entry = entries(proc)[0]
        self.assertEqual(entry["hint"], entry["src"].replace("-stencil.png", "-stencil-hint.png"))
        base, _ = contract(self, self.out / "shapes-stencil.png")
        hint, hint_seen = contract(self, self.out / "shapes-stencil-hint.png")
        self.assertEqual(hint.size, base.size)
        # Twice the keep, so more ink than the stencil, and flat: the hint is
        # for the player's eye and the scorer never opens it, so it carries
        # no weights and compresses like the binary stencils used to.
        self.assertGreater(ink(hint), ink(base))
        self.assertEqual(weights(hint_seen), {255}, sorted(weights(hint_seen)))

    def test_texture_raises_the_limit_and_is_reported(self):
        proc = run(self.texture(), "--out", self.out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertGreater(self.chosen(proc), 60)
        self.assertIn("note:", proc.stderr)
        self.assertTrue("texture" in proc.stderr or "sparse" in proc.stderr, proc.stderr)

    def test_an_explicit_speck_is_used_as_given(self):
        proc = run(self.texture(), "--speck", "75", "--out", self.out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertEqual(self.chosen(proc), 75)
        self.assertNotIn("mostly texture", proc.stderr)

    def test_a_dark_photograph_is_reported(self):
        im = Image.new("RGB", (300, 400), (20, 18, 16))
        ImageDraw.Draw(im).rectangle([60, 40, 240, 380], outline=(70, 60, 55), width=5)
        p = self.photos / "dark.jpg"
        im.save(p, quality=92)
        proc = run(p, "--out", self.out)
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertIn("dim", proc.stderr)


if __name__ == "__main__":
    unittest.main()
