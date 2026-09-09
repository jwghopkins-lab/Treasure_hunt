// The audit against the scorer it claims to model.
//
// pipeline/audit.py decides whether a hunt is worth walking to, and it does
// that by reimplementing app/lens.js's arithmetic in Python. A reimplementation
// that drifts is worse than no audit at all: it would pass hunts the camera
// cannot read and refuse ones it can. So the fixture hunt is scored twice —
// once by the audit, once by lens.js itself in a browser with the photograph
// in its fake camera — and the two have to agree.
//
// The browser number comes from `Lens.bothWays()`, which scores the frame
// showing at that instant over the same search the match loop uses. The loop
// is stopped first, because a good alignment passes and a pass closes the
// screen.
const { test, expect } = require("@playwright/test");
const { execFileSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");
const { ROOT, INIT, hunt, browserWithFeed, mobileContext, stubBoard } = require("./helpers");

const FIX = hunt("fixture");

// One browser at a time: the scorer is doing real work in each of them.
test.describe.configure({ mode: "serial" });

// How far apart the two may be. Measured over the seven Snowman House
// stencils and the ten of Park gate, the audit reads high by 0.001 to 0.008,
// the difference being PIL's resize of a JPEG against the browser's draw of
// a decoded video frame. This is about twice that, which leaves room for a
// slower machine's rounding without leaving room for a difference in the
// arithmetic: the fixture hunt scores in the high eighties, where the score
// curve is flat, and switching the weighting off on one side alone moves it
// by only about 0.01. A looser line here would pass that.
const TOLERANCE = 0.015;

let AUDIT = null;

test.beforeAll(() => {
  const out = path.join(os.tmpdir(), "fixture-audit.json");
  // --floor 0 measures without judging: this test is about agreement, not
  // about whether the fixture hunt is a good hunt.
  execFileSync("python3", [path.join(ROOT, "pipeline", "audit.py"), "content/fixture.json",
                           "--photos", "photos/fixture", "--json", out, "--floor", "0"],
               { cwd: ROOT, stdio: ["ignore", "pipe", "pipe"] });
  AUDIT = JSON.parse(fs.readFileSync(out, "utf8"));
});

test.describe("the audit and the camera", () => {
  for (const s of FIX.stencils) {
    test(`${s.id}: the audit's attainable score is what lens.js reads`, async () => {
      test.setTimeout(90000);
      const row = AUDIT.stencils.find((r) => r.id === s.id);
      expect(row, `audit has no row for ${s.id}`).toBeTruthy();
      const browser = await browserWithFeed(`fixture-${s.id}.y4m`);
      const context = await mobileContext(browser);
      const page = await context.newPage();
      const errors = [];
      page.on("pageerror", (e) => errors.push(String(e)));
      await page.addInitScript(INIT);
      await page.addInitScript(() => { localStorage.setItem("treasure.name", "Ada"); });
      stubBoard(page);
      try {
        await page.goto("fixture/");
        await expect(page.locator("#s-main")).toBeVisible();
        await page.locator(`#grid .tile[data-id="${s.id}"]`).click();
        await expect(page.locator("#lens")).toBeVisible();
        await page.waitForFunction(() => window.Lens && window.Lens.isOpen());
        await page.evaluate(() => window.Lens.fakeScore(0));
        await page.waitForFunction(() => {
          const v = document.getElementById("lensfeed");
          const i = document.getElementById("lensstencil");
          return v && v.videoWidth > 0 && i && i.naturalWidth > 0;
        });
        // A moment for the camera to be showing the photograph rather than
        // the grey frame it opens on.
        await page.waitForTimeout(400);
        const r = await page.evaluate(() => window.Lens.bothWays());
        expect(r, "bothWays had no frame to score").toBeTruthy();
        expect(r.n).toBeGreaterThan(0);
        // The number being compared came off the weighted path. The fixture
        // stencils are cut by the current tool and carry strengths; if the
        // browser stopped weighing them the two sides would be measuring
        // different arithmetic, which is exactly what this test is for.
        expect(r.weights, `${s.id} was not weighed in the browser`).toBe(true);
        expect(r.minW, `${s.id} is weighed but every weight is one`).toBeLessThan(1);
        const drift = Math.abs(r.weighted - row.attainable);
        console.log(`${s.id}: audit ${row.attainable.toFixed(3)}, `
                    + `camera ${r.weighted.toFixed(3)}, drift ${drift.toFixed(3)}`);
        expect(drift, `${s.id}: audit ${row.attainable}, camera ${r.weighted}`)
          .toBeLessThanOrEqual(TOLERANCE);
        expect(errors).toEqual([]);
      } finally {
        await browser.close();
      }
    });
  }
});
