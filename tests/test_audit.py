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

import io
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
        # The summary, then the same hunt on the smaller working frame.
        self.assertIn(f"{len(PICTURES)} stencils:", lines[1 + len(PICTURES)])
        self.assertTrue(lines[-1].startswith("on a slow phone"), self.proc.stdout)

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
        # and a stencil cut before the tool carried strength scores exactly
        # as it did. The cut stencil is checked alongside it, because weights
        # that are all one whatever the alpha would satisfy the promise by
        # ignoring the alpha altogether.
        src = next(s["src"] for s in self.stencils if s["id"] == "door")
        with Image.open(src) as im:
            cut = im.convert("RGBA").split()[3]
        with Image.open(self.flattened("door")) as im:
            old = im.convert("RGBA").split()[3]
        frame = audit.frame_for(cut.size, audit.WORK_PX)
        was = {w for a in audit.alignments(old, frame) for w in a.mask.ws}
        self.assertEqual(was, {1.0}, sorted(was)[:8])
        now = {w for a in audit.alignments(cut, frame) for w in a.mask.ws}
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

    def test_a_landscape_stencil_is_letterboxed_and_not_squashed(self):
        """lens.js fits the stencil inside the video's rectangle at the
        stencil's own aspect and scales both axes by the same amount. The
        audit did not, at first: it stretched every stencil to fill a fixed
        portrait frame, which moves the lines, the thickening and the ring by
        different amounts on the two axes and scores a stencil no camera can
        produce. Park gate's two landscape photographs read 0.389 and 0.756
        that way against 0.424 and 0.836 through the camera, so this is
        pinned rather than left to the next reader's care."""
        frame = audit.frame_for((1600, 1200), audit.WORK_PX)
        self.assertEqual(frame, (320, 240), "the frame has the photograph's shape")
        # A landscape stencil in a landscape frame fills it; the same stencil
        # in a portrait frame is letterboxed, never stretched.
        self.assertEqual(audit.placed((800, 600), (320, 240)), (320.0, 240.0))
        wide = audit.placed((800, 600), (240, 320))
        self.assertAlmostEqual(wide[0] / wide[1], 800 / 600, places=6)
        self.assertLessEqual(wide[0], 240)
        self.assertLessEqual(wide[1], 320)
        # And drawn() paints it at that size, centred, on an empty frame.
        img = Image.new("L", (800, 600), 255)
        canvas = audit.drawn(img, 1, (240, 320))
        self.assertEqual(canvas.size, (240, 320))
        box = canvas.getbbox()
        self.assertEqual((box[2] - box[0], box[3] - box[1]),
                         (round(wide[0]), round(wide[1])), box)
        self.assertGreater(box[1], 0, "a landscape stencil leaves the frame's top empty")

    def test_the_two_working_frames_are_both_measured(self):
        """A phone that cannot evaluate at 320 px inside ten milliseconds
        drops to 240 for the rest of the stencil, and confuses more there.
        Confusion is judged against a line taken from the game, so both
        frames are measured and the worse one is judged."""
        for row in self.rows.values():
            self.assertIn("attainable_slow", row)
            self.assertIn("confusion_slow", row)
        self.assertIn("on a slow phone", self.proc.stdout)

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
            # The line names the worse of the two working frames, because
            # that is the one the refusal was made on.
            worst = max(row["confusion"], row["confusion_slow"])
            self.assertGreaterEqual(worst, 0.20, row)
            partner = (row["confused_with_slow"] if row["confusion_slow"] > row["confusion"]
                       else row["confused_with"])
            self.assertIn(f"{name} ({worst:.3f} on {partner})", wrong[0])

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


