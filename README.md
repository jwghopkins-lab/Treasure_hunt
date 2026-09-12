# Treasure Hunt

A game played on a phone, outdoors, against a set of stencils. One static
page per hunt on GitHub Pages; the only thing that is not static is the
leaderboard, on Supabase, so every phone can see every finishing time.

A hunt has a name and six to nine stencils, each cut from a photograph the
owner took standing somewhere. The player sees the stencils as thumbnails,
picks one, and the camera opens with that stencil fixed over the live view.
To pass it the player has to stand where the photograph was taken and point
the phone the same way, until the live edges agree with the stencil for long
enough. A passed stencil gets a green tick. When every one is passed the page
says Congratulations and the clock stops.

The engine is taken from `jwghopkins-lab/architect-order`: the camera
lifecycle and the whole match scorer, the tick, the palette, the geography,
and the shape of the build and the Pages workflow. Everything of that game's
narrative, gates, questions and gestures was left behind.

## Layout

    content/<slug>.json          the hunts
    content/supabase.json        the Supabase URL and anon key, when the project exists
    app/player.html              the game page, with the marker lines the build writes over
    app/lens.js                  the camera screen and the scorer
    app/capture.html             the page the owner takes the photographs with
    app/img/<slug>/              the stencils, and a hand-made map if there is one
    app/vendor/leaflet/          Leaflet 1.9.4, the one dependency, vendored
    photos/<slug>/               the photographs; gitignored, except the fixture's
    pipeline/stencil.py          photograph -> stencil (needs Pillow)
    pipeline/audit.py            the stencils scored against their photographs (needs Pillow)
    pipeline/from_captures.py    the capture rows -> photographs, stencils and a hunt file
    pipeline/sheet.py            a contact sheet of a hunt's stencils on their photographs
    pipeline/build.py            validate a hunt and bake it (standard library only)
    supabase/schema.sql          the tables, policies and bucket, as applied
    tests/                       the Playwright suites, the y4m tool, the python tests
    site/                        build output, gitignored

