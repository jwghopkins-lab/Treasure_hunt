#!/usr/bin/env python3
"""A hunt from the photographs the capture page took.

    python3 pipeline/from_captures.py --slug snowman2 --name "Snowman House"
        --manifest manifest.json --base https://<project>.supabase.co

The capture page puts each photograph in the `captures` bucket and writes a
row saying where it came from. This takes those rows, in the order the
stencils should appear, fetches each photograph to photos/<slug>/<id>.jpg,
cuts its stencil with pipeline/stencil.py, and writes content/<slug>.json:
the clues as they were typed, a location for every fix worth trusting, and
the map's corners round them. What comes out is a hunt the build takes, or
nothing at all.

The manifest is what

    select path, clue, lat, lon, accuracy from captures
        where hunt = '<slug>' order by taken_at

gives, with an id chosen for each row:

    [{"id": "front-door",
      "path": "snowman2/1788730518182-b16f6425d77404b1.jpg",
      "clue": "Where the milk is left.",
      "lat": 51.47, "lon": -0.1, "accuracy": 12.3}]

Only `id` and `path` are required. The id names the photograph, the stencil
and the tile, so it is the one thing a person chooses here; the rest is the
row as the capture page wrote it, with a bad shot dropped and a clue or a
location corrected by hand where the owner wants it.

The fetch carries no key: the bucket is public to read and the path carries
sixteen random hex characters, which is the whole of what stands between a
stranger and the answers. `--base` may also be a directory of photographs or
a file:// URL, and then the fetch is a copy, so a run with no network is the
same run.

Pillow, through stencil.py, is the only thing here that is not the standard
library.
"""

import argparse
import http.client
import json
import math
import sys
import urllib.parse
import urllib.request
from pathlib import Path
from urllib.request import url2pathname

sys.path.insert(0, str(Path(__file__).resolve().parent))

import build      # noqa: E402  the validation the site build does, run on what this writes
import stencil    # noqa: E402  the recipe, not repeated here

BASE = Path(__file__).resolve().parent.parent

# A fix worse than this is no information: the player's distance line ignores
# one, so a location made from one would put a marker where the photograph
# was not taken.
ACC_USELESS_M = 75

# About 150 m of latitude. A degree of longitude is shorter than a degree of
# latitude by the cosine of where you are, so the margin east and west is
# divided by it and the box is 150 m on every side rather than 150 m north
# and ninety-odd east.
MARGIN_DEG = 0.00135
PLACES = 4
STEP = 10 ** -PLACES

MANIFEST_KEYS = ("id", "path", "clue", "lat", "lon", "accuracy")

# A JPEG starts with the start-of-image marker. Storage answers a wrong path
# with JSON, not a picture, and a JSON file handed to Pillow is a stack trace
# three steps later.
SOI = b"\xff\xd8\xff"


def refuse(why):
    """Nothing can be made of what was given, and nothing has been fetched or
    written. The message names the row, because the person holding it has a
    phone full of photographs and a list of paths."""
    print(f"refused — {why}", file=sys.stderr)
    raise SystemExit(2)


def stop(kind, why):
    print(f"{kind} error — {why}", file=sys.stderr)
    raise SystemExit(1)


def warn(why):
    print(f"warning — {why}", file=sys.stderr)


def read_manifest(path):
    """The rows, checked, in the order the stencils will appear. Everything
    that would make a hunt the build refuses is refused here, before a single
    photograph is fetched, so a mistyped manifest costs nothing."""
    path = Path(path)
    if not path.is_file():
        refuse(f"{path}: no such file")
    try:
        rows = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as err:
        refuse(f"{path}: line {err.lineno}: {err.msg}")
    if not isinstance(rows, list) or not all(isinstance(r, dict) for r in rows):
        refuse("the manifest must be a list of objects, one per photograph, "
               "in the order the stencils should appear")
    if not rows:
        refuse("the manifest is empty")
    seen = set()
    for n, row in enumerate(rows, 1):
        where = f"row {n}"
        rid = row.get("id")
        if not isinstance(rid, str) or not build.SLUG.fullmatch(rid):
            refuse(f"{where}: id {rid!r} must be lower-case letters, digits and hyphens")
        if len(rid) > 40:
            refuse(f"{where}: id {rid!r} is longer than 40 characters")
        if rid in seen:
            refuse(f"{where}: duplicate id {rid!r}; one id names one photograph, "
                   "one stencil and one tile")
        seen.add(rid)
        where = f"row {n} ({rid})"
        # An unknown key is said and passed over rather than refused: the rows
        # come from a select, and a session that brings taken_at along with
        # them has not made a mistake worth stopping for.
        for key in row:
            if key not in MANIFEST_KEYS:
                warn(f"{where}: ignoring {key!r} ({', '.join(MANIFEST_KEYS)})")
        obj = row.get("path")
        if not isinstance(obj, str) or not obj:
            refuse(f"{where}: no path; it is the object's path in the bucket, "
                   "as the captures row has it")
        if obj.startswith("/") or ".." in Path(obj).parts:
            refuse(f"{where}: path {obj!r} must be inside the bucket, "
                   "not absolute and not climbing out")
        if "clue" in row and row["clue"] is not None and not isinstance(row["clue"], str):
            refuse(f"{where}: clue is {row['clue']!r}, must be a sentence of text")
        for field in ("lat", "lon", "accuracy"):
            if field in row and row[field] is not None and not build.is_num(row[field]):
                refuse(f"{where}: {field} is {row[field]!r}, must be a number")
    # Six to nine is the game as designed, and a hunt being tried out with
    # fewer is not broken, so this is said and not enforced, as the build says
    # it too.
    if not 6 <= len(rows) <= 9:
        warn(f"{len(rows)} photographs, a hunt has six to nine")
    return rows


