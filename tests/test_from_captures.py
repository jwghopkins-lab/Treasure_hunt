"""pipeline/from_captures.py, run as a session runs it, with no network.

    python3 -m unittest discover -s tests -p 'test_*.py'

--base pointing at a directory makes the fetch a copy, so the whole path runs
offline: three small pictures drawn here stand in for the bucket, and what
comes out is checked from the photographs on disk through the stencils to the
hunt file and the build's own validation of it. --long 200 keeps the edge map
cheap; the arithmetic itself is test_stencil.py's business.

The stencils have to be written under app/ for the build to accept their
srcs, so the out directory is a temporary one there, as test_stencil.py's is,
and it goes away with the test. The photographs land where the tool puts
them, photos/<slug>/, which is gitignored.
"""

import io
import json
import subprocess
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path

from PIL import Image, ImageDraw

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import build  # noqa: E402
import from_captures  # noqa: E402

BASE = Path(__file__).resolve().parent.parent
TOOL = BASE / "pipeline" / "from_captures.py"

SLUG = "tmp-test-captures"
NAME = "Hollow Lane"

# A good fix, and one so wide the player's distance line would ignore it.
GOOD_ACC = 12.3
BAD_ACC = 120


def run(*args):
    """from_captures.py as a subprocess, the way it is run, so the command
    line and the exit code are tested along with what it writes."""
    return subprocess.run([sys.executable, str(TOOL), *map(str, args)],
                          capture_output=True, text=True, cwd=BASE)


def scene(path, seed):
    """A small picture with a few long edges in it, so the stencil is neither
    empty nor noise, and a different one per photograph."""
    im = Image.new("RGB", (300, 400), (205, 200, 190))
    d = ImageDraw.Draw(im)
    d.rectangle([40 + seed * 8, 50, 250, 350 - seed * 10], outline=(35, 30, 30), width=6)
    d.rectangle([80, 90 + seed * 12, 210, 200], outline=(35, 30, 30), width=5)
    d.ellipse([120, 240, 200, 320], outline=(35, 30, 30), width=5)
    path.parent.mkdir(parents=True, exist_ok=True)
    im.save(path, "JPEG", quality=92)


def hunt_of(path):
    return json.loads(Path(path).read_text(encoding="utf-8"))


