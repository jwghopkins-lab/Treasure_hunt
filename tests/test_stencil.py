#!/usr/bin/env python3
"""pipeline/stencil.py, run as the owner runs it.

    python3 -m unittest discover -s tests -p 'test_*.py'

The fixture door is the checked-in sample: its stencil must be the size of
the resized photograph, made of nothing but the two allowed pixel values,
and neither empty nor noise. A blank image must come out empty with a
message rather than a crash, a portrait photograph must stay portrait
through its EXIF orientation, and a filename must become a slug-safe id.
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

ORANGE = (255, 61, 0, 255)
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
    im = Image.open(png)
    return im, {c for _, c in im.getcolors(im.width * im.height)}


class DoorTest(unittest.TestCase):
    """The recipe's defaults on the fixture door, run once for the class."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.out = Path(cls.tmp.name) / "out"
        cls.proc = run(DOOR, "--keep", "0.06", "--speck", "60", "--long", "800",
                       "--out", cls.out)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def test_exits_cleanly_with_one_entry(self):
        self.assertEqual(self.proc.returncode, 0, self.proc.stderr)
        self.assertEqual(entries(self.proc), [
            {"id": "door", "src": str(self.out / "door-stencil.png")}])

    def test_png_is_the_photo_size_in_two_colours(self):
        with Image.open(DOOR) as photo:
            w, h = ImageOps.exif_transpose(photo).size
        k = 800 / max(w, h)
        im, seen = colours(self.out / "door-stencil.png")
        self.assertEqual(im.mode, "RGBA")
        self.assertEqual(im.size, (round(w * k), round(h * k)))
        self.assertEqual(im.size, (600, 800))
        self.assertTrue(seen <= {ORANGE, CLEAR}, seen)

    def test_set_fraction_is_lines_not_noise_and_not_nothing(self):
        im = Image.open(self.out / "door-stencil.png")
        alpha = im.histogram()[768:]
        frac = alpha[255] / (im.width * im.height)
        self.assertGreaterEqual(frac, 0.02, frac)
        self.assertLessEqual(frac, 0.12, frac)

    def test_preview_is_written_beside_it(self):
        with Image.open(self.out / "door-stencil-preview.jpg") as pv:
            self.assertEqual(pv.size, (600, 800))


class BlankTest(unittest.TestCase):

    def test_uniform_image_gives_empty_stencil_and_a_message(self):
        with tempfile.TemporaryDirectory() as tmp:
            blank = Path(tmp) / "wall.png"
            Image.new("RGB", (300, 400), (128, 128, 128)).save(blank)
            proc = run(blank, "--out", Path(tmp) / "out")
            self.assertEqual(proc.returncode, 0, proc.stderr)
            self.assertIn(f"{blank}: no edges found, the stencil is empty", proc.stderr)
            im, seen = colours(Path(tmp) / "out" / "wall-stencil.png")
            self.assertEqual(im.size, (600, 800))
            self.assertEqual(seen, {CLEAR})
            self.assertEqual(entries(proc), [
                {"id": "wall", "src": str(Path(tmp) / "out" / "wall-stencil.png")}])


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
                    {"id": "red-door", "src": f"img/{out.name}/red-door-stencil.png"}])
        finally:
            shutil.rmtree(out)


if __name__ == "__main__":
    unittest.main()


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