def photo_source(base):
    """The directory --base names, when it names one: a plain path, or a
    file:// URL. None means a web address. On disk the path in the row is the
    path on disk, because storage/v1/object/public belongs to the storage
    API and to nothing else."""
    if base.startswith("file://"):
        return Path(url2pathname(urllib.parse.urlsplit(base).path))
    if "://" in base:
        return None
    return Path(base)


def fetch(base, bucket, row, dest):
    """One photograph to photos/<slug>/<id>.jpg. The bytes are read whole and
    checked before anything is written, so a refusal, an error page or a cut
    connection leaves no half a photograph behind for the stencil tool to
    read as if it were the shot."""
    sid, obj = row["id"], row["path"]
    local = photo_source(base)
    if local is not None:
        where = str(local / obj)
        try:
            data = (local / obj).read_bytes()
        except OSError as err:
            stop("fetch", f"{sid}: {where}: {err.strerror or err}")
    else:
        where = (f"{base.rstrip('/')}/storage/v1/object/public/"
                 f"{bucket}/{urllib.parse.quote(obj)}")
        # A body that stops short of its length raises an HTTPException and
        # not an OSError, and a download cut halfway through should name the
        # photograph like every other failure here, not Python.
        try:
            with urllib.request.urlopen(where, timeout=60) as answer:
                data = answer.read()
        except (OSError, http.client.HTTPException) as err:
            stop("fetch", f"{sid}: {where}: {err}")
    if not data.startswith(SOI):
        stop("fetch", f"{sid}: {where} is not a JPEG "
                      f"(it starts {data[:8]!r}, {len(data)} bytes)")
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.with_name(dest.name + ".part")
    part.write_bytes(data)
    part.replace(dest)
    print(f"fetched {dest} ({len(data) // 1024} kB)", file=sys.stderr)
    return dest


def location_of(row, allow):
    """Where the photograph was taken, when it is worth putting on the map.
    A coordinate typed by hand carries no accuracy at all, so only a number
    can rule a fix out; nothing said is nothing against it, which is how the
    player's own distance line reads a fix as well."""
    if not allow:
        return None
    lat, lon = row.get("lat"), row.get("lon")
    if not (build.is_num(lat) and build.is_num(lon)):
        return None
    acc = row.get("accuracy")
    if build.is_num(acc):
        if acc > ACC_USELESS_M:
            warn(f"{row['id']}: the fix is {acc:g} m wide, worse than {ACC_USELESS_M} m, "
                 "so the stencil has no location")
            return None
    else:
        # The capture page never writes a position without its accuracy, so a
        # fix with none is a coordinate someone typed, or a select that left
        # the column out. It is taken as given and said aloud, because the
        # second looks exactly like the first.
        warn(f"{row['id']}: the location came with no accuracy, so it is taken as given")
    return {"lat": lat, "lon": lon}


def widen(lo, hi, margin):
    """One axis of the map's box: the locations with the margin outside them,
    rounded to four places. Rounding can pull an edge back onto a location,
    and a marker on the edge of the map is a marker half off it, so an edge
    that lands on one takes one more step out."""
    low = round(lo - margin, PLACES)
    high = round(hi + margin, PLACES)
    if low >= lo:
        low = round(low - STEP, PLACES)
    if high <= hi:
        high = round(high + STEP, PLACES)
    return low, high


def map_bounds(located):
    """The smallest box round the locations, widened by about 150 m on each
    side, which is what the map opens on."""
    lats = [p["lat"] for p in located]
    lons = [p["lon"] for p in located]
    middle = (min(lats) + max(lats)) / 2
    # The cosine is held off zero so a hunt at the pole widens rather than
    # divides by nothing.
    east_west = MARGIN_DEG / max(0.01, math.cos(math.radians(middle)))
    south, north = widen(min(lats), max(lats), MARGIN_DEG)
    west, east = widen(min(lons), max(lons), east_west)
    return [[south, west], [north, east]]


