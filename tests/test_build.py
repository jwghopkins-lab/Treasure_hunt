"""pipeline/build.py against a stub app in a temporary directory.

    python3 -m unittest discover -s tests -p 'test_*.py'

The stub has the three marker lines of player.html, the one of capture.html,
a lens.js, a few stencil PNGs and a vendored Leaflet, and build.BASE / APP are
pointed at it, so these tests do not depend on the real templates existing
and never write into the repository.
"""

import io
import json
import re
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "pipeline"))
import build  # noqa: E402

PLAYER = """<!doctype html>
<html><head>
<title>Treasure Hunt</title>
<!-- LEAFLET GOES HERE -->
</head><body>
<!-- HUNT GOES HERE -->
</body></html>
"""
CAPTURE = """<!doctype html>
<html><head><title>Capture</title></head><body>
<!-- SUPABASE GOES HERE -->
</body></html>
"""
SUPABASE = {"url": "https://example.supabase.co", "anon_key": "anon-key-123"}


def hunt(n=7, located=(0, 1, 2), clue=(0,), **over):
    """A valid hunt of n stencils, the given ones located and with a clue."""
    stencils = []
    for i in range(n):
        s = {"id": f"s{i + 1}", "src": f"img/sample/s{i + 1}-stencil.png"}
        if i in clue:
            s["clue"] = f"Clue {i + 1}."
        if i in located:
            s["location"] = {"lat": 51.50 + i / 1000, "lon": -0.12 + i / 1000}
        stencils.append(s)
    h = {"id": "sample", "name": "Sample Hunt", "stencils": stencils}
    h.update(over)
    return h


BOUNDS = {"bounds": [[51.49, -0.13], [51.52, -0.10]]}
IMAGE = {"image": "img/sample/map.jpg"}


def quiet(fn, *args, **kw):
    """Run fn with stdout and stderr captured; returns (result, out, err)."""
    out, err = io.StringIO(), io.StringIO()
    with redirect_stdout(out), redirect_stderr(err):
        result = fn(*args, **kw)
    return result, out.getvalue(), err.getvalue()


def baked(page):
    """window.HUNT and window.SUPABASE parsed back out of a built page."""
    m = re.search(r"<script>window\.HUNT = (.*); window\.SUPABASE = (.*);</script>", page)
    assert m, "no HUNT script in the page"
    return json.loads(m.group(1)), json.loads(m.group(2))


class Sandbox(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="th-build-"))
        self.addCleanup(shutil.rmtree, self.tmp, True)
        self.repo = self.tmp / "repo"
        self.app = self.repo / "app"
        self.content = self.repo / "content"
        self.site = self.repo / "site"
        self.content.mkdir(parents=True)
        (self.app / "player.html").parent.mkdir(parents=True)
        (self.app / "player.html").write_text(PLAYER)
        (self.app / "capture.html").write_text(CAPTURE)
        (self.app / "lens.js").write_text("// lens\n")
        img = self.app / "img" / "sample"
        img.mkdir(parents=True)
        # Ten, one more than a hunt should have, so the count warning can be tried.
        for i in range(1, 11):
            (img / f"s{i}-stencil.png").write_bytes(b"PNG" + bytes([i]))
        # Things beside the stencils that must never reach the site.
        (img / "s1-stencil-preview.jpg").write_bytes(b"JPG")
        (img / "unused-stencil.png").write_bytes(b"PNG")
        (img / "map.jpg").write_bytes(b"MAP")
        leaflet = self.app / "vendor" / "leaflet"
        (leaflet / "images").mkdir(parents=True)
        (leaflet / "leaflet.js").write_text("// leaflet\n")
        (leaflet / "leaflet.css").write_text("/* leaflet */\n")
        (leaflet / "LICENSE").write_text("BSD\n")
        (leaflet / "images" / "marker-icon.png").write_bytes(b"PNG")
        (leaflet / "images" / "layers.png").write_bytes(b"PNG")
        self.saved = build.BASE, build.APP
        build.BASE, build.APP = self.repo, self.app
        self.addCleanup(self.restore)

    def restore(self):
        build.BASE, build.APP = self.saved

    def write(self, h, stem=None):
        path = self.content / f"{stem or h['id']}.json"
        path.write_text(json.dumps(h))
        return str(path)

    def build(self, h, stem=None, out=None, supabase=None):
        out = out or self.site / (stem or h["id"])
        _, self.stdout, self.stderr = quiet(build.build, self.write(h, stem), out, supabase)
        return out

    def page(self, h, **kw):
        return (self.build(h, **kw) / "index.html").read_text()

    def assertFails(self, h, *needles, stem=None, fn=None):
        with self.assertRaises(build.ContentError) as cm:
            quiet(fn or build.validate, h, stem if fn else (stem or "sample"))
        message = str(cm.exception)
        for needle in needles:
            self.assertIn(needle, message)
        return message