class HuntTest(unittest.TestCase):
    """One run over three photographs in a directory that stands in for the
    bucket: two with a good fix, one with a fix too wide to use and a clue
    that is only spaces."""

    ROWS = [
        {"id": "front-door", "path": "hollow/one.jpg", "clue": "Where the milk is left.",
         "lat": 51.4700, "lon": -0.1000, "accuracy": GOOD_ACC},
        {"id": "the-shed", "path": "hollow/two.jpg",
         "lat": 51.4712, "lon": -0.0984, "accuracy": 8},
        {"id": "back-gate", "path": "hollow/three.jpg", "clue": "   ",
         "lat": 51.4705, "lon": -0.0991, "accuracy": BAD_ACC},
    ]

    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        root = Path(cls.tmp.name)
        cls.bucket = root / "bucket"
        for n, name in enumerate(("one", "two", "three")):
            scene(cls.bucket / "hollow" / f"{name}.jpg", n)
        cls.manifest = root / "manifest.json"
        cls.manifest.write_text(json.dumps(cls.ROWS), encoding="utf-8")
        cls.content = root / "content" / f"{SLUG}.json"
        cls.photos = BASE / "photos" / SLUG
        cls.out = Path(tempfile.mkdtemp(prefix="tmp-test-", dir=BASE / "app" / "img"))
        cls.addClassCleanup(shutil.rmtree, cls.out, ignore_errors=True)
        cls.addClassCleanup(shutil.rmtree, cls.photos, ignore_errors=True)
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.proc = run("--slug", SLUG, "--name", NAME, "--manifest", cls.manifest,
                       "--base", cls.bucket, "--out", cls.out, "--content", cls.content,
                       "--long", "200")

    def test_exits_cleanly_and_says_what_it_made(self):
        self.assertEqual(self.proc.returncode, 0, self.proc.stderr)
        self.assertIn(f"{SLUG}: 3 stencils, 2 located, 1 with a clue "
                      "— front-door, the-shed, back-gate", self.proc.stderr)
        self.assertEqual(self.proc.stdout, "")

    def test_the_photographs_land_under_the_slug(self):
        for row in self.ROWS:
            photo = self.photos / f"{row['id']}.jpg"
            self.assertTrue(photo.is_file(), photo)
            self.assertEqual(photo.read_bytes()[:3], b"\xff\xd8\xff")
        self.assertEqual(sorted(p.name for p in self.photos.iterdir()),
                         ["back-gate.jpg", "front-door.jpg", "the-shed.jpg"])

    def test_the_stencils_and_their_hints_are_under_the_out_directory(self):
        for row in self.ROWS:
            for kind in ("stencil", "stencil-hint", "stencil-preview"):
                ext = "jpg" if kind.endswith("preview") else "png"
                self.assertTrue((self.out / f"{row['id']}-{kind}.{ext}").is_file(),
                                f"{row['id']}-{kind}.{ext}")

    def test_the_hunt_file_is_written_as_the_others_are(self):
        text = self.content.read_text(encoding="utf-8")
        self.assertTrue(text.startswith('{\n  "id": "'), text[:40])
        self.assertTrue(text.endswith("}\n"))
        hunt = hunt_of(self.content)
        self.assertEqual(hunt["id"], SLUG)
        self.assertEqual(hunt["name"], NAME)
        self.assertIs(hunt["test_mode"], False)

    def test_the_build_takes_it(self):
        # The build's own validation, on what was written, is what the tool
        # runs before it moves the file into place; this is that promise kept.
        err = io.StringIO()
        with redirect_stderr(err):
            build.validate(hunt_of(self.content), SLUG)
        self.assertIn("3 stencils, a hunt has six to nine", err.getvalue())

    def test_the_stencils_are_in_the_manifest_order_with_their_clues(self):
        stencils = hunt_of(self.content)["stencils"]
        self.assertEqual([s["id"] for s in stencils], [r["id"] for r in self.ROWS])
        for s in stencils:
            self.assertEqual(s["src"], f"img/{self.out.name}/{s['id']}-stencil.png")
            self.assertEqual(s["hint"], f"img/{self.out.name}/{s['id']}-stencil-hint.png")
            self.assertTrue((BASE / "app" / s["src"]).is_file())
        self.assertEqual(stencils[0]["clue"], "Where the milk is left.")
        # A clue of nothing but spaces is no clue, not an empty strip.
        self.assertNotIn("clue", stencils[1])
        self.assertNotIn("clue", stencils[2])

    def test_a_location_only_where_the_fix_was_good_enough(self):
        stencils = hunt_of(self.content)["stencils"]
        self.assertEqual(stencils[0]["location"], {"lat": 51.47, "lon": -0.1})
        self.assertEqual(stencils[1]["location"], {"lat": 51.4712, "lon": -0.0984})
        self.assertNotIn("location", stencils[2])
        self.assertIn(f"back-gate: the fix is {BAD_ACC} m wide", self.proc.stderr)

    def test_the_map_is_the_box_round_the_locations(self):
        hunt = hunt_of(self.content)
        (south, west), (north, east) = hunt["map"]["bounds"]
        for v in (south, west, north, east):
            self.assertEqual(v, round(v, 4))
        for s in hunt["stencils"]:
            if "location" not in s:
                continue
            lat, lon = s["location"]["lat"], s["location"]["lon"]
            self.assertTrue(south < lat < north, (south, lat, north))
            self.assertTrue(west < lon < east, (west, lon, east))
        # About 150 m on each side: a degree of latitude is 111 km, and the
        # margin east and west is wider than that by 1 / cos(51.47°).
        self.assertAlmostEqual(south, 51.47 - 0.00135, places=3)
        self.assertAlmostEqual(north, 51.4712 + 0.00135, places=3)
        self.assertGreater(-0.1 - west, 0.00135)
        self.assertLess(-0.1 - west, 0.0025)

    def test_no_locations_leaves_the_map_out(self):
        content = Path(self.tmp.name) / "plain" / f"{SLUG}.json"
        proc = run("--slug", SLUG, "--name", NAME, "--manifest", self.manifest,
                   "--base", self.bucket, "--out", self.out, "--content", content,
                   "--photos", Path(self.tmp.name) / "photos", "--no-locations",
                   "--long", "200")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        hunt = hunt_of(content)
        self.assertNotIn("map", hunt)
        for s in hunt["stencils"]:
            self.assertNotIn("location", s)
        self.assertIn(f"{SLUG}: 3 stencils, 0 located,", proc.stderr)

    def test_a_file_url_names_a_directory_as_well(self):
        root = Path(self.tmp.name)
        manifest = root / "one.json"
        manifest.write_text(json.dumps(self.ROWS[:1]), encoding="utf-8")
        content = root / "only" / f"{SLUG}.json"
        proc = run("--slug", SLUG, "--name", NAME, "--manifest", manifest,
                   "--base", self.bucket.as_uri(), "--out", self.out, "--content", content,
                   "--photos", root / "photos", "--long", "200")
        self.assertEqual(proc.returncode, 0, proc.stderr)
        self.assertTrue((root / "photos" / "front-door.jpg").is_file())
        self.assertEqual([s["id"] for s in hunt_of(content)["stencils"]], ["front-door"])