class RuleTest(unittest.TestCase):
    """The pass lines a stencil is given, the verdict on each, and the
    photograph judged on its own."""

    def test_lines_come_down_for_a_hard_stencil_and_never_below_three_quarters(self):
        self.assertIsNone(audit.lines_for(0.6, 0.1))
        self.assertIsNone(audit.lines_for(0.45, 0.1))
        self.assertEqual(audit.lines_for(0.40, 0.05), [0.267, 0.222, 0.178])
        self.assertEqual(audit.lines_for(0.30, 0.05), [0.225, 0.188, 0.15])
        self.assertEqual(audit.lines_for(0.10, 0.05), [0.225, 0.188, 0.15])

    def test_the_lowest_line_keeps_clear_of_the_confusion(self):
        # The lowest line has to stay a margin above the worst wrong-place
        # score, so the lines come down less, or not at all.
        self.assertEqual(audit.lines_for(0.30, 0.15), [0.27, 0.225, 0.18])
        self.assertIsNone(audit.lines_for(0.30, 0.19))

    def test_lines_go_up_for_a_strong_stencil_that_confuses(self):
        # A wrong-place score over the line is answered with higher lines
        # where the stencil can afford them: a top line no higher than two
        # thirds of what it attains, the share the standard top is of 0.45.
        self.assertEqual(audit.lines_for(0.60, 0.227), [0.385, 0.321, 0.257])
        self.assertEqual(audit.lines_for(0.60, 0.19), [0.33, 0.275, 0.22])
        # It can afford part of the margin: it gets that part.
        self.assertEqual(audit.lines_for(0.46, 0.19), [0.307, 0.256, 0.204])
        # It cannot afford any, and it is over the line: no lines would do.
        self.assertIs(audit.lines_for(0.50, 0.227), False)
        self.assertIs(audit.lines_for(0.68, 0.30), False)
        # Exactly the standard lines are still "standard", not a copy of them.
        self.assertIsNone(audit.lines_for(0.45, 0.17))
        # The player will not take a line over 1, and no stencil attains
        # enough to ask for one: the top line is at most two thirds of that.
        for att in (0.6, 0.8, 1.0):
            for conf in (0.0, 0.2, 0.3, 0.4, 0.6):
                lines = audit.lines_for(att, conf)
                if lines:
                    self.assertLessEqual(lines[0], round(att * 2 / 3, 3) + 0.001, (att, conf, lines))
                    self.assertGreater(lines[-1], conf + audit.LINE_MARGIN - 0.001, (att, conf, lines))

    def row(self, sid, att, conf, off=0.05, slow=None):
        return {"id": sid, "attainable": att, "attainable_slow": att if slow is None else slow,
                "confusion": conf, "confusion_slow": conf, "confused_with": "other",
                "on": 0.35, "off": off}

    def test_verdicts_drop_the_weak_and_the_confusable_and_line_the_hard(self):
        rows = [self.row("strong", 0.6, 0.10), self.row("busy", 0.30, 0.05, off=0.25),
                self.row("hard", 0.40, 0.10, slow=0.38), self.row("twin", 0.50, 0.22),
                self.row("slowweak", 0.40, 0.05, slow=0.30), self.row("tall", 0.60, 0.227)]
        said = {v["id"]: v for v in audit.verdicts(rows, 0.35)}
        # Strong enough to afford lines over the wrong-place score: kept on them.
        self.assertTrue(said["tall"]["keep"])
        self.assertEqual(said["tall"]["lines"], [0.385, 0.321, 0.257])
        self.assertTrue(said["strong"]["keep"]); self.assertIsNone(said["strong"]["lines"])
        self.assertFalse(said["busy"]["keep"])
        self.assertIn("under the 0.35 floor", said["busy"]["why"])
        self.assertIn("busy beside its lines", said["busy"]["why"])
        self.assertTrue(said["hard"]["keep"])
        self.assertEqual(said["hard"]["lines"], audit.lines_for(0.38, 0.10))
        self.assertFalse(said["twin"]["keep"])
        self.assertIn("in front of other", said["twin"]["why"])
        self.assertIn("attains too little (0.500)", said["twin"]["why"])
        # The worse frame decides: a stencil that only fails on a slow phone fails.
        self.assertFalse(said["slowweak"]["keep"])
        # With the floor off, everything stays, and the weak one gets lines.
        off = {v["id"]: v for v in audit.verdicts(rows, 0)}
        self.assertTrue(all(v["keep"] for v in off.values()))
        self.assertEqual(off["busy"]["lines"], [0.225, 0.188, 0.15])
        # The one that could not afford its lines plays the standard ones.
        self.assertIsNone(off["twin"]["lines"])

    def test_the_audit_judges_a_wrong_place_score_against_the_lines_the_stencil_plays(self):
        # A hunt file that gives a stencil raised lines has answered its
        # wrong-place score already; the same score on standard lines is a
        # stencil that passes in the wrong place.
        raised = dict(self.row("tall", 0.60, 0.227), lines=[0.385, 0.321, 0.257])
        plain = self.row("tall", 0.60, 0.227)
        quiet = io.StringIO()
        self.assertEqual(audit.judge([raised], 0.35, out=quiet), 0, quiet.getvalue())
        self.assertNotIn("wrong place", quiet.getvalue())
        loud = io.StringIO()
        self.assertEqual(audit.judge([plain], 0.35, out=loud), 1)
        self.assertIn("passes in the wrong place: tall (0.227 on other)", loud.getvalue())
        # Lines that do not cover the score are named beside it.
        low = dict(self.row("tall", 0.60, 0.227), lines=[0.30, 0.25, 0.20])
        said = io.StringIO()
        self.assertEqual(audit.judge([low], 0.35, out=said), 1)
        self.assertIn("over its 0.2 line", said.getvalue())
        # Lines a stencil cannot afford are refused too, however they got
        # into the file: the wrong-place test would otherwise take any
        # number at its word.
        tall = dict(self.row("tall", 0.40, 0.35), lines=[0.9, 0.8, 0.7])
        said = io.StringIO()
        self.assertEqual(audit.judge([tall], 0.35, out=said), 1)
        self.assertIn("lines beyond reach: tall (top 0.9, attains 0.400)", said.getvalue())
        # Exactly what it can afford is not beyond reach.
        fine = dict(self.row("tall", 0.60, 0.227), lines=[0.4, 0.333, 0.267])
        self.assertEqual(audit.judge([fine], 0.35, out=io.StringIO()), 0)
        # The partner named beside the number is the worse frame's.
        slow = dict(self.row("tall", 0.60, 0.10), confusion_slow=0.30,
                    confused_with_slow="slowpartner")
        said = io.StringIO()
        self.assertEqual(audit.judge([slow], 0.35, out=said), 1)
        self.assertIn("tall (0.300 on slowpartner)", said.getvalue())

    def test_the_summary_says_raised_by_the_top_line(self):
        # A raise that rounds its lowest line to exactly 0.2 is still a raise.
        self.assertEqual(audit.lines_for(0.451, 0.18), [0.301, 0.251, 0.2])
        rows = [dict(self.row("edge", 0.451, 0.18), lines=[0.301, 0.251, 0.2]),
                dict(self.row("hard", 0.40, 0.05), lines=[0.267, 0.222, 0.178])]
        said = io.StringIO()
        audit.summarise(rows, said)
        self.assertIn("own lines: edge 0.301/0.251/0.2 (raised), hard 0.267/0.222/0.178 (lowered)",
                      said.getvalue())

    def test_a_hunt_file_with_bad_lines_is_a_broken_input(self):
        for bad in (0.5, [0.3, 0.25], [0.3, 0.3, 0.2], [1.2, 0.5, 0.2], ["a", "b", "c"]):
            self.assertFalse(audit.well_formed_lines(bad), bad)
        self.assertTrue(audit.well_formed_lines([0.385, 0.321, 0.257]))

    def test_why_weak_names_the_ring_first_then_the_frame_then_the_edges(self):
        self.assertIn("busy beside its lines", audit.why_weak(self.row("a", 0.2, 0.1, off=0.21), None))
        self.assertIn("too little in the frame",
                      audit.why_weak(self.row("a", 0.2, 0.1), {"sparse": True, "inked": 0.02}))
        self.assertIn("faint edges", audit.why_weak(self.row("a", 0.2, 0.1), {"sparse": False}))

    def test_assess_scores_a_clean_subject_high_a_blank_frame_nought_and_noise_as_busy(self):
        clean = Image.new("RGB", (300, 400), (200, 196, 188))
        d = ImageDraw.Draw(clean)
        d.rectangle([40, 50, 250, 350], outline=(20, 20, 20), width=6)
        d.rectangle([80, 90, 210, 200], outline=(20, 20, 20), width=5)
        a = audit.assess(clean)
        self.assertGreater(a["score"], 0.6, a)
        self.assertLess(a["off"], 0.1, a)
        self.assertEqual(a["frame"], "240x320")
        blank = Image.new("RGB", (300, 400), (150, 150, 150))
        b = audit.assess(blank)
        self.assertEqual(b["score"], 0.0, b)
        self.assertTrue(b["sparse"], b)
        import random
        rnd = random.Random(3)
        noisy = Image.new("RGB", (300, 400))
        noisy.putdata([(v, v, v) for v in (rnd.randint(60, 230) for _ in range(300 * 400))])
        ImageDraw.Draw(noisy).rectangle([40, 50, 250, 350], outline=(10, 10, 10), width=6)
        c = audit.assess(noisy)
        # Noise beside the lines is read as a busier ring and a lower score
        # than the same lines on a plain ground; how much busier depends on
        # the noise, so it is held against the clean frame, not a line.
        self.assertGreater(c["off"], 3 * a["off"], (a, c))
        self.assertLess(c["score"], a["score"] - 0.2, (a, c))

