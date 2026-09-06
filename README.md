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
like the ones that will play, under the hunt's slug. Then, in a session with
the Supabase connector:

    select * from captures where hunt = '<slug>' order by taken_at

Download each `path` from the bucket's public URL to `photos/<slug>/<id>.jpg`,
take the clue and, where the accuracy is at most 75 m, the position. Then:

    python3 pipeline/stencil.py photos/<slug>/*.jpg --keep 0.06 --speck 60 --long 800 --out app/img/<slug>

Look at every `*-stencil-preview.jpg`. A photo with too much texture
(foliage, gravel, brick) gives a stencil that is noise: raise `--speck`,
lower `--keep`, or take another photo. A stencil is good when a person could
tell what it is. Write `content/<slug>.json`:

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

`clue` and `location` are optional per stencil. `map` is optional: `bounds`
is a street map of that box (the smallest box round the locations, widened
by about 150 m), `image` is a hand-made map at `img/<slug>/map.jpg` for a
small or indoor hunt, shown as a picture to pan and pinch with no location
read at all. `test_mode` puts a Skip on the camera screen and Test the tick
in the menu; make it false before anybody plays for real.

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
exactly the edges the camera will see. The search is wider, ±5 px and ±10%,
still 27 evaluations.

## The pass rule

The smoothed score is evaluated every 250 ms. The stencil passes when any
one of these has held, continuously, on consecutive evaluations: 0.35 for
0.6 s, 0.30 for 1.0 s, or 0.25 for 2.0 s. Each line keeps its own timer. The
bar at the top is the smoothed score against the 0.35 line, so a pass that
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