class RefusalTest(unittest.TestCase):
    """Every way a manifest or a bucket can be wrong: the message names the
    problem, and the hunt file the run would have written is not there."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.bucket = self.root / "bucket"
        scene(self.bucket / "hollow" / "one.jpg", 0)
        self.content = self.root / "content" / f"{SLUG}.json"
        self.photos = self.root / "photos"
        self.out = self.root / "out"

    def refuse(self, rows):
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps(rows), encoding="utf-8")
        proc = run("--slug", SLUG, "--name", NAME, "--manifest", manifest,
                   "--base", self.bucket, "--out", self.out, "--content", self.content,
                   "--photos", self.photos, "--long", "200")
        self.assertNotEqual(proc.returncode, 0)
        self.assertFalse(self.content.exists(), "a hunt file was left behind")
        return proc

    def test_a_body_that_is_not_a_jpeg(self):
        (self.bucket / "hollow" / "note.jpg").write_bytes(b'{"error":"not found"}')
        proc = self.refuse([{"id": "front-door", "path": "hollow/note.jpg"}])
        self.assertIn("front-door", proc.stderr)
        self.assertIn("is not a JPEG", proc.stderr)
        # Nothing half fetched: the stencil tool must never be handed a file
        # that is not the photograph.
        self.assertFalse((self.photos / "front-door.jpg").exists())
        self.assertEqual(list(self.photos.glob("*")) if self.photos.exists() else [], [])

    def test_a_photograph_that_is_not_there(self):
        proc = self.refuse([{"id": "front-door", "path": "hollow/nope.jpg"}])
        self.assertIn("front-door", proc.stderr)
        self.assertIn("hollow/nope.jpg", proc.stderr)

    def test_a_duplicated_id(self):
        proc = self.refuse([{"id": "front-door", "path": "hollow/one.jpg"},
                            {"id": "front-door", "path": "hollow/one.jpg"}])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("duplicate id 'front-door'", proc.stderr)

    def test_an_id_that_is_not_slug_safe(self):
        proc = self.refuse([{"id": "Front Door", "path": "hollow/one.jpg"}])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("id 'Front Door' must be lower-case letters", proc.stderr)

    def test_a_path_that_climbs_out_of_the_bucket(self):
        proc = self.refuse([{"id": "front-door", "path": "../../etc/passwd"}])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("'../../etc/passwd'", proc.stderr)
        self.assertIn("not climbing out", proc.stderr)

    def test_a_content_file_that_is_not_named_for_the_slug(self):
        # The build publishes each hunt at /<its file's name>/ and refuses one
        # whose id is not that name, so this run would write a file the build
        # then throws out, taking the whole deploy with it.
        manifest = self.root / "manifest.json"
        manifest.write_text(json.dumps([{"id": "front-door", "path": "hollow/one.jpg"}]),
                            encoding="utf-8")
        other = self.root / "content" / "other.json"
        proc = run("--slug", SLUG, "--name", NAME, "--manifest", manifest,
                   "--base", self.bucket, "--out", self.out, "--content", other,
                   "--photos", self.photos, "--long", "200")
        self.assertEqual(proc.returncode, 2)
        self.assertIn("names the hunt 'other'", proc.stderr)
        self.assertFalse(other.exists())
        # And nothing was fetched: the name is checked before the first photograph.
        self.assertFalse(self.photos.exists())

    def test_a_manifest_that_is_not_a_list_of_objects(self):
        proc = self.refuse(["hollow/one.jpg"])
        self.assertEqual(proc.returncode, 2)
        self.assertIn("must be a list of objects", proc.stderr)


class BoxTest(unittest.TestCase):
    """The map's box on its own, which is where the rounding is."""

    def test_rounding_never_leaves_a_location_on_the_edge(self):
        # A margin so small that four decimal places round the edge back onto
        # the location it was meant to be outside: it takes one more step out.
        self.assertEqual(from_captures.widen(51.47, 51.47, 0), (51.4699, 51.4701))

    def test_the_margin_east_and_west_grows_with_the_latitude(self):
        (south, west), (north, east) = from_captures.map_bounds([{"lat": 0.0, "lon": 0.0}])
        (far_south, far_west), (far_north, far_east) = from_captures.map_bounds(
            [{"lat": 60.0, "lon": 0.0}])
        self.assertAlmostEqual(north - south, far_north - far_south, places=6)
        # A degree of longitude at 60 degrees is half of one at the equator,
        # so 150 m of it is twice as many degrees.
        self.assertGreater(far_east - far_west, 1.9 * (east - west))


if __name__ == "__main__":
    unittest.main()