class Validation(Sandbox):
    def test_a_good_hunt_validates_and_returns_its_images(self):
        h = hunt(map=IMAGE)
        images, _, err = quiet(build.validate, h, "sample")
        self.assertEqual(images, [f"img/sample/s{i}-stencil.png" for i in range(1, 8)] + ["img/sample/map.jpg"])
        self.assertEqual(err, "")
        self.assertIs(h["test_mode"], False)

    def test_hunt_must_be_an_object(self):
        self.assertFails(["not", "a", "hunt"], "hunt: must be an object")

    def test_unknown_top_level_key_is_named(self):
        self.assertFails(hunt(title="x"), "hunt: unknown key 'title'", "id, name, test_mode, map, stencils")

    def test_id_is_required(self):
        h = hunt()
        del h["id"]
        self.assertFails(h, "hunt: no id")

    def test_id_must_be_slug_safe(self):
        for bad in ("Sample", "sam ple", "sam_ple", "", 3, None):
            h = hunt(id=bad)
            self.assertFails(h, "hunt: id", "lower-case letters, digits and hyphens", stem=bad if isinstance(bad, str) else "x")

    def test_id_is_at_most_forty_characters(self):
        long = "a" * 41
        h = hunt(); h["id"] = long
        self.assertFails(h, "hunt: id", "longer than 40", stem=long)
        h = hunt(); h["id"] = "a" * 40
        quiet(build.validate, h, "a" * 40)

    def test_id_must_equal_the_file_stem(self):
        self.assertFails(hunt(), "hunt: id 'sample' does not match the file name 'other'", stem="other")
        self.assertFails(hunt(), "does not match", stem="other", fn=lambda h, s: build.build(self.write(h, s), self.site / "x"))
        # Without a stem, as when validating a dict that came from nowhere.
        quiet(build.validate, hunt(), None)

    def test_name_is_required_and_text(self):
        h = hunt()
        del h["name"]
        self.assertFails(h, "hunt: no name")
        self.assertFails(hunt(name=""), "hunt: name is ''")
        self.assertFails(hunt(name="   "), "hunt: name is '   '")
        self.assertFails(hunt(name=7), "hunt: name is 7, must be text")

    def test_test_mode_defaults_false_and_must_be_boolean(self):
        h = hunt()
        quiet(build.validate, h, "sample")
        self.assertIs(h["test_mode"], False)
        h = hunt(test_mode=True)
        quiet(build.validate, h, "sample")
        self.assertIs(h["test_mode"], True)
        self.assertFails(hunt(test_mode="yes"), "hunt: test_mode is 'yes'")
        self.assertFails(hunt(test_mode=1), "hunt: test_mode is 1")

    def test_stencils_required_and_a_list(self):
        h = hunt()
        del h["stencils"]
        self.assertFails(h, "hunt: no stencils")
        self.assertFails(hunt(stencils={"a": 1}), "hunt: stencils must be a list")

    def test_stencil_count_warns_outside_six_to_nine(self):
        for n, warns in ((0, True), (5, True), (6, False), (9, False), (10, True)):
            h = hunt(n=n, located=(), clue=())
            _, _, err = quiet(build.validate, h, "sample")
            if warns:
                self.assertIn(f"warning — hunt 'sample': {n} stencils, a hunt has six to nine", err)
            else:
                self.assertEqual(err, "", n)

    def test_stencil_must_be_an_object(self):
        h = hunt()
        h["stencils"][2] = "s3"
        self.assertFails(h, "stencil #3: must be an object")

    def test_stencil_unknown_key_is_named(self):
        h = hunt()
        h["stencils"][1]["clues"] = "x"
        self.assertFails(h, "stencil 's2': unknown key 'clues'", "id, src, clue, location")

    def test_stencil_id_required_slug_safe_and_unique(self):
        h = hunt()
        del h["stencils"][0]["id"]
        self.assertFails(h, "stencil #1: no id")
        h = hunt()
        h["stencils"][3]["id"] = "S 4"
        self.assertFails(h, "stencil 'S 4': id 'S 4' must be lower-case letters, digits and hyphens")
        h = hunt()
        h["stencils"][3]["id"] = ""
        self.assertFails(h, "stencil #4: id ''")
        h = hunt()
        h["stencils"][4]["id"] = "s2"
        self.assertFails(h, "stencil 's2': duplicate id")

    def test_stencil_src_required_and_under_app(self):
        h = hunt()
        del h["stencils"][0]["src"]
        self.assertFails(h, "stencil 's1': no src")
        h = hunt()
        h["stencils"][0]["src"] = ""
        self.assertFails(h, "stencil 's1': no src")
        h = hunt()
        h["stencils"][5]["src"] = "img/sample/missing-stencil.png"
        self.assertFails(h, "stencil 's6': src 'img/sample/missing-stencil.png' is not under app/")
        h = hunt()
        h["stencils"][0]["src"] = 5
        self.assertFails(h, "stencil 's1': src must be a path under app/")

    def test_stencil_hint_must_exist_under_app_and_is_copied(self):
        h = hunt()
        h["stencils"][1]["hint"] = "img/sample/s2-stencil.png"
        images = quiet(build.validate, h, "sample")[0]
        self.assertEqual(images.count("img/sample/s2-stencil.png"), 2)
        h["stencils"][1]["hint"] = "img/sample/nothing-stencil-hint.png"
        self.assertFails(h, "stencil 's2': hint 'img/sample/nothing-stencil-hint.png' is not under app/")

    def test_stencil_src_may_not_climb_out_of_app(self):
        (self.repo / "secret.png").write_bytes(b"PNG")
        h = hunt()
        h["stencils"][0]["src"] = "../secret.png"
        self.assertFails(h, "stencil 's1': src '../secret.png' must be a path under app/")
        h = hunt()
        h["stencils"][0]["src"] = str(self.repo / "secret.png")
        self.assertFails(h, "stencil 's1'", "must be a path under app/")

    def test_clue_if_present_is_a_short_sentence(self):
        for bad in ("", "  ", None, 3, ["x"]):
            h = hunt()
            h["stencils"][1]["clue"] = bad
            self.assertFails(h, "stencil 's2': clue is", "must be a sentence of text")
        h = hunt()
        h["stencils"][1]["clue"] = "x" * 201
        self.assertFails(h, "stencil 's2': clue is 201 characters, at most 200")
        h = hunt()
        h["stencils"][1]["clue"] = "x" * 200
        quiet(build.validate, h, "sample")

    def test_location_if_present_is_on_the_earth(self):
        h = hunt()
        h["stencils"][0]["location"] = [51.5, -0.1]
        self.assertFails(h, "stencil 's1'.location: must be an object with lat and lon")
        h = hunt()
        h["stencils"][0]["location"] = None
        self.assertFails(h, "stencil 's1'.location: must be an object")
        h = hunt()
        h["stencils"][0]["location"] = {"lat": 51.5}
        self.assertFails(h, "stencil 's1'.location: no lon")
        h = hunt()
        h["stencils"][0]["location"] = {"lon": 0.1}
        self.assertFails(h, "stencil 's1'.location: no lat")
        h = hunt()
        h["stencils"][0]["location"] = {"lat": True, "lon": 0.1}
        self.assertFails(h, "stencil 's1'.location: lat is True, must be a number")
        h = hunt()
        h["stencils"][0]["location"] = {"lat": "51.5", "lon": 0.1}
        self.assertFails(h, "stencil 's1'.location: lat is '51.5', must be a number")
        h = hunt()
        h["stencils"][0]["location"] = {"lat": 91, "lon": 0.1}
        self.assertFails(h, "stencil 's1'.location: lat/lon are not on the Earth")
        h = hunt()
        h["stencils"][0]["location"] = {"lat": 51.5, "lon": -181}
        self.assertFails(h, "stencil 's1'.location: lat/lon are not on the Earth")
        h = hunt()
        h["stencils"][0]["location"] = {"lat": 51.5, "lon": 0.1, "alt": 3}
        self.assertFails(h, "stencil 's1'.location: unknown key 'alt' (lat, lon)")
        # The edges of the Earth are on it.
        h = hunt(located=())
        h["stencils"][0]["location"] = {"lat": -90, "lon": 180}
        quiet(build.validate, h, "sample")

    def test_map_is_exactly_one_of_bounds_or_image(self):
        self.assertFails(hunt(map="img/sample/map.jpg"), "hunt.map: must be an object with bounds or image")
        self.assertFails(hunt(map=None), "hunt.map: must be an object")
        self.assertFails(hunt(map={}), "hunt.map: must have exactly one of bounds or image")
        self.assertFails(hunt(map={**BOUNDS, **IMAGE}), "hunt.map: must have exactly one of bounds or image")
        self.assertFails(hunt(map={**IMAGE, "zoom": 3}), "hunt.map: unknown key 'zoom' (bounds, image)")

    def test_map_image_must_exist_under_app(self):
        self.assertFails(hunt(map={"image": "img/sample/nowhere.jpg"}),
                         "hunt.map: image 'img/sample/nowhere.jpg' is not under app/")
        self.assertFails(hunt(map={"image": ""}), "hunt.map: no image")
        self.assertFails(hunt(map={"image": "../secret.jpg"}), "hunt.map: image '../secret.jpg' must be a path under app/")

    def test_bounds_are_two_pairs_south_below_north_west_below_east(self):
        shape = "hunt.map.bounds: must be two [lat, lon] pairs"
        for bad in ([[51.49, -0.13]], [[51.49, -0.13], [51.52]], [[51.49, -0.13], [51.52, "-0.10"]],
                    [[51.49, -0.13], [51.52, True]], "51.49,-0.13,51.52,-0.10", [[51.49, -0.13], [51.52, -0.10], [0, 0]]):
            self.assertFails(hunt(map={"bounds": bad}), shape)
        self.assertFails(hunt(map={"bounds": [[91, -0.13], [51.52, -0.10]]}), "hunt.map.bounds: corners are not on the Earth")
        self.assertFails(hunt(map={"bounds": [[51.49, -181], [51.52, -0.10]]}), "hunt.map.bounds: corners are not on the Earth")
        self.assertFails(hunt(map={"bounds": [[51.52, -0.13], [51.49, -0.10]]}),
                         "hunt.map.bounds: south 51.52 must be below north 51.49")
        self.assertFails(hunt(map={"bounds": [[51.49, -0.10], [51.52, -0.13]]}),
                         "hunt.map.bounds: west -0.1 must be below east -0.13")
        self.assertFails(hunt(map={"bounds": [[51.49, -0.13], [51.49, -0.10]]}), "south 51.49 must be below north 51.49")

    def test_bounds_must_contain_every_located_stencil(self):
        h = hunt(map=BOUNDS)
        h["stencils"][2]["location"] = {"lat": 51.53, "lon": -0.12}
        self.assertFails(h, "stencil 's3': location 51.53, -0.12 is outside the map bounds")
        h = hunt(map=BOUNDS)
        h["stencils"][1]["location"] = {"lat": 51.50, "lon": -0.09}
        self.assertFails(h, "stencil 's2': location 51.5, -0.09 is outside the map bounds")
        # On the line counts as inside.
        h = hunt(map=BOUNDS, located=(0,))
        h["stencils"][0]["location"] = {"lat": 51.49, "lon": -0.10}
        quiet(build.validate, h, "sample")

    def test_bounds_with_no_located_stencil_is_an_error(self):
        self.assertFails(hunt(map=BOUNDS, located=()),
                         "hunt.map.bounds: there is a street map but no stencil has a location")
        # An image map has no such need: the locations are for the distance line only.
        quiet(build.validate, hunt(map=IMAGE, located=()), "sample")

    def test_load_names_the_line_of_bad_json(self):
        path = self.content / "sample.json"
        path.write_text('{"id": "sample",\n "name": }')
        with self.assertRaises(build.ContentError) as cm:
            build.load(path)
        self.assertIn(f"{path}: line 2:", str(cm.exception))


