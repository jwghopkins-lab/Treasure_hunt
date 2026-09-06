#!/usr/bin/env python3
"""Validate a hunt and bake it into the player.

    python3 pipeline/build.py content/<slug>.json site/<slug> [--supabase PATH | --no-supabase]
    python3 pipeline/build.py --capture site/capture [--supabase PATH | --no-supabase]
    python3 pipeline/build.py --index site/index.html content/a.json content/b.json ...

The first builds one hunt's page with its stencils, its map image if it has
one, and Leaflet only if it has a map. The second builds the capture page the
owner takes the photographs with. The third writes the root page: the wordmark
and a link to each hunt, in the order given.

Standard library only, on purpose: the whole point of this game is that it is
a static page anybody can serve, so the thing that produces it should not need
an install either.

Validation fails loudly and names the stencil, because the person writing a
hunt has a phone full of photographs and a notebook, not a stack trace.
"""

import html
import json
import re
import shutil
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parent.parent
APP = BASE / "app"

# The lines in the templates that get written over. Each is matched whole, so
# re-indenting a template cannot silently stop the bake working and ship a
# player with no hunt in it, and a missing one is an error rather than a page
# with a hole where the hunt should be.
TITLE_MARKER = "<title>Treasure Hunt</title>"
LEAFLET_MARKER = "<!-- LEAFLET GOES HERE -->"
HUNT_MARKER = "<!-- HUNT GOES HERE -->"
SUPABASE_MARKER = "<!-- SUPABASE GOES HERE -->"

# What replaces the Leaflet marker on a page with a map. The paths are relative
# to the hunt's own directory, which is where vendor/leaflet is copied to.
LEAFLET_TAGS = ('<link rel="stylesheet" href="vendor/leaflet/leaflet.css">\n'
                '<script src="vendor/leaflet/leaflet.js"></script>')
LEAFLET_FILES = ("leaflet.js", "leaflet.css")

# A slug is a directory name on the site and a localStorage namespace on the
# phone, so it is kept to characters that are safe in both without escaping.
SLUG = re.compile(r"[a-z0-9-]+")

HUNT_KEYS = ("id", "name", "test_mode", "map", "stencils")
STENCIL_KEYS = ("id", "src", "clue", "location", "hint")
MAP_KEYS = ("bounds", "image")
LOCATION_KEYS = ("lat", "lon")
SUPABASE_KEYS = ("url", "anon_key")

# One sentence in a strip across the bottom of the camera screen. The captures
# table has the same limit, so a clue typed on the capture page always fits.
CLUE_MAX = 200

