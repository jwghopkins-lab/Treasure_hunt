#!/usr/bin/env python3
"""pipeline/audit.py, run as the build runs it.

    python3 -m unittest discover -s tests -p 'test_*.py'

Four small pictures stand in for a hunt: a door on a plain ground, the same
door on a busy one, another bold subject, and a blank wall. They are cut with
stencil.py at --long 200, which keeps the edge map cheap, and written into a
hunt file with the paths the tool printed, so what is measured here is a real
stencil against the real photograph it came from.

What the audit is for is the two numbers, and the two numbers are what is
pinned: a bold subject must come out far above a blank wall, which has nothing
for the camera to hold and no stencil to speak of, and the door on the busy
ground must come out far below the same door on the plain one, on the same on
mean and a much higher off. Beside that, the refusal: it names every stencil
it measured, it stops rather than skipping when a photograph has gone, and
--floor 0 measures without judging, so that a hunt already in the field can
have a number read off it without being told to go back out.

Two of those are the alpha the stencil now carries, because no exit code
shows a weight. One stencil is measured twice, once as it was cut and once
with every kept pixel flattened to 255 over exactly the same pixels, and the
two have to disagree; and the flattened one, which is what every stencil cut
before the tool carried strength looks like, has to weigh exactly one
everywhere, because Park gate's ten cannot be recut and must go on scoring
as they always did. The other is the wrong place: a hunt with nothing under
the floor and a stencil that passes in another room is still refused, and
the refusal says which stencil and which photograph.
"""

import json
import random
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

from PIL import Image, ImageDraw

BASE = Path(__file__).resolve().parent.parent
AUDIT = BASE / "pipeline" / "audit.py"
STENCIL = BASE / "pipeline" / "stencil.py"

sys.path.insert(0, str(BASE / "pipeline"))

import audit    # noqa: E402  for the weights, which no exit code can show

SIZE = (300, 400)
PAPER = (205, 200, 190)
INK = (35, 30, 30)


def panels(d):
    """A door, more or less: a few long outlines and a handle."""
    d.rectangle([50, 40, 250, 370], outline=INK, width=7)
    d.rectangle([90, 90, 210, 200], outline=INK, width=6)
    d.ellipse([215, 195, 240, 220], fill=INK)


def door(im):
    """A bold shape on a plain ground: what the recipe asks for, and what the
    audit should approve of."""
    panels(ImageDraw.Draw(im))


def clutter(im):
    """The same door with a wall of pebbledash behind it, which is the case
    the audit exists to catch: the subject's own edges are as strong as the
    plain door's, and the edges beside them are what sinks it."""
    d = ImageDraw.Draw(im)
    rnd = random.Random(7)
    for y in range(6, 398, 11):
        for x in range(6, 296, 11):
            if rnd.random() < 0.8:
                d.ellipse([x, y, x + 5, y + 4], fill=(120, 95, 70))
    panels(d)


def arch(im):
    """Another bold subject, somewhere else in the frame, so that a stencil
    has somewhere other than its own photograph to be confused with."""
    d = ImageDraw.Draw(im)
    d.ellipse([40, 60, 260, 300], outline=INK, width=8)
    d.line([150, 300, 150, 390], fill=INK, width=8)


def wall(im):
    """Nothing at all: the plain ground on its own, which is the photograph
    the tool can find no edges in."""


PICTURES = {"door": door, "clutter": clutter, "arch": arch, "wall": wall}


def run(*args):
    """audit.py as a subprocess, the way the build runs it, so the exit code
    is tested with the arithmetic."""
    return subprocess.run([sys.executable, str(AUDIT), *map(str, args)],
                          capture_output=True, text=True, cwd=BASE)