class Bake(Sandbox):
    def test_hunt_and_null_supabase_are_baked_with_defaults_filled_in(self):
        page = self.page(hunt())
        h, sb = baked(page)
        self.assertEqual(h["id"], "sample")
        self.assertEqual(h["name"], "Sample Hunt")
        self.assertIs(h["test_mode"], False)
        self.assertNotIn("map", h)
        self.assertEqual([s["id"] for s in h["stencils"]], [f"s{i}" for i in range(1, 8)])
        self.assertEqual(h["stencils"][0]["clue"], "Clue 1.")
        self.assertEqual(h["stencils"][0]["location"], {"lat": 51.5, "lon": -0.12})
        self.assertNotIn("clue", h["stencils"][3])
        self.assertNotIn("location", h["stencils"][3])
        self.assertIsNone(sb)
        self.assertIn("window.SUPABASE = null;", page)
        self.assertNotIn("HUNT GOES HERE", page)

    def test_title_is_the_name_escaped(self):
        page = self.page(hunt(name='Tom & "Jerry" <3'))
        self.assertIn("<title>Tom &amp; &quot;Jerry&quot; &lt;3</title>", page)
        self.assertNotIn("<title>Treasure Hunt</title>", page)

    def test_script_closers_in_the_hunt_are_escaped(self):
        h = hunt()
        h["stencils"][0]["clue"] = "Look </script><b>up</b>."
        page = self.page(h)
        self.assertNotIn("</script><b>", page)
        self.assertIn('<\\/script><b>up<\\/b>', page)
        self.assertEqual(baked(page)[0]["stencils"][0]["clue"], "Look </script><b>up</b>.")
        # The same escape guards the config.
        self.assertIn('"anon_key": "a<\\/script>b"', build.script_json({"anon_key": "a</script>b"}))

    def test_leaflet_tags_only_with_a_map_of_either_kind(self):
        tags = '<link rel="stylesheet" href="vendor/leaflet/leaflet.css">\n<script src="vendor/leaflet/leaflet.js"></script>'
        page = self.page(hunt())
        self.assertNotIn("leaflet", page)
        self.assertNotIn("LEAFLET GOES HERE", page)
        self.assertIn(tags, self.page(hunt(map=BOUNDS)))
        self.assertIn(tags, self.page(hunt(map=IMAGE)))

    def test_leaflet_copied_only_with_a_map_of_either_kind(self):
        out = self.build(hunt())
        self.assertFalse((out / "vendor").exists())
        for m in (BOUNDS, IMAGE):
            out = self.build(hunt(map=m))
            self.assertTrue((out / "vendor" / "leaflet" / "leaflet.js").is_file())
            self.assertTrue((out / "vendor" / "leaflet" / "leaflet.css").is_file())
            self.assertEqual(sorted(p.name for p in (out / "vendor" / "leaflet" / "images").iterdir()),
                             ["layers.png", "marker-icon.png"])
            self.assertFalse((out / "vendor" / "leaflet" / "LICENSE").exists())

    def test_leaflet_missing_from_app_is_an_error(self):
        (self.app / "vendor" / "leaflet" / "leaflet.js").unlink()
        with self.assertRaises(build.ContentError) as cm:
            self.build(hunt(map=IMAGE))
        self.assertIn("app/vendor/leaflet: leaflet.js is not vendored", str(cm.exception))

    def test_only_the_referenced_images_are_copied(self):
        out = self.build(hunt(n=6))
        got = sorted(str(p.relative_to(out)) for p in out.rglob("*") if p.is_file())
        self.assertEqual(got, ["img/sample/s1-stencil.png", "img/sample/s2-stencil.png",
                               "img/sample/s3-stencil.png", "img/sample/s4-stencil.png",
                               "img/sample/s5-stencil.png", "img/sample/s6-stencil.png",
                               "index.html", "lens.js"])
        self.assertEqual((out / "img/sample/s2-stencil.png").read_bytes(), b"PNG\x02")
        self.assertEqual((out / "lens.js").read_text(), "// lens\n")
        out = self.build(hunt(n=6, map=IMAGE))
        self.assertTrue((out / "img/sample/map.jpg").is_file())
        self.assertFalse((out / "img/sample/s1-stencil-preview.jpg").exists())
        self.assertFalse((out / "img/sample/unused-stencil.png").exists())

    def test_the_summary_line(self):
        self.build(hunt(map=BOUNDS, test_mode=True))
        self.assertIn("sample: 7 stencils, 3 located, 1 clues, 0 hints, map bounds, test mode on, leaderboard off", self.stdout)
        self.build(hunt(map=IMAGE), supabase=SUPABASE)
        self.assertIn("map image, test mode off, leaderboard on", self.stdout)
        self.build(hunt())
        self.assertIn("map none, test mode off, leaderboard off", self.stdout)

    def test_refuses_to_build_into_the_repository_or_above_it(self):
        for out in (self.repo, self.repo.parent, self.repo / "site" / ".."):
            with self.assertRaises(build.ContentError) as cm:
                self.build(hunt(), out=out)
            self.assertIn("is the repository itself, not a place to build into", str(cm.exception))
            self.assertTrue((self.app / "player.html").is_file())
        self.build(hunt(), out=self.repo / "site" / "sample")
        self.build(hunt(), out=self.tmp / "elsewhere")

    def test_only_the_hunts_own_directory_is_cleared(self):
        stale = self.site / "sample" / "stale.txt"
        keep = self.site / "other" / "keep.txt"
        for f in (stale, keep):
            f.parent.mkdir(parents=True)
            f.write_text("x")
        self.build(hunt())
        self.assertFalse(stale.exists())
        self.assertTrue(keep.exists())

    def test_a_missing_marker_is_an_error_naming_the_template(self):
        for marker in ("<title>Treasure Hunt</title>", "<!-- LEAFLET GOES HERE -->", "<!-- HUNT GOES HERE -->"):
            (self.app / "player.html").write_text(PLAYER.replace(marker, ""))
            with self.assertRaises(build.ContentError) as cm:
                self.build(hunt())
            self.assertEqual(str(cm.exception), f"app/player.html: no {marker} line to write over")