# The root page. The palette and the three theme states are the player's, so
# the list of hunts and the hunt itself look like one thing. The wordmark
# carries the accent on its second word, as the player's does.
INDEX_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>Treasure Hunt</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<style>
  /* Palette carried over from london-noticing. Portland stone for the ground,
     cast iron for the ink, the oxide red of Roman tile courses for the accent.

     Three theme states, not two. An explicit choice stamps data-theme on the
     root; the default setting stamps nothing and only prefers-color-scheme
     separates light from dark. So the bare :root carries the whole light
     palette, the media query redefines tokens for the unstamped dark case, and
     the [data-theme] blocks let a deliberate choice win in either direction.
     Every component reads tokens, never a literal, or it renders one theme's
     text on the other theme's ground. */
  :root {
    --paper: #ECEBE7; --panel: #FAFAF8; --ink: #191B1C; --ink-soft: #5C6163;
    --line: #CFCFC8; --accent: #9E2B25; --accent-soft: #F0DEDB;
    --accent-ink: #FFFFFF;
    --good: #2F6B4F; --good-soft: #DCE9E2;
    --warn: #9E2B25; --warn-soft: #F0DEDB;
    --key: #E0E0DA; --key-ink: #191B1C; --shadow: 0 1px 3px rgba(25,27,28,.13);
  }
  @media (prefers-color-scheme: dark) {
    :root:not([data-theme="light"]) {
      --paper: #141617; --panel: #1D2022; --ink: #E8E7E3; --ink-soft: #9AA0A2;
      --line: #363B3D; --accent: #E08078; --accent-soft: #3A2220;
      --accent-ink: #141617;
      --good: #6FBF97; --good-soft: #1E3229;
      --warn: #E08078; --warn-soft: #3A2220;
      --key: #2A2E30; --key-ink: #E8E7E3; --shadow: 0 1px 3px rgba(0,0,0,.45);
    }
  }
  :root[data-theme="dark"] {
    --paper: #141617; --panel: #1D2022; --ink: #E8E7E3; --ink-soft: #9AA0A2;
    --line: #363B3D; --accent: #E08078; --accent-soft: #3A2220;
    --accent-ink: #141617;
    --good: #6FBF97; --good-soft: #1E3229;
    --warn: #E08078; --warn-soft: #3A2220;
    --key: #2A2E30; --key-ink: #E8E7E3; --shadow: 0 1px 3px rgba(0,0,0,.45);
  }
  * { box-sizing: border-box; margin: 0; padding: 0; -webkit-tap-highlight-color: transparent; }
  html, body { height: 100%; }
  body { background: var(--paper); color: var(--ink);
         font-family: system-ui, -apple-system, "Segoe UI", sans-serif;
         display: flex; flex-direction: column; align-items: center; }
  main { width: 100%; max-width: 560px;
         padding: 8px 12px calc(20px + env(safe-area-inset-bottom)); }
  header { display: flex; align-items: center; gap: 10px; padding: 6px 2px; }
  .wordmark { font-family: Georgia, "Times New Roman", serif; font-weight: 700;
              font-size: 1.15rem; letter-spacing: .08em; line-height: 1.2; }
  .wordmark span { color: var(--accent); }
  ul { list-style: none; margin-top: 12px; }
  li + li { margin-top: 8px; }
  /* Each hunt is one wide tap, 16px so iOS never auto-zooms into it. */
  li a { display: block; padding: 14px 16px; font-size: 1rem; color: var(--ink);
         text-decoration: none; background: var(--panel); border: 1px solid var(--line);
         border-radius: 12px; box-shadow: var(--shadow); }
  /* The owner's way in to the capture page: small, at the foot, one word. */
  .foot { margin-top: 32px; text-align: center; font-size: .8rem; }
  .foot a { color: var(--ink-soft); text-decoration: none; padding: 10px 14px;
            display: inline-block; }
</style>
</head>
<body>
<main>
  <header><div class="wordmark">Treasure <span>Hunt</span></div></header>
  <ul>
<!-- HUNTS GO HERE -->
  </ul>
  <p class="foot"><a href="capture/">Capture</a></p>