class AuditTest(unittest.TestCase):
    """One hunt, cut once for the class: the pictures, their stencils, the
    hunt file, and the audit's own numbers read back from --json."""

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        tmp = Path(cls.tmp.name)
        cls.photos = tmp / "photos"
        cls.photos.mkdir()
        for name, draw in PICTURES.items():
            im = Image.new("RGB", SIZE, PAPER)
            draw(im)
            # PNG, not JPEG: the blank wall has to arrive blank, and JPEG
            # would leave a grid of its own edges all over it.
            im.save(cls.photos / f"{name}.png")
        cls.out = tmp / "stencils"
        cut = subprocess.run(
            [sys.executable, str(STENCIL), *[str(cls.photos / f"{n}.png") for n in PICTURES],
             "--long", "200", "--out", str(cls.out)],
            capture_output=True, text=True, cwd=BASE)
        assert cut.returncode == 0, cut.stderr
        cls.stencils = [json.loads(line) for line in cut.stdout.splitlines() if line.strip()]
        cls.hunt = tmp / "hunt.json"
        cls.hunt.write_text(json.dumps({
            "id": "audit-fixture", "name": "Audit Fixture", "test_mode": True,
            "stencils": cls.stencils,
        }), encoding="utf-8")
        cls.report = tmp / "audit.json"
        cls.proc = run(cls.hunt, "--photos", cls.photos, "--json", cls.report)
        cls.rows = {r["id"]: r for r in
                    json.loads(cls.report.read_text(encoding="utf-8"))["stencils"]}

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()

    def printed(self, name):
        """One row of the printed table: id, attainable, on, off, confusion,
        the photograph it was confused with, and the margin."""
        rows = [line.split() for line in self.proc.stdout.splitlines()
                if line.split() and line.split()[0] == name]
        self.assertEqual(len(rows), 1, self.proc.stdout)
        return rows[0]

    def test_a_bold_subject_beats_a_blank_wall(self):
        # The wall keeps nothing, so it has nothing to score with; the door
        # and the arch are what a stencil is supposed to look like.
        self.assertLess(self.rows["wall"]["attainable"], 0.1, self.proc.stdout)
        for name in ("door", "arch"):
            self.assertGreater(self.rows[name]["attainable"],
                               self.rows["wall"]["attainable"] + 0.4, self.proc.stdout)

    def test_busy_surroundings_sink_a_strong_subject(self):
        # The same door in both, so the edges under the stencil are as strong
        # in one as in the other; all that changed is what is beside them.
        plain, busy = self.rows["door"], self.rows["clutter"]
        self.assertAlmostEqual(plain["on"], busy["on"], delta=0.1, msg=(plain, busy))
        self.assertGreater(busy["off"], plain["off"] + 0.1, (plain, busy))
        self.assertLess(busy["attainable"], plain["attainable"] - 0.3, (plain, busy))

    def test_the_table_carries_the_numbers_it_measured(self):
        # Including on and off: off is what governs the outcome, so it is in
        # the table and not only in the arithmetic behind it.
        for name in PICTURES:
            row, printed = self.rows[name], self.printed(name)
            self.assertEqual([float(v) for v in printed[1:5]],
                             [row["attainable"], row["on"], row["off"], row["confusion"]])
            self.assertEqual(printed[5], row["confused_with"])
            self.assertEqual(float(printed[6]), row["margin"])
        for name in ("door", "clutter", "arch"):
            self.assertGreater(self.rows[name]["on"], self.rows[name]["off"], self.rows[name])

    def test_the_table_names_every_stencil(self):
        lines = self.proc.stdout.splitlines()
        self.assertTrue(lines[0].startswith("stencil"), self.proc.stdout)
        named = [line.split()[0] for line in lines[1:1 + len(PICTURES)]]
        self.assertEqual(named, list(PICTURES), self.proc.stdout)
        self.assertIn(f"{len(PICTURES)} stencils:", lines[-1])

    def test_confusion_names_another_photograph(self):
        for name in PICTURES:
            row = self.rows[name]
            self.assertIn(row["confused_with"], set(PICTURES) - {name}, row)
            self.assertEqual(row["margin"],
                             round(row["attainable"] - row["confusion"], 3), row)

    def flattened(self, name):
        """One stencil written out again with every kept pixel at full alpha
        and not one pixel more or fewer: a stencil as the tool cut them
        before it carried strength."""
        src = Path(next(s["src"] for s in self.stencils if s["id"] == name))
        with Image.open(src) as im:
            r, g, b, a = im.convert("RGBA").split()
        flat = Image.merge("RGBA", (r, g, b, a.point(lambda v: 255 if v else 0)))
        out = Path(self.tmp.name) / f"{name}-flat-stencil.png"
        flat.save(out)
        return out

    def test_an_old_stencil_weighs_one_everywhere(self):
        # The format contract's whole promise: an all-255 stencil comes out
        # of the mask at weight one, so the weighted mean is the plain mean
        # and Park gate's ten, whose photographs are gone, score exactly as
        # they did. The cut stencil is checked alongside it, because weights
        # that are all one whatever the alpha would satisfy the promise by
        # ignoring the alpha altogether.
        src = next(s["src"] for s in self.stencils if s["id"] == "door")
        with Image.open(src) as im:
            cut = im.convert("RGBA").split()[3]
        with Image.open(self.flattened("door")) as im:
            old = im.convert("RGBA").split()[3]
        was = {w for a in audit.alignments(old) for w in a.mask.ws}
        self.assertEqual(was, {1.0}, sorted(was)[:8])
        now = {w for a in audit.alignments(cut) for w in a.mask.ws}
        self.assertTrue([w for w in now if w < 1], sorted(now)[:8])

    def test_the_alpha_is_the_weight(self):
        # The same stencil twice over the same photograph, once as cut and
        # once flattened, and the on mean has to move: the alpha is the edge
        # strength the tool read from this very photograph, so weighting by
        # it counts the pixels where the frame's edges are strongest for
        # more than the faint ones the flattened stencil counts equally.
        tmp = Path(self.tmp.name) / "weights"
        tmp.mkdir(exist_ok=True)
        photos = tmp / "photos"
        photos.mkdir(exist_ok=True)
        for name in ("arch", "arch-flat"):
            shutil.copy(self.photos / "arch.png", photos / f"{name}.png")
        hunt = tmp / "hunt.json"
        hunt.write_text(json.dumps({
            "id": "weights", "name": "Weights", "stencils": [
                {"id": "arch", "src": next(s["src"] for s in self.stencils
                                           if s["id"] == "arch")},
                {"id": "arch-flat", "src": str(self.flattened("arch"))},
            ]}), encoding="utf-8")
        report = tmp / "weights.json"
        proc = run(hunt, "--photos", photos, "--floor", "0", "--json", report)
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        rows = {r["id"]: r for r in
                json.loads(report.read_text(encoding="utf-8"))["stencils"]}
        self.assertGreater(rows["arch"]["on"], rows["arch-flat"]["on"] + 0.02, rows)

    def test_a_confusion_refuses_and_names_where(self):
        # The floor set under everything this hunt measured, so the only
        # thing left to refuse it for is the stencil that passes in the wrong
        # room — which is the failure the floor cannot see, since a stencil
        # can be excellent against its own photograph and excellent against
        # the one next door. The blank wall is left out because nothing can
        # be put under its score.
        tmp = Path(self.tmp.name) / "wrong-place"
        tmp.mkdir(exist_ok=True)
        stencils = [s for s in self.stencils if s["id"] != "wall"]
        hunt = tmp / "hunt.json"
        hunt.write_text(json.dumps({
            "id": "wrong-place", "name": "Wrong Place", "stencils": stencils,
        }), encoding="utf-8")
        floor = min(self.rows[s["id"]]["attainable"] for s in stencils) - 0.01
        self.assertGreater(floor, 0, self.rows)
        report = tmp / "wrong-place.json"
        proc = run(hunt, "--photos", self.photos, "--floor", f"{floor:.3f}",
                   "--json", report)
        self.assertEqual(proc.returncode, 1, proc.stderr + proc.stdout)
        self.assertNotIn("floor", proc.stderr)
        wrong = [line for line in proc.stderr.splitlines()
                 if "passes in the wrong place" in line]
        self.assertEqual(len(wrong), 1, proc.stderr)
        rows = {r["id"]: r for r in
                json.loads(report.read_text(encoding="utf-8"))["stencils"]}
        for name, row in rows.items():
            self.assertGreaterEqual(row["confusion"], 0.20, row)
            self.assertIn(f"{name} ({row['confusion']:.3f} on {row['confused_with']})",
                          wrong[0])

    def test_a_broken_input_is_not_the_verdict(self):
        # Exit 1 means the stencils are not worth walking to. A hunt file
        # that will not parse and a src that is not an image are the person's
        # to fix, like a missing photograph, and go out the same door.
        tmp = Path(self.tmp.name) / "broken"
        tmp.mkdir(exist_ok=True)
        bad = tmp / "bad.json"
        bad.write_text("{ not json", encoding="utf-8")
        proc = run(bad, "--photos", self.photos)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn("bad.json", proc.stderr)
        notpng = tmp / "door-stencil.png"
        notpng.write_text("a preview, renamed", encoding="utf-8")
        hunt = tmp / "hunt.json"
        hunt.write_text(json.dumps({
            "id": "broken", "name": "Broken",
            "stencils": [{"id": "door", "src": str(notpng)}],
        }), encoding="utf-8")
        proc = run(hunt, "--photos", self.photos)
        self.assertEqual(proc.returncode, 2, proc.stderr)
        self.assertIn(str(notpng), proc.stderr)

    def test_a_missing_photograph_is_an_error_and_not_a_skip(self):
        with tempfile.TemporaryDirectory() as tmp:
            short = Path(tmp) / "photos"
            short.mkdir()
            for name in PICTURES:
                if name != "arch":
                    shutil.copy(self.photos / f"{name}.png", short / f"{name}.png")
            proc = run(self.hunt, "--photos", short)
            self.assertEqual(proc.returncode, 2, proc.stderr)
            self.assertIn("arch", proc.stderr)
            self.assertNotIn("door", proc.stdout)

    def test_floor_zero_measures_without_judging(self):
        proc = run(self.hunt, "--photos", self.photos, "--floor", "0")
        self.assertEqual(proc.returncode, 0, proc.stderr + proc.stdout)
        self.assertIn("wall", proc.stdout)
        self.assertIn("none judged", proc.stderr)

    def test_a_floor_above_every_score_refuses_and_says_which(self):
        floor = max(r["attainable"] for r in self.rows.values()) + 0.01
        proc = run(self.hunt, "--photos", self.photos, "--floor", str(floor))
        self.assertEqual(proc.returncode, 1, proc.stderr)
        under = [line for line in proc.stderr.splitlines() if "floor" in line]
        self.assertEqual(len(under), 1, proc.stderr)
        for name in PICTURES:
            self.assertIn(name, under[0])
        self.assertIn("photograph these again", under[0])


if __name__ == "__main__":
    unittest.main()