class Supabase(Sandbox):
    def test_content_supabase_json_is_baked_when_present(self):
        (self.content / "supabase.json").write_text(json.dumps(SUPABASE))
        self.assertEqual(build.load_supabase(), SUPABASE)
        page = self.page(hunt(), supabase=build.load_supabase())
        self.assertEqual(baked(page)[1], SUPABASE)

    def test_absent_config_bakes_null(self):
        self.assertIsNone(build.load_supabase())
        self.assertIn("window.SUPABASE = null;", self.page(hunt(), supabase=build.load_supabase()))

    def test_no_supabase_bakes_null_even_with_the_file(self):
        (self.content / "supabase.json").write_text(json.dumps(SUPABASE))
        self.assertIsNone(build.load_supabase(off=True))

    def test_supabase_path_overrides_the_default(self):
        (self.content / "supabase.json").write_text(json.dumps(SUPABASE))
        other = self.tmp / "other.json"
        other.write_text(json.dumps({"url": "https://other.supabase.co/", "anon_key": "k"}))
        self.assertEqual(build.load_supabase(other), {"url": "https://other.supabase.co", "anon_key": "k"})
        with self.assertRaises(FileNotFoundError):
            build.load_supabase(self.tmp / "nowhere.json")

    def test_config_shape_is_checked(self):
        path = self.tmp / "sb.json"
        for bad, why in (('["x"]', "must be an object"), ('{"url": "https://x"}', "no anon_key"),
                         ('{"anon_key": "k"}', "no url"), ('{"url": "", "anon_key": "k"}', "no url"),
                         ('{"url": "https://x", "anon_key": 3}', "no anon_key"),
                         ('{"url": "https://x", "anon_key": "k", "service_key": "s"}', "unknown key 'service_key'"),
                         ('{"url": ', "line 1:")):
            path.write_text(bad)
            with self.assertRaises(build.ContentError) as cm:
                build.load_supabase(path)
            self.assertIn(why, str(cm.exception))
            self.assertIn(str(path), str(cm.exception))


