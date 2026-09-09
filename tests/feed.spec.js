// The scorer, with a real picture in the fake camera: the stencil's own
// photograph passes within three seconds, a blank grey frame never does, and
// a stencil that is alpha 255 all through scores what it scored before the
// alpha carried a weight.
const { test, expect } = require("@playwright/test");
const { execFileSync } = require("child_process");
const fs = require("fs");
const path = require("path");
const { ROOT, Y4M, INIT, hunt, browserWithFeed, mobileContext, stubBoard } = require("./helpers");

const FIX = hunt("fixture");

// One at a time: each of these runs a browser with the scorer in it, and four
// of them on four cores slow the evaluations enough to miss a three-second
// window that a phone meets with ease.
test.describe.configure({ mode: "serial" });

async function openWithFeed(y4m, huntPath) {
  const browser = await browserWithFeed(y4m);
  const context = await mobileContext(browser);
  const page = await context.newPage();
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.addInitScript(INIT);
  await page.addInitScript(() => { localStorage.setItem("treasure.name", "Ada"); });
  stubBoard(page);
  await page.goto(huntPath);
  await expect(page.locator("#s-main")).toBeVisible();
  return { browser, page, errors };
}

async function expectPass(page, id, within) {
  await page.locator(`#grid .tile[data-id="${id}"]`).click();
  await expect(page.locator("#lens")).toBeVisible();
  await page.waitForFunction(() => { const v = document.getElementById("lensfeed"); return v && v.videoWidth > 0; });
  const size = await page.evaluate(() => { const v = document.getElementById("lensfeed"); return [v.videoWidth, v.videoHeight]; });
  const t0 = Date.now();
  // The pass stops the match loop, so a reading taken after it is empty:
  // what the stencil scored has to be kept as it goes past. The log below is
  // read to judge a hunt, and a hunt is judged on the number.
  let stats = null;
  await expect
    .poll(async () => {
      const st = await page.evaluate(() => window.Lens.stats());
      if (st && st.score != null) stats = st;
      return page.locator("#lenswash").isVisible();
    }, { timeout: within, intervals: [100] })
    .toBe(true);
  const took = Date.now() - t0;
  await expect(page.locator("#lens")).toBeHidden({ timeout: 2500 });
  await expect(page.locator(`#grid .tile[data-id="${id}"]`)).toHaveClass(/passed/);
  return { took, size, stats };
}

test.describe("the fake camera", () => {
  for (const s of FIX.stencils) {
    test(`the ${s.id} stencil passes against its own photograph within three seconds`, async () => {
      test.setTimeout(90000);
      const { browser, page, errors } = await openWithFeed(`fixture-${s.id}.y4m`, "fixture/");
      try {
        const r = await expectPass(page, s.id, 3000);
        expect(r.size).toEqual([600, 800]);
        // The pass came from the match loop: the strong pattern, outside a tap.
        const vibes = await page.evaluate(() => window.__vibes);
        const strong = vibes.filter((v) => Array.isArray(v.p));
        expect(strong.length).toBe(1);
        expect(strong[0]).toEqual({ p: [60, 50, 60], inTap: false });
        expect(errors).toEqual([]);
      } finally {
        await browser.close();
      }
    });
  }

  test("the hint changes nothing for the scorer: the door still passes with it showing", async () => {
    test.setTimeout(90000);
    const door = FIX.stencils.find((s) => s.hint);
    const { browser, page, errors } = await openWithFeed(`fixture-${door.id}.y4m`, "fixture/");
    try {
      await page.locator(`#grid .tile[data-id="${door.id}"]`).click();
      await expect(page.locator("#lens")).toBeVisible();
      await page.locator("#lenshintbtn").click();
      await expect(page.locator("#lenshint")).toBeVisible();
      await expect(page.locator("#lenswash")).toBeVisible({ timeout: 3000 });
      await expect(page.locator("#lens")).toBeHidden({ timeout: 2500 });
      await expect(page.locator(`#grid .tile[data-id="${door.id}"]`)).toHaveClass(/passed/);
      expect(errors).toEqual([]);
    } finally {
      await browser.close();
    }
  });

  test("an all-255 stencil scores against its photograph exactly what the plain mean scored", async () => {
    test.setTimeout(90000);
    const s = FIX.stencils[0];
    const { browser, page, errors } = await openWithFeed(`fixture-${s.id}.y4m`, "fixture/");
    try {
      await page.locator(`#grid .tile[data-id="${s.id}"]`).click();
      await expect(page.locator("#lens")).toBeVisible();
      await page.waitForFunction(() => { const v = document.getElementById("lensfeed"); return v && v.videoWidth > 0; });
      // The loop is stopped first: this stencil passes in about a second, and
      // a pass closes the screen.
      await page.evaluate(() => window.Lens.fakeScore(0));
      // The same picture at alpha 255 wherever it has any, so the test says
      // what the alpha is instead of depending on how the tool cut it.
      await page.evaluate(() => new Promise((done) => {
        const img = document.getElementById("lensstencil");
        const c = document.createElement("canvas");
        c.width = img.naturalWidth; c.height = img.naturalHeight;
        const ctx = c.getContext("2d");
        ctx.drawImage(img, 0, 0);
        const d = ctx.getImageData(0, 0, c.width, c.height);
        for (let j = 3; j < d.data.length; j += 4) if (d.data[j]) d.data[j] = 255;
        ctx.putImageData(d, 0, 0);
        img.addEventListener("load", done, { once: true });
        img.src = c.toDataURL();
      }));
      const r = await page.evaluate(() => window.Lens.bothWays());
      // A stencil with no strength to carry is not weighed at all: `weights`
      // false says the scorer built none and took the plain mean, which is
      // the arithmetic that shipped, rather than a weighted mean that ought
      // to come to the same number. Which pixels that mean is taken over is
      // the other half of the guarantee, and it is pinned where it matters:
      // camera.spec.js holds Park gate's ten masks to the pixel. This
      // fixture will be recut like any other stencil, so what it is worth
      // here is the part a mask cannot show — that a real photograph, played
      // into a real camera, still scores well clear of the top pass line.
      expect(r.weights).toBe(false);
      expect(r.minW).toBe(1);
      expect(r.maxW).toBe(1);
      expect(r.weighted).toBe(r.flat);
      expect(r.n).toBeGreaterThan(0);
      expect(r.weighted).toBeGreaterThan(0.3);
      expect(errors).toEqual([]);
    } finally {
      await browser.close();
    }
  });

  test("a blank grey feed does not pass in ten seconds", async () => {
    test.setTimeout(60000);
    const { browser, page, errors } = await openWithFeed("grey.y4m", "fixture/");
    try {
      await page.locator(`#grid .tile[data-id="${FIX.stencils[0].id}"]`).click();
      await expect(page.locator("#lens")).toBeVisible();
      await page.waitForTimeout(10000);
      await expect(page.locator("#lenswash")).toBeHidden();
      await expect(page.locator("#lens")).toBeVisible();
      const st = await page.evaluate(() => window.Lens.stats());
      expect(st.score == null || st.score < 0.25).toBe(true);
      expect(await page.evaluate(() => window.__th.state().done)).toEqual({});
      expect(errors).toEqual([]);
    } finally {
      await browser.close();
    }
  });

  test("the working frame keeps within the budget on this machine", async () => {
    test.setTimeout(60000);
    const { browser, page } = await openWithFeed("grey.y4m", "fixture/");
    try {
      await page.locator(`#grid .tile[data-id="${FIX.stencils[0].id}"]`).click();
      await page.waitForTimeout(3000);
      const st = await page.evaluate(() => window.Lens.stats());
      expect(st.recent.length).toBeGreaterThan(3);
      expect([320, 240]).toContain(st.workPx);
    } finally {
      await browser.close();
    }
  });
});