</main>
</body>
</html>
"""
INDEX_MARKER = "<!-- HUNTS GO HERE -->"

USAGE = """usage: python3 pipeline/build.py content/<slug>.json site/<slug> [--supabase PATH | --no-supabase]
       python3 pipeline/build.py --capture site/capture [--supabase PATH | --no-supabase]
       python3 pipeline/build.py --index site/index.html content/<a>.json content/<b>.json ..."""


class ContentError(Exception):
    """A hunt that will not play. The message says which stencil and why."""


def fail(where, why):
    raise ContentError(f"{where}: {why}")


def is_num(v):
    return isinstance(v, (int, float)) and not isinstance(v, bool)


def check_slug(value, where, what):
    if not isinstance(value, str) or not SLUG.fullmatch(value):
        fail(where, f"{what} {value!r} must be lower-case letters, digits and hyphens")
    # The completions and captures tables check the hunt's name at 40.
    if len(value) > 40:
        fail(where, f"{what} {value!r} is longer than 40 characters")


def check_keys(obj, allowed, where):
    """Unknown keys are an error rather than carried through, because a typo
    like "clues" would otherwise be a stencil that silently shows no clue."""
    for key in obj:
        if key not in allowed:
            fail(where, f"unknown key {key!r} ({', '.join(allowed)})")


def check_app_file(src, where, what):
    """A path in the hunt file names a file under app/ and is copied to the
    same path in the site. Anything absolute or climbing out is refused before
    is_file() gets to say yes to a file that is not ours to ship."""
    if not isinstance(src, str) or not src:
        fail(where, f"no {what}" if src in (None, "") else f"{what} must be a path under app/")
    if Path(src).is_absolute() or ".." in Path(src).parts:
        fail(where, f"{what} {src!r} must be a path under app/, not absolute and not climbing out")
    if not (APP / src).is_file():
        fail(where, f"{what} {src!r} is not under app/")


def check_location(loc, where):
    at = f"{where}.location"
    if not isinstance(loc, dict):
        fail(at, "must be an object with lat and lon")
    check_keys(loc, LOCATION_KEYS, at)
    for field in LOCATION_KEYS:
        if field not in loc:
            fail(at, f"no {field}")
        if not is_num(loc[field]):
            fail(at, f"{field} is {loc[field]!r}, must be a number")
    if not -90 <= loc["lat"] <= 90 or not -180 <= loc["lon"] <= 180:
        fail(at, "lat/lon are not on the Earth")


def check_stencil(s, n, seen, images):
    """One stencil. Appends its src to images so the build copies it."""
    where = f"stencil #{n + 1}"
    if not isinstance(s, dict):
        fail(where, "must be an object")
    sid = s.get("id")
    if isinstance(sid, str) and sid:
        where = f"stencil {sid!r}"
    check_keys(s, STENCIL_KEYS, where)
    if "id" not in s:
        fail(where, "no id")
    check_slug(sid, where, "id")
    if sid in seen:
        fail(where, "duplicate id")
    seen.add(sid)

    check_app_file(s.get("src"), where, "src")
    images.append(s["src"])
    # The denser stencil the hint button shows, drawn under the real one on
    # the camera screen; the scorer never reads it.
    if "hint" in s:
        check_app_file(s["hint"], where, "hint")
        images.append(s["hint"])

    if "clue" in s:
        clue = s["clue"]
        if not isinstance(clue, str) or not clue.strip():
            fail(where, f"clue is {clue!r}, must be a sentence of text")
        if len(clue) > CLUE_MAX:
            fail(where, f"clue is {len(clue)} characters, at most {CLUE_MAX}")
    if "location" in s:
        check_location(s["location"], where)


def check_bounds(bounds, stencils):
    """The corners of a street map, and that every located stencil is inside
    them: a marker off the edge of the map is a stencil the player cannot be
    shown the way to."""
    where = "hunt.map.bounds"
    pairs = (isinstance(bounds, list) and len(bounds) == 2
             and all(isinstance(p, list) and len(p) == 2 and all(is_num(v) for v in p)
                     for p in bounds))
    if not pairs:
        fail(where, "must be two [lat, lon] pairs, [[south, west], [north, east]]")
    (south, west), (north, east) = bounds
    if not all(-90 <= v <= 90 for v in (south, north)) or not all(-180 <= v <= 180 for v in (west, east)):
        fail(where, "corners are not on the Earth")
    if not south < north:
        fail(where, f"south {south} must be below north {north}")
    if not west < east:
        fail(where, f"west {west} must be below east {east}")
    located = [s for s in stencils if "location" in s]
    if not located:
        fail(where, "there is a street map but no stencil has a location to put on it")
    for s in located:
        lat, lon = s["location"]["lat"], s["location"]["lon"]
        if not (south <= lat <= north and west <= lon <= east):
            fail(f"stencil {s['id']!r}", f"location {lat}, {lon} is outside the map bounds")


def check_map(m, stencils, images):
    """One of two shapes: bounds for a street map, image for a hand-made one."""
    where = "hunt.map"
    if not isinstance(m, dict):
        fail(where, "must be an object with bounds or image")
    check_keys(m, MAP_KEYS, where)
    if ("bounds" in m) == ("image" in m):
        fail(where, "must have exactly one of bounds or image")
    if "image" in m:
        check_app_file(m["image"], where, "image")
        images.append(m["image"])
    else:
        check_bounds(m["bounds"], stencils)


def validate(hunt, stem=None):
    """Check the whole hunt, fill in the defaults, and return the image srcs it
    referenced: the stencils and the map image if there is one.

    stem is the content file's name without .json, when the hunt came from a
    file. The id has to equal it because the workflow publishes each file at
    /<stem>/ while the page stores its state under the id, and the two being
    different would be a hunt at one address remembering itself under another."""
    if not isinstance(hunt, dict):
        fail("hunt", "must be an object")
    check_keys(hunt, HUNT_KEYS, "hunt")
    if "id" not in hunt:
        fail("hunt", "no id")
    check_slug(hunt["id"], "hunt", "id")
    if stem is not None and hunt["id"] != stem:
        fail("hunt", f"id {hunt['id']!r} does not match the file name {stem!r}, "
                     f"and the page is published at /{stem}/")
    if "name" not in hunt:
        fail("hunt", "no name")
    if not isinstance(hunt["name"], str) or not hunt["name"].strip():
        fail("hunt", f"name is {hunt['name']!r}, must be text")
    # One flag for every player-facing testing affordance: the Skip on the
    # camera screen and the haptic report in the menu. One edit turns them all
    # off before anybody plays for real.
    test_mode = hunt.setdefault("test_mode", False)
    if not isinstance(test_mode, bool):
        fail("hunt", f"test_mode is {test_mode!r}, must be true or false")
    if "stencils" not in hunt:
        fail("hunt", "no stencils")
    stencils = hunt["stencils"]
    if not isinstance(stencils, list):
        fail("hunt", "stencils must be a list")

    images, seen = [], set()
    for n, s in enumerate(stencils):
        check_stencil(s, n, seen, images)
    # Six to nine is the game as designed, but a hunt being tried out with
    # fewer is not broken, so this is said and not enforced.
    if not 6 <= len(stencils) <= 9:
        print(f"warning — hunt {hunt['id']!r}: {len(stencils)} stencils, a hunt has six to nine",
              file=sys.stderr)
    if "map" in hunt:
        check_map(hunt["map"], stencils, images)
    return images


def load(content_path):
    path = Path(content_path)
    text = path.read_text(encoding="utf-8")
    try:
        return json.loads(text)
    except json.JSONDecodeError as err:
        fail(str(path), f"line {err.lineno}: {err.msg}")


def load_supabase(path=None, off=False):
    """The leaderboard's address and public key, or None, which bakes null and
    turns off the leaderboard, the name screen and the capture page's upload.
    The default is content/supabase.json, and its absence is not an error: the
    file is written when the project is created, and the site builds before."""
    if off:
        return None
    given = path is not None
    path = Path(path) if given else BASE / "content" / "supabase.json"
    if not given and not path.is_file():
        return None
    text = path.read_text(encoding="utf-8")
    try:
        cfg = json.loads(text)
    except json.JSONDecodeError as err:
        fail(str(path), f"line {err.lineno}: {err.msg}")
    where = str(path)
    if not isinstance(cfg, dict):
        fail(where, "must be an object with url and anon_key")
    check_keys(cfg, SUPABASE_KEYS, where)
    for field in SUPABASE_KEYS:
        if not isinstance(cfg.get(field), str) or not cfg[field].strip():
            fail(where, f"no {field}")
    # The page appends /rest/v1/... to the url, so a trailing slash would put
    # two in the path.
    return {"url": cfg["url"].rstrip("/"), "anon_key": cfg["anon_key"]}


def script_json(value):
    """JSON to sit inside a <script>. Escaping "</" is the whole of the safety
    here: a hunt containing the characters that end a script tag would
    otherwise close this one early and spill the rest of the JSON into the
    page as markup."""
    return json.dumps(value, ensure_ascii=False).replace("</", "<\\/")


def require_marker(template, marker, where):
    if marker not in template:
        fail(where, f"no {marker} line to write over")


def bake(template, hunt, supabase):
    """The player page for one validated hunt."""
    where = "app/player.html"
    for marker in (TITLE_MARKER, LEAFLET_MARKER, HUNT_MARKER):
        require_marker(template, marker, where)
    page = template.replace(TITLE_MARKER, f"<title>{html.escape(hunt['name'])}</title>", 1)
    # Leaflet goes with a map of either kind: the street map draws tiles with
    # it and the hand-made one is an imageOverlay in CRS.Simple, which is
    # Leaflet too. A hunt with no map does not load a library it never uses.
    page = page.replace(LEAFLET_MARKER, LEAFLET_TAGS if "map" in hunt else "", 1)
    page = page.replace(HUNT_MARKER,
                        f"<script>window.HUNT = {script_json(hunt)}; "
                        f"window.SUPABASE = {script_json(supabase)};</script>", 1)
    return page


def refuse_repo(path):
    """Building into the repository or above it would clear it."""
    here, root = Path(path).resolve(), BASE.resolve()
    if here == root or here in root.parents:
        fail("output", f"{path} is the repository itself, not a place to build into")


def output_dir(out_dir):
    """The directory a page is built into, emptied first so a stencil dropped
    from a hunt does not linger on the site. Only this one directory is
    cleared, so a hunt can be built into a corner of the real site without
    flattening the rest of it."""
    out = Path(out_dir)
    refuse_repo(out)
    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    return out


def copy_leaflet(out):
    src, dest = APP / "vendor" / "leaflet", out / "vendor" / "leaflet"
    for name in LEAFLET_FILES:
        if not (src / name).is_file():
            fail("app/vendor/leaflet", f"{name} is not vendored")
    if not (src / "images").is_dir():
        fail("app/vendor/leaflet", "images/ is not vendored")
    (dest / "images").mkdir(parents=True)
    for name in LEAFLET_FILES:
        shutil.copy2(src / name, dest / name)
    for f in sorted((src / "images").iterdir()):
        if f.is_file():
            shutil.copy2(f, dest / "images" / f.name)


def build(content_path, out_dir, supabase=None):
    hunt = load(content_path)
    images = validate(hunt, Path(content_path).stem)
    template = (APP / "player.html").read_text(encoding="utf-8")
    page = bake(template, hunt, supabase)

    out = output_dir(out_dir)
    (out / "index.html").write_text(page, encoding="utf-8")
    shutil.copy2(APP / "lens.js", out / "lens.js")
    # Only the images the hunt refers to. app/img/ also holds the other hunts'
    # stencils and the previews that are documentation, not content, and none
    # of that belongs on a page handed to a player.
    for src in sorted(set(images)):
        dest = out / src
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(APP / src, dest)
    if "map" in hunt:
        copy_leaflet(out)

    stencils = hunt["stencils"]
    print(f"built {out / 'index.html'} from {content_path}")
    print(f"  {hunt['id']}: {len(stencils)} stencils, "
          f"{sum(1 for s in stencils if 'location' in s)} located, "
          f"{sum(1 for s in stencils if 'clue' in s)} clues, "
          f"{sum(1 for s in stencils if 'hint' in s)} hints, "
          f"map {'bounds' if 'bounds' in hunt.get('map', {}) else 'image' if 'map' in hunt else 'none'}, "
          f"test mode {'on' if hunt['test_mode'] else 'off'}, "
          f"leaderboard {'on' if supabase else 'off'}")


def build_capture(out_dir, supabase=None):
    """The page the owner takes the photographs with. Just the one file: it
    carries its own camera code, so nothing else is copied beside it."""
    template = (APP / "capture.html").read_text(encoding="utf-8")
    require_marker(template, SUPABASE_MARKER, "app/capture.html")
    page = template.replace(SUPABASE_MARKER,
                            f"<script>window.SUPABASE = {script_json(supabase)};</script>", 1)
    out = output_dir(out_dir)
    (out / "index.html").write_text(page, encoding="utf-8")
    print(f"built {out / 'index.html'} from app/capture.html, "
          f"upload {'on' if supabase else 'off, the shutter downloads instead'}")


def build_index(out_path, content_paths):
    """The root page: one link per hunt, by name, in the order given. Each hunt
    is loaded and validated to get its name, so a broken hunt stops the whole
    publish here as it would in its own build. Only this one file is written;
    the hunts already built beside it are left alone."""
    hunts = []
    for content_path in content_paths:
        hunt = load(content_path)
        validate(hunt, Path(content_path).stem)
        hunts.append(hunt)
    links = "\n".join(f'    <li><a href="{html.escape(h["id"])}/">{html.escape(h["name"])}</a></li>'
                      for h in hunts)
    page = INDEX_PAGE.replace(INDEX_MARKER, links, 1)

    out = Path(out_path)
    refuse_repo(out.parent)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(page, encoding="utf-8")
    print(f"built {out} with {len(hunts)} hunts"
          + (": " + ", ".join(h["id"] for h in hunts) if hunts else ""))


def usage():
    print(USAGE, file=sys.stderr)
    return 2


def main(argv=None):
    args = list(sys.argv[1:] if argv is None else argv)
    supabase_path, no_supabase, rest = None, False, []
    while args:
        arg = args.pop(0)
        if arg == "--no-supabase":
            no_supabase = True
        elif arg == "--supabase":
            if not args:
                return usage()
            supabase_path = args.pop(0)
        else:
            rest.append(arg)
    if supabase_path is not None and no_supabase:
        return usage()
    mode = rest[0] if rest and rest[0].startswith("--") else None
    try:
        if mode == "--index":
            # The root page carries no Supabase config, so a flag here would
            # do nothing, and a flag that does nothing is a misunderstanding.
            if len(rest) < 2 or supabase_path is not None or no_supabase:
                return usage()
            build_index(rest[1], rest[2:])
        elif mode == "--capture":
            if len(rest) != 2:
                return usage()
            build_capture(rest[1], load_supabase(supabase_path, no_supabase))
        elif mode is None and len(rest) == 2:
            build(rest[0], rest[1], load_supabase(supabase_path, no_supabase))
        else:
            return usage()
    except ContentError as err:
        print(f"content error — {err}", file=sys.stderr)
        return 1
    except FileNotFoundError as err:
        print(f"missing file — {err}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