## Build

    python3 pipeline/build.py content/trafalgar.json site/trafalgar
    python3 pipeline/build.py --capture site/capture
    python3 pipeline/build.py --index site/index.html content/*.json

One page per hunt at `/<slug>/`, the capture page at `/capture/`, and a root
index that is the wordmark and the hunts by name. The build validates the
hunt and exits non-zero naming the stencil if anything is wrong; it copies
only the stencils the hunt refers to, the map image if there is one, and
Leaflet only for a hunt with a map. `--supabase PATH` uses another config
file and `--no-supabase` bakes none: without a config the page has no name
screen, no board and makes no request, and the capture page downloads the
photograph to the phone instead of uploading it.

Pushing to `main` runs the workflow: the python tests, a build of every hunt
in `content/`, the deploy, and a curl of each deployed URL.

## Making a hunt

Take six to nine photographs with the capture page, in portrait, on a phone
like the ones that will play, with the hunt's slug typed once and a clue
where one is wanted. Then, in a session with the Supabase connector:

    select path, clue, lat, lon, accuracy from captures
        where hunt = '<slug>' order by taken_at

Read the rows back to the owner, so a bad shot can be dropped and a clue or a
position corrected, and give each one an id: that is the manifest, a JSON
list in the order the stencils should appear.

    [{"id": "front-door",
      "path": "snowman2/1788730518182-b16f6425d77404b1.jpg",
      "clue": "Where the milk is left.",
      "lat": 51.47, "lon": -0.1, "accuracy": 12.3}]

Only `id` and `path` are required; the id names the photograph, the stencil
and the tile. Then dispatch the hunt workflow with it:

    gh workflow run hunt.yml --ref main -f slug=<slug> -f name="<Hunt Name>" \
        -f manifest="$(cat manifest.json)" -f locations=true
    gh workflow run pages.yml --ref main

The runner fetches each photograph from the bucket to `photos/<slug>/<id>.jpg`,
cuts its stencil with the recipe below, writes `content/<slug>.json` with the
clues as they were typed and, with `locations=true`, a location for every fix
at most 75 m wide (a coordinate typed into the manifest by hand has no
accuracy to be judged by, and is taken as it is) and the map's corners round
them; then it runs the python tests and the fake-camera pass of every new
stencil against its own photograph, and commits the stencils and the hunt
file, and nothing else. It is a runner and not the session because a session
may have the Supabase connector and still have no route to the storage
bucket, and the runner has both. Pages does not follow by itself: a push made
with `GITHUB_TOKEN` does not start another workflow, which is why the second
line is there.

The same tool runs by hand, against a directory of photographs or a `file://`
URL instead of the project, which is how it is tested:

    python3 pipeline/from_captures.py --slug <slug> --name "<Hunt Name>" \
        --manifest manifest.json --base <directory>

Photographs that arrive as files rather than through the capture page take
the older route: put them in `photos/<slug>/` named as the stencils should be
named, and cut them directly.

    python3 pipeline/stencil.py photos/<slug>/*.jpg --out app/img/<slug>
    python3 pipeline/sheet.py content/<slug>.json sheet.jpg

Left to itself the tool keeps 0.12 of each frame's edges and chooses the
speck limit per photograph, raising it until most of what survives is
strokes rather than specks, and says what it chose. It also says when a
photograph is a poor subject: `mostly texture` (wicker, gravel, foliage),
`sparse` (too few edges to hold), or `dim` (a dark room is noise to the
camera). Those are the ones to take again, with a subject that has big
permanent edges two to four metres away in decent light, and nothing that
moves. `--keep` and `--speck` still fix the recipe by hand, and the hunt
workflow takes both as inputs for the photograph that needs it. Look at
every `*-stencil-preview.jpg`, or at the sheet: a stencil is good when a
person could tell what it is. Then write `content/<slug>.json`:

    {
      "id": "trafalgar",
      "name": "Trafalgar",
      "test_mode": false,
      "map": {"bounds": [[51.5060, -0.1310], [51.5100, -0.1240]]},
      "stencils": [
        {"id": "lions", "src": "img/trafalgar/lions-stencil.png",
         "clue": "Between the fountains, looking north.",
         "location": {"lat": 51.50787, "lon": -0.12812}},
        {"id": "column", "src": "img/trafalgar/column-stencil.png"}
      ]
    }

`clue`, `location` and `hint` are optional per stencil. `map` is optional: `bounds`
is a street map of that box (the smallest box round the locations, widened
by about 150 m), `image` is a hand-made map at `img/<slug>/map.jpg` for a
small or indoor hunt, shown as a picture to pan and pinch with no location
read at all. `test_mode` puts a Skip on the camera screen and Test the tick
in the menu; make it false before anybody plays for real.

Then measure what was cut, against the photographs it was cut from:

    python3 pipeline/audit.py content/<slug>.json --photos photos/<slug>

Two scores per stencil. The attainable score is what it gets against its own
photograph, which is the most a player standing in the right place can ever
get, since nobody holds a phone as steady as the photograph does; the
confusion is the best it reaches against any other photograph of the hunt,
which is what a player gets for standing somewhere else. Beside them are the
on and off means behind the attainable score, and off is the number that
governs the outcome: it is the edge activity in the ring just beside the
lines, and a stencil scores only where its lines are busier than their
surroundings. A photograph with busy surroundings — a plain door in a
cluttered hall, railings against foliage — scores badly however strong its
own edges are. On the first hunt walked, the two stencils that would not pass
where they were taken are the two lowest attainable scores of that house's
nine photographs, and the worst confusion of the nine is one of them.

It exits 1 naming the stencils if an attainable score is under `--floor`
(0.35 by default) or a confusion reaches 0.20, the lowest pass line. A
stencil under the floor is answered with another photograph, not with another
`--keep`: no recipe takes the clutter out from beside the lines. `--floor 0`
measures a hunt without judging it, for a hunt already in the field or a cut
being compared with the one before it, and `--json` keeps the numbers to
compare with.

Then run the tests, including the fake-camera pass for the new hunt:

    cd tests && HUNT=<slug> npx playwright test feed.spec.js

## Test

    python3 -m unittest discover -s tests -p 'test_*.py'
    cd tests && npm install && npx playwright test

Playwright, headless Chromium, a phone-sized viewport, a fake camera, a
stubbed vibration and a stubbed Supabase, against the fixture hunts built
into `tests/.site`. `tests/png2y4m.py` turns a photograph into the y4m file
the fake camera plays, so a stencil can be tested against its own
photograph. `Lens.fakeScore(v)` paints the bar as if the smoothed score were
`v`; it feeds nothing else and is there for the tests.

`audit.spec.js` is the one that keeps `pipeline/audit.py` honest. The audit
decides whether a hunt is worth walking to, and it does that by writing
`lens.js`'s arithmetic out again in Python; a copy that drifts would pass
hunts the camera cannot read and refuse ones it can. So every fixture
photograph is scored twice, once by the audit and once by `lens.js` itself
with the photograph in the fake camera, and the two have to agree. They
agree to 0.008 on the fixture hunt and to 0.008 over the forty-nine
photograph-and-stencil pairs of Snowman House, the audit reading high every
time by about 0.007, which is PIL's resize of a JPEG against the browser's
draw of a decoded video frame. Read an audit number as about 0.007 kind.

To try the built site on a phone use the Pages URL: the camera needs a
secure context, and a file path is not one.

## What changed from architect-order

The scorer is architect-order's with two changes. The working frame is the
video's rendered rectangle rather than the screen, since the video is
letterboxed here and the stencil is placed inside it; and the box blur in
`edgeMap` clamps at the frame's border instead of leaving it at zero. The
zero border made the Sobel see a bright line all the way round the frame,
in every stencil and in every live frame alike, and a line that is always
there is a match for free: with the stencil filling the rectangle, a blank
wall passed. `stencil.py` computes the same blur, so a stencil is still
exactly the edges the camera will see. The search is wider, ±5 px and five
scales from 0.85 to 1.15, 45 evaluations, because photographs from the
camera app lean on the scale search and the first hunt showed ±10% was
tight.

## The leaderboard

Two boards read the same Supabase project. The one under `Congratulations!`
is the fastest fifty finishing times, from `completions`, and it is there
only when a walk is done. The button in the header, the three bars beside
the map button and the `⋯`, opens the other at any time: one row per run of
this hunt, from `progress`, showing how far each has got.

    progress(run_id uuid primary key, hunt text, name text,
             done int, total int, ms int, updated_at timestamptz)

The phone upserts its own row on every pass and once on each load of a run
that has begun, with `Prefer: resolution=merge-duplicates`, so a run keeps
one row however many times it is sent. `ms` is the number the clock shows,
hints and all, which on the last pass is the finishing time: a finished
run's row is final. A post that fails is silent and nothing waits on it —
the next pass or the next load sends it again — so the pass, the clock and
the tick are never held up by the network. Without a config there is no
button and no request.

Finished runs sort above unfinished ones, by time; the rest by how far they
have got and then by time. A finished row carries its `6/6` in the good
colour, and the player's own row is in the accent colour, as the finish
board marks it. The board is fetched when the screen opens; while a fetch is
in flight the screen shows what the last one found, and a fetch that fails
leaves it as it was, with no spinner and no error text.

## Telemetry

Every opening of the camera screen posts one row to `attempts` as it
closes. The row is not anonymous: it carries the player's chosen name and
the run's id, as the leaderboard rows do. With them go how the opening
ended (`match`, `skip` or `back`), which pass line a match came from, how long the screen was open, how many evaluations ran, the best
score the scorer saw and what was under and beside the lines at that moment,
how long the smoothed score sat at or above the lowest line, whether the
hint was showing, the working frame the phone settled on and what an
evaluation cost it, and `trace`, the smoothed score once a second for the
last eight minutes of the opening, a blank for any second in which nothing
was evaluated (the camera not yet up, the page hidden). For a
located stencil `dist_m` is how far the phone was from where the photograph
was taken when the screen closed; no position is kept. The phone never reads
the table and the anon key cannot; the session reads it through the
connector, and `supabase/schema.sql` ends with the two queries to start
from. It exists so that the pass lines and the choice of stencils can be
tuned on what players saw rather than on what the audit predicts: the audit
says what a stencil can score against its own photograph, and this says what
it did score against the room.

## The hint

A stencil may carry a `hint`: the same picture with twice as much of it
kept, which `stencil.py` writes beside every stencil as
`<id>-stencil-hint.png`. With one in the hunt file, the camera screen shows
a `?` at the top right; a tap lays the denser stencil under the real one,
dimmer, and adds thirty seconds to the clock, once per stencil, kept in the
phone's state and folded into the time that goes to the board. It is
display only: the scorer keeps reading the real stencil, and nothing about
a hint completes anything. Leave `hint` out of a stencil and there is no
button.

## The pass rule

The smoothed score is evaluated every 250 ms. The stencil passes when any
one of these has held, continuously, on consecutive evaluations: 0.30 for
0.6 s, 0.25 for 1.0 s, or 0.20 for 2.0 s (each 0.05 under the handoff's
lines, after the first hunt was walked). Each line keeps its own timer. The
bar at the top is the smoothed score against the 0.30 line, so a pass that
comes from a lower line is seen with the bar part of the way across. There
is nothing to press to complete a stencil.

## Known risk

A browser's camera stream and the phone's camera app do not always show the
same field of view. The stencil is fixed, so a scale difference between the
photograph and the live view cannot be corrected by the player: that is why
the capture page exists and is the way to take the photographs. Between
phones, main cameras run from about 24 to 28 mm equivalent, which is up to
about 15% wider or tighter; the scale search in the scorer is ±10% for that.
If a second phone shows it is not enough, widen `MATCH_SCALES` in
`app/lens.js`.

## The tick

Every tap ticks, as in architect-order: an invisible native switch under
every button's face for iPhone, and one 50 ms vibration in the capture phase
for everything else. The strong pattern is the pass itself, on Android, and a
tap on the Complete! wash.