// A real hunt, by name: HUNT=<slug> npx playwright test feed.spec.js. Every
// stencil of the hunt against its own photograph in photos/<slug>/, which is
// what section 9 asks for before a hunt is pushed. Skipped without HUNT.
const SLUG = process.env.HUNT;
test.describe("the hunt named in HUNT", () => {
  test.skip(!SLUG, "set HUNT=<slug> to run");
  if (!SLUG) return;
  const H = JSON.parse(fs.readFileSync(path.join(ROOT, "content", SLUG + ".json"), "utf8"));
  for (const s of H.stencils) {
    test(`${SLUG}: ${s.id} passes against its photograph`, async () => {
      test.setTimeout(90000);
      const photo = ["jpg", "jpeg", "JPG", "png"].map((e) => path.join(ROOT, "photos", SLUG, s.id + "." + e)).find((p) => fs.existsSync(p));
      expect(photo, `photos/${SLUG}/${s.id}.jpg`).toBeTruthy();
      // The fake camera plays the photograph at the stencil's own size, which
      // is the photograph resized as the stencil tool resized it: a
      // full-resolution frame would be a gigabyte of y4m for nothing.
      const png = fs.readFileSync(path.join(ROOT, "app", s.src));
      const size = `${png.readUInt32BE(16)}x${png.readUInt32BE(20)}`;
      const y4m = path.join(Y4M, `${SLUG}-${s.id}.y4m`);
      execFileSync("python3", [path.join(ROOT, "tests", "png2y4m.py"), photo, y4m, "--size", size]);
      const browser = await browserWithFeed(y4m);
      const context = await mobileContext(browser);
      const page = await context.newPage();
      await page.addInitScript(INIT);
      await page.addInitScript(() => { localStorage.setItem("treasure.name", "Ada"); });
      stubBoard(page);
      try {
        await page.goto(`${SLUG}/`);
        await expect(page.locator("#s-main")).toBeVisible();
        const r = await expectPass(page, s.id, 3000);
        const st = r.stats || {};
        console.log(`${SLUG}/${s.id}: passed in ${r.took} ms at ${r.size.join("x")}`
                    + `, smoothed ${st.score == null ? "?" : st.score.toFixed(3)}`
                    + `, best ${st.best == null ? "?" : st.best.toFixed(3)}`
                    + `, ${st.ms == null ? "?" : st.ms} ms per evaluation at ${st.workPx} px`);
      } finally {
        await browser.close();
      }
    });
  }
});