class Capture(Sandbox):
    def test_capture_page_bakes_the_config(self):
        out = self.site / "capture"
        quiet(build.build_capture, out, SUPABASE)
        page = (out / "index.html").read_text()
        self.assertIn('<script>window.SUPABASE = {"url": "https://example.supabase.co", "anon_key": "anon-key-123"};</script>', page)
        self.assertNotIn("SUPABASE GOES HERE", page)
        self.assertEqual([p.name for p in out.iterdir()], ["index.html"])

    def test_capture_page_bakes_null_without_config(self):
        out = self.site / "capture"
        quiet(build.build_capture, out, None)
        self.assertIn("<script>window.SUPABASE = null;</script>", (out / "index.html").read_text())

    def test_capture_marker_missing_is_an_error(self):
        (self.app / "capture.html").write_text("<html></html>")
        with self.assertRaises(build.ContentError) as cm:
            quiet(build.build_capture, self.site / "capture", None)
        self.assertEqual(str(cm.exception), "app/capture.html: no <!-- SUPABASE GOES HERE --> line to write over")

    def test_capture_refuses_the_repository(self):
        with self.assertRaises(build.ContentError):
            quiet(build.build_capture, self.repo, None)


class Index(Sandbox):
    def test_lists_the_hunts_by_name_as_links_in_the_order_given(self):
        a = self.write(hunt(id="sample", name="Sample Hunt"))
        b = self.write(hunt(id="fish-chips", name="Fish & Chips <3"), stem="fish-chips")
        out = self.site / "index.html"
        _, stdout, _ = quiet(build.build_index, out, [b, a])
        page = out.read_text()
        self.assertIn('<div class="wordmark">Treasure <span>Hunt</span></div>', page)
        self.assertIn('<li><a href="fish-chips/">Fish &amp; Chips &lt;3</a></li>\n    <li><a href="sample/">Sample Hunt</a></li>', page)
        self.assertEqual(page.count("<li>"), 2)
        self.assertNotIn("HUNTS GO HERE", page)
        self.assertIn('<a href="capture/">Capture</a>', page)
        self.assertIn("built", stdout)
        # The player's palette travels with it, all three theme states.
        self.assertIn("--accent: #9E2B25", page)
        self.assertIn('@media (prefers-color-scheme: dark)', page)
        self.assertIn(':root:not([data-theme="light"])', page)
        self.assertIn(':root[data-theme="dark"]', page)
        self.assertIn("Georgia", page)

    def test_index_validates_the_hunts(self):
        bad = self.write(hunt(name=""))
        with self.assertRaises(build.ContentError) as cm:
            quiet(build.build_index, self.site / "index.html", [bad])
        self.assertIn("hunt: name is ''", str(cm.exception))
        self.assertFalse((self.site / "index.html").exists())

    def test_index_leaves_the_hunts_built_beside_it_alone(self):
        out = self.build(hunt())
        quiet(build.build_index, self.site / "index.html", [self.write(hunt())])
        self.assertTrue((out / "index.html").is_file())
        self.assertTrue((self.site / "index.html").is_file())

    def test_index_with_no_hunts_is_the_wordmark_alone(self):
        out = self.site / "index.html"
        quiet(build.build_index, out, [])
        page = out.read_text()
        self.assertIn("Treasure <span>Hunt</span>", page)
        self.assertNotIn("<li>", page)

    def test_index_refuses_the_repository(self):
        with self.assertRaises(build.ContentError):
            quiet(build.build_index, self.repo / "index.html", [])