def write(path, hunt):
    """The hunt file, pretty-printed as the others are, and only once the
    build has agreed to it: it is written beside the real one, read back,
    validated under the name it is being written as, and moved into place. So
    the build never finds a hunt this tool wrote that it refuses, and a
    failure leaves the ground as it was."""
    path.parent.mkdir(parents=True, exist_ok=True)
    part = path.with_name(path.name + ".part")
    part.write_text(json.dumps(hunt, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    try:
        build.validate(json.loads(part.read_text(encoding="utf-8")), path.stem)
    except build.ContentError as err:
        part.unlink(missing_ok=True)
        stop("content", f"{err}; {path} was not written")
    part.replace(path)


def default_base():
    """The project the capture page uploaded to, taken from the config the
    pages already bake, so the URL is written down once."""
    try:
        cfg = build.load_supabase()
    except build.ContentError as err:
        refuse(f"content/supabase.json — {err}")
    if not cfg:
        refuse("no --base, and no content/supabase.json to take the project's URL from")
    return cfg["url"]


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="Make a hunt from the photographs the capture page took.")
    ap.add_argument("--slug", required=True,
                    help="the hunt's slug, which is the directory the photographs went to")
    ap.add_argument("--name", required=True, help="the hunt's name, as the title bar shows it")
    ap.add_argument("--manifest", required=True, type=Path,
                    help="the rows as JSON, in the order the stencils should appear")
    ap.add_argument("--base", default=None,
                    help="the project's URL, a file:// URL, or a directory of photographs "
                         "(default: the url in content/supabase.json)")
    ap.add_argument("--bucket", default="captures", help="the storage bucket (default captures)")
    ap.add_argument("--photos", type=Path, default=None,
                    help="where the photographs are saved (default photos/<slug>)")
    ap.add_argument("--out", type=Path, default=None,
                    help="where the stencils are written (default app/img/<slug>)")
    ap.add_argument("--content", type=Path, default=None,
                    help="the hunt file to write (default content/<slug>.json)")
    ap.add_argument("--no-locations", action="store_true",
                    help="leave every location out, and the map with them")
    ap.add_argument("--keep", type=float, default=stencil.KEEP,
                    help=f"fraction of each frame's interior to keep (default {stencil.KEEP})")
    ap.add_argument("--speck", type=int, default=None,
                    help="drop blobs with fewer pixels than this (chosen per photo if left out)")
    ap.add_argument("--long", type=int, default=800,
                    help="resize so the long side is this many px (default 800)")
    args = ap.parse_args(argv)
    # The recipe's own guards, because this is the other door to it and a
    # --keep of 6 for 0.6 would otherwise index off the end of a quantile.
    if not 0 < args.keep <= 1:
        ap.error("--keep must be above 0 and at most 1")
    if args.speck is not None and args.speck < 0:
        ap.error("--speck must not be negative")
    if args.long < 5:
        ap.error("--long must be at least 5, so the frame has an interior")

    slug = args.slug
    if not build.SLUG.fullmatch(slug) or len(slug) > 40:
        refuse(f"slug {slug!r} must be lower-case letters, digits and hyphens, "
               "at most 40 characters")
    base = args.base if args.base is not None else default_base()
    photos = args.photos if args.photos is not None else BASE / "photos" / slug
    out = args.out if args.out is not None else BASE / "app" / "img" / slug
    content = args.content if args.content is not None else BASE / "content" / f"{slug}.json"
    # The page is published at /<the file's name>/ and stores its state under
    # the hunt's id, so the build refuses a hunt whose id is not its file's
    # name. Refuse it here too, before a photograph is fetched for a file
    # nothing would take.
    if content.stem != slug:
        refuse(f"--content {content} names the hunt {content.stem!r} while --slug says "
               f"{slug!r}, and the build takes a hunt only under its own id")
    rows = read_manifest(args.manifest)

    stencils, located, clues = [], [], 0
    for row in rows:
        photo = fetch(base, args.bucket, row, photos / f"{row['id']}.jpg")
        entry = stencil.make(photo, out, args.keep, args.speck, args.long)
        s = {"id": entry["id"], "src": entry["src"]}
        clue = (row.get("clue") or "").strip()
        if clue:
            s["clue"] = clue
            clues += 1
        where = location_of(row, not args.no_locations)
        if where:
            s["location"] = where
            located.append(where)
        if entry.get("hint"):
            s["hint"] = entry["hint"]
        stencils.append(s)

    hunt = {"id": slug, "name": args.name, "test_mode": False}
    if located:
        hunt["map"] = {"bounds": map_bounds(located)}
    hunt["stencils"] = stencils
    write(content, hunt)

    print(f"wrote {content}", file=sys.stderr)
    print(f"{slug}: {len(stencils)} stencils, {len(located)} located, "
          f"{clues} with a clue — {', '.join(s['id'] for s in stencils)}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