class Main(Sandbox):
    def main(self, *args):
        return quiet(build.main, list(args))

    def test_builds_a_hunt_with_the_default_config(self):
        (self.content / "supabase.json").write_text(json.dumps(SUPABASE))
        path = self.write(hunt(map=BOUNDS))
        code, stdout, stderr = self.main(path, str(self.site / "sample"))
        self.assertEqual((code, stderr), (0, ""))
        self.assertIn("leaderboard on", stdout)
        self.assertEqual(baked((self.site / "sample" / "index.html").read_text())[1], SUPABASE)

    def test_no_supabase_and_supabase_path(self):
        (self.content / "supabase.json").write_text(json.dumps(SUPABASE))
        path = self.write(hunt())
        code, _, _ = self.main(path, str(self.site / "sample"), "--no-supabase")
        self.assertEqual(code, 0)
        self.assertIsNone(baked((self.site / "sample" / "index.html").read_text())[1])
        other = self.tmp / "other.json"
        other.write_text(json.dumps({"url": "https://other.supabase.co", "anon_key": "k"}))
        code, _, _ = self.main("--supabase", str(other), path, str(self.site / "sample"))
        self.assertEqual(code, 0)
        self.assertEqual(baked((self.site / "sample" / "index.html").read_text())[1],
                         {"url": "https://other.supabase.co", "anon_key": "k"})
        code, _, stderr = self.main(path, str(self.site / "sample"), "--supabase", str(self.tmp / "nowhere.json"))
        self.assertEqual(code, 1)
        self.assertIn("missing file — ", stderr)

    def test_content_error_is_exit_1_with_the_message(self):
        h = hunt()
        h["stencils"][2]["src"] = "img/sample/gone.png"
        code, _, stderr = self.main(self.write(h), str(self.site / "sample"))
        self.assertEqual(code, 1)
        self.assertEqual(stderr.strip(), "content error — stencil 's3': src 'img/sample/gone.png' is not under app/")
        code, _, stderr = self.main(str(self.content / "nowhere.json"), str(self.site / "sample"))
        self.assertEqual(code, 1)
        self.assertIn("missing file — ", stderr)

    def test_usage_is_exit_2(self):
        path = self.write(hunt())
        for args in ((), (path,), (path, "a", "b"), ("--supabase",), (path, "a", "--supabase", "x", "--no-supabase"),
                     ("--index",), ("--capture",), ("--capture", "a", "b"), ("--index", "a", "--no-supabase"),
                     ("--wat", path, "a")):
            code, _, stderr = self.main(*args)
            self.assertEqual(code, 2, args)
            self.assertIn("usage:", stderr)

    def test_capture_and_index_modes(self):
        (self.content / "supabase.json").write_text(json.dumps(SUPABASE))
        code, _, _ = self.main("--capture", str(self.site / "capture"))
        self.assertEqual(code, 0)
        self.assertIn('"anon_key": "anon-key-123"', (self.site / "capture" / "index.html").read_text())
        code, _, _ = self.main("--capture", str(self.site / "capture"), "--no-supabase")
        self.assertEqual(code, 0)
        self.assertIn("window.SUPABASE = null;", (self.site / "capture" / "index.html").read_text())
        code, _, _ = self.main("--index", str(self.site / "index.html"), self.write(hunt()))
        self.assertEqual(code, 0)
        self.assertIn('<a href="sample/">Sample Hunt</a>', (self.site / "index.html").read_text())
        code, _, _ = self.main("--index", str(self.site / "index.html"))
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
