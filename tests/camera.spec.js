// The camera screen: the stencil fixed, the bar at the top, the clue and the
// distance line, the back button, and nothing else. And the mask under it:
// which pixels the scorer reads, and what it weighs each of them by.
const { test, expect } = require("@playwright/test");
const fs = require("fs");
const path = require("path");
const { ROOT, hunt, prepare, withName, stubBoard, destPoint } = require("./helpers");

const FIX = hunt("fixture");
const withClue = FIX.stencils.find((s) => s.clue && s.location);
const bare = FIX.stencils.find((s) => !s.clue && !s.location);

async function openTile(page, id) {
  await page.locator(`#grid .tile[data-id="${id}"]`).click();
  await expect(page.locator("#lens")).toBeVisible();
}

// The screen open with the match loop stopped, so that a pass cannot close it
// out from under a reading: the fake camera's own pattern scores well enough
// to pass if it is left running.
async function openStill(page, id) {
  await openTile(page, id);
  // The screen opens before the camera has a frame and before the stencil
  // has decoded, and both are read below: the stencil's own pixels are
  // rewritten, and there is nothing to score until the video is running.
  await page.waitForFunction(() => {
    const v = document.getElementById("lensfeed"), s = document.getElementById("lensstencil");
    return v && v.videoWidth > 0 && s && s.naturalWidth > 0 && window.Lens.stats().place;
  });
  await page.evaluate(() => window.Lens.fakeScore(0));
}

// A short name for the mask itself: the pixels of M and then of R, at every
// scale, in the order the scorer holds them. Two masks that agree on every
// pixel and its place agree here; one that gains, loses or moves a single
// pixel does not. The hashing is done in the page because the mask is a
// quarter of a million numbers and the answer is eight characters.
async function maskDigest(page) {
  return page.evaluate(() => {
    const m = window.Lens.maskSets();
    if (!m) return null;
    let hash = 0x811c9dc5;
    const eat = (v) => { hash = Math.imul(hash ^ (v >>> 0), 0x01000193) >>> 0; };
    for (const mk of m.sets) {
      eat(mk.M.length); eat(mk.R.length);
      for (let t = 0; t < mk.M.length; t++) eat(mk.M[t]);
      for (let t = 0; t < mk.R.length; t++) eat(mk.R[t]);
    }
    return { digest: hash.toString(16).padStart(8, "0"), size: [m.w, m.h],
             scales: m.sets.map((mk) => mk.M.length) };
  });
}

// A PNG from the repository worn in place of the hunt's own stencil. The wait
// is for the screen's own load handler, which lays the new one out before
// anything can be measured against it.
async function wearStencil(page, file) {
  await wear(page, "data:image/png;base64," + fs.readFileSync(file).toString("base64"));
}
async function wear(page, src) {
  await page.evaluate((s) => new Promise((done) => {
    const img = document.getElementById("lensstencil");
    img.addEventListener("load", done, { once: true });
    img.src = s;
  }), src);
}

// Whether a stencil PNG carries strengths, read off its own pixels rather
// than out of the scorer: what the tool wrote, not what the mask came out
// with. The two are the same question asked of different code, which is the
// point — it is what lets a test say the scorer weighed the stencil it was
// given rather than merely that it weighed something.
async function gradedAlpha(page, file) {
  return page.evaluate((src) => new Promise((done, fail) => {
    const img = new Image();
    img.onerror = () => fail(new Error("the stencil would not decode"));
    img.onload = () => {
      const c = document.createElement("canvas");
      c.width = img.naturalWidth; c.height = img.naturalHeight;
      const ctx = c.getContext("2d", { willReadFrequently: true });
      ctx.drawImage(img, 0, 0);
      const d = ctx.getImageData(0, 0, c.width, c.height).data;
      for (let j = 3; j < d.length; j += 4) if (d[j] && d[j] !== 255) return done(true);
      done(false);
    };
    img.src = src;
  }), "data:image/png;base64," + fs.readFileSync(file).toString("base64"));
}

// Where the mask sits in the working frame, and how much of it there is.
async function maskCentre(page) {
  return page.evaluate(() => {
    const m = window.Lens.maskSets();
    if (!m) return null;
    const mk = m.sets[Math.floor(m.sets.length / 2)];   // the scale nearest 1
    let sx = 0, sy = 0;
    for (let t = 0; t < mk.M.length; t++) { sx += mk.M[t] % m.w; sy += Math.floor(mk.M[t] / m.w); }
    return { n: mk.M.length, x: sx / mk.M.length, y: sy / mk.M.length, w: m.w, h: m.h };
  });
}

// The hunt's own stencil redrawn at a chosen alpha wherever it has any: left
// of the middle at one value, right of it at another. A test about the
// weights should say what the alpha is rather than trust how it was cut.
async function wearAlpha(page, left, right) {
  const src = await page.evaluate(([l, r]) => {
    const img = document.getElementById("lensstencil");
    const c = document.createElement("canvas");
    c.width = img.naturalWidth; c.height = img.naturalHeight;
    const ctx = c.getContext("2d");
    ctx.drawImage(img, 0, 0);
    const d = ctx.getImageData(0, 0, c.width, c.height);
    for (let y = 0; y < c.height; y++) {
      for (let x = 0; x < c.width; x++) {
        const j = (y * c.width + x) * 4 + 3;
        if (d.data[j]) d.data[j] = x < c.width / 2 ? l : r;
      }
    }
    ctx.putImageData(d, 0, 0);
    return c.toDataURL();
  }, [left, right]);
  await wear(page, src);
}


test.describe("the camera screen", () => {
  test.beforeEach(async ({ page }) => {
    await prepare(page);
    await withName(page);
    stubBoard(page);
  });

  test("shows the stencil fixed over the video, the bar at the top, the clue, the back button and no other controls", async ({ page }) => {
    await page.goto("fixture/");
    await openTile(page, withClue.id);
    const lens = page.locator("#lens");
    // The fill is empty before the first evaluation, and is held there while
    // the rest of the screen is measured: the fake camera's own pattern has
    // edges, and left running it fills the bar in behind the measurements.
    expect(await page.evaluate(() => {
      const w = document.getElementById("matchfill").style.width;
      window.Lens.fakeScore(0);
      return w;
    })).toBe("0%");
    await expect(lens.locator("#lensstencil")).toHaveAttribute("src", withClue.src);
    await expect(lens.locator("#lensfeed")).toBeVisible();
    // The bar is at the very top and the full width.
    const bar = await lens.locator("#matchbar").boundingBox();
    const vp = page.viewportSize();
    expect(bar.y).toBeLessThanOrEqual(1);
    expect(bar.width).toBeCloseTo(vp.width, 0);
    await expect(lens.locator("#matchfill")).toHaveAttribute("style", /width: 0%/);
    // The clue, in the strip at the bottom.
    await expect(lens.locator("#lensclue")).toHaveText(withClue.clue);
    const strip = await lens.locator("#lensfoot").boundingBox();
    expect(strip.y + strip.height).toBeGreaterThan(vp.height - 2);
    // The back button top-left, and Skip because the fixture has test mode on.
    await expect(lens.locator("#lensback")).toBeVisible();
    await expect(lens.locator("#lensback")).toHaveText("←");
    const back = await lens.locator("#lensback").boundingBox();
    expect(back.x).toBeLessThan(40);
    expect(back.y).toBeLessThan(80);
    const visibleButtons = await lens.locator("button:visible").evaluateAll((els) => els.map((e) => e.id));
    expect(visibleButtons.sort()).toEqual(withClue.hint ? ["lensback", "lenshintbtn", "lensskip"] : ["lensback", "lensskip"]);
    // No words but the clue, Skip and the hint's glyph.
    // (The mocked position is far away, so the distance line may be there too.)
    const words = await lens.evaluate((el) => el.innerText.replace(/\s+/g, " ").trim());
    const rest = words.replace("←", "").replace("Skip", "").replace("?", "").trim();
    expect(rest.startsWith(withClue.clue)).toBe(true);
    expect(rest.slice(withClue.clue.length).trim()).toMatch(/^(About [\d.]+ (m|km) · (N|NE|E|SE|S|SW|W|NW))?$/);
    await expect(lens.locator("#lenswash")).toBeHidden();
    await expect(lens.locator("input[type=range]")).toHaveCount(0);
  });

  test("the stencil sits centred in the video's rectangle at the stencil's own aspect", async ({ page }) => {
    await page.goto("fixture/");
    await openTile(page, withClue.id);
    // The fake camera is 640x480 by default here: a landscape feed on a
    // portrait screen, letterboxed top and bottom, and a portrait stencil
    // fitted inside that, centred.
    await page.waitForFunction(() => { const v = document.getElementById("lensfeed"); return v && v.videoWidth > 0; });
    const st = await page.evaluate(() => window.Lens.stats());
    const vp = page.viewportSize();
    expect(st.rect.w).toBeCloseTo(vp.width, 0);
    expect(st.rect.h).toBeCloseTo(vp.width * 480 / 640, 0);
    expect(st.rect.y).toBeCloseTo((vp.height - st.rect.h) / 2, 0);
    const box = await page.locator("#lensstencil").boundingBox();
    expect(box.height).toBeCloseTo(st.rect.h, 0);
    expect(box.width).toBeCloseTo(st.rect.h * 600 / 800, 0);
    expect(box.x + box.width / 2).toBeCloseTo(vp.width / 2, 0);
    expect(box.y + box.height / 2).toBeCloseTo(vp.height / 2, 0);
  });

  test("shows nothing at the bottom for a stencil with neither clue nor location", async ({ page }) => {
    await page.goto("fixture/");
    await openTile(page, bare.id);
    await expect(page.locator("#lensfoot")).toBeHidden();
    await expect(page.locator("#lensclue")).toBeHidden();
    await expect(page.locator("#lensdist")).toBeHidden();
    const words = await page.locator("#lens").evaluate((el) => el.innerText.replace(/\s+/g, " ").trim());
    expect(words.replace("←", "").replace("Skip", "").replace("?", "").trim()).toBe("");
  });

  test("pointer drags and pinches do not move the stencil", async ({ page }) => {
    await page.goto("fixture/");
    await openTile(page, withClue.id);
    await page.waitForFunction(() => { const v = document.getElementById("lensfeed"); return v && v.videoWidth > 0; });
    const before = await page.locator("#lensstencil").boundingBox();
    const vp = page.viewportSize();
    await page.mouse.move(vp.width / 2, vp.height / 2);
    await page.mouse.down();
    await page.mouse.move(vp.width / 2 + 90, vp.height / 2 + 60, { steps: 6 });
    await page.mouse.up();
    // A two-finger pinch, as pointer events on the screen.
    await page.evaluate(() => {
      const el = document.getElementById("lens");
      const ev = (type, id, x, y) => el.dispatchEvent(new PointerEvent(type, { pointerId: id, pointerType: "touch",
        clientX: x, clientY: y, bubbles: true, isPrimary: id === 1 }));
      ev("pointerdown", 1, 150, 400); ev("pointerdown", 2, 250, 400);
      ev("pointermove", 1, 100, 350); ev("pointermove", 2, 300, 450);
      ev("pointermove", 1, 60, 300); ev("pointermove", 2, 340, 500);
      ev("pointerup", 1, 60, 300); ev("pointerup", 2, 340, 500);
      const t = (type, touches) => el.dispatchEvent(new TouchEvent(type, { bubbles: true, cancelable: true,
        touches: touches.map(([id, x, y]) => new Touch({ identifier: id, target: el, clientX: x, clientY: y })) }));
      t("touchstart", [[1, 150, 400], [2, 250, 400]]);
      t("touchmove", [[1, 100, 350], [2, 300, 450]]);
      t("touchend", []);
    });
    await page.waitForTimeout(300);
    const after = await page.locator("#lensstencil").boundingBox();
    expect(after).toEqual(before);
  });

  test("the bar: 0.15 fills half the width, 0.30 and above fills all of it", async ({ page }) => {
    await page.goto("fixture/");
    await openTile(page, withClue.id);
    await page.evaluate(() => window.Lens.fakeScore(0.15));
    await expect(page.locator("#matchfill")).toHaveAttribute("style", /width: 50%/);
    const bar = await page.locator("#matchbar").boundingBox();
    // The fill eases over 200 ms; wait for it to land.
    await expect.poll(async () => (await page.locator("#matchfill").boundingBox()).width).toBeCloseTo(bar.width / 2, 0);
    await page.evaluate(() => window.Lens.fakeScore(0.30));
    await expect(page.locator("#matchfill")).toHaveAttribute("style", /width: 100%/);
    await page.evaluate(() => window.Lens.fakeScore(0.9));
    await expect(page.locator("#matchfill")).toHaveAttribute("style", /width: 100%/);
    // Green, not white, and no tick mark or threshold line anywhere.
    await expect(page.locator("#matchfill")).toHaveCSS("background-color", "rgb(63, 191, 127)");
    await expect(page.locator("#matchtick")).toHaveCount(0);
  });

  test("the mask weighs each pixel by the stencil's alpha, and the shape does not move with it", async ({ page }) => {
    await page.goto("fixture/");
    await openStill(page, withClue.id);
    // Alpha 255 wherever the picture has any, which is how every stencil was
    // cut before the alpha carried a strength: there is nothing to weigh by,
    // no weights are built, and the plain mean is what runs.
    await wearAlpha(page, 255, 255);
    const full = await page.evaluate(() => window.Lens.bothWays());
    const fullMask = await maskDigest(page);
    expect(full.n).toBeGreaterThan(0);
    expect(full.weights).toBe(false);
    expect(full.minW).toBe(1);
    expect(full.maxW).toBe(1);
    expect(full.weighted).toBe(full.flat);
    // Now the same picture with the alpha down the left at a fifth, which is
    // well under the 128 the shape is thresholded at. The weights follow the
    // alpha all the way down, and the mask is the same mask to the pixel,
    // digest and all, because a faint line is still a line.
    await wearAlpha(page, 51, 255);
    const faint = await page.evaluate(() => window.Lens.bothWays());
    expect(faint.weights).toBe(true);
    expect(await maskDigest(page)).toEqual(fullMask);
    expect(faint.n).toBe(full.n);
    expect(faint.minW).toBeGreaterThan(0.19);
    expect(faint.minW).toBeLessThan(0.21);
    expect(faint.maxW).toBe(1);
    expect(faint.weighted).not.toBe(faint.flat);
  });

  test("every stencil the repository ships builds a mask the scorer can read", async ({ page }) => {
    test.setTimeout(180000);
    // Park gate's ten were once pinned here by digest, because their
    // photographs were gone and they could never be recut. The photographs
    // came back and every hunt has been recut weighted, so a golden digest
    // would now only pin whichever cut happened to be committed. What is
    // worth holding is what a stencil has to be for the scorer to read it at
    // all, and that is true of every stencil of every hunt: a mask with
    // pixels in it at all five scales, in the working frame the fake camera
    // gives this suite, and weights that are strengths — over nought, never
    // over one, and one somewhere, since the tool keeps the strongest edge it
    // finds. A stencil that is alpha 255 all through carries no weights and
    // has to score exactly what the plain mean scores, which is the arithmetic
    // the game shipped with.
    const dir = path.join(ROOT, "app", "img");
    const hunts = fs.readdirSync(dir).filter((d) => fs.statSync(path.join(dir, d)).isDirectory()).sort();
    const files = hunts.flatMap((h) => fs.readdirSync(path.join(dir, h))
      .filter((f) => f.endsWith("-stencil.png")).sort().map((f) => path.join(h, f)));
    expect(files.length).toBeGreaterThan(20);
    let graded = 0;
    await page.goto("fixture/");
    for (const f of files) {
      // One opening each: the masks a stencil builds are held until the
      // screen closes, and thirty stencils' worth is a lot to hold at once.
      await openStill(page, bare.id);
      await wearStencil(page, path.join(dir, f));
      const r = await page.evaluate(() => window.Lens.bothWays());
      const m = await maskDigest(page);
      expect(r.n, f).toBeGreaterThan(0);
      // The default fake camera is 640x480, so the working frame is 320x240
      // and not the phone's own portrait.
      expect(m.size, f).toEqual([320, 240]);
      expect(m.scales.length, f).toBe(5);
      for (const n of m.scales) expect(n, `${f} has a scale with an empty mask`).toBeGreaterThan(0);
      expect(r.minW, `${f} has a weight at or under nought`).toBeGreaterThan(0);
      expect(r.maxW, `${f} has a weight over one`).toBe(1);
      // The scorer weighed this stencil if and only if the tool wrote
      // strengths into it. Without this the test passes with the weighting
      // switched off altogether: a stencil that carries no weights reports
      // minW and maxW as one, which satisfies everything above.
      const isGraded = await gradedAlpha(page, path.join(dir, f));
      expect(r.weights, isGraded ? `${f} carries strengths and was not weighed`
                                 : `${f} is alpha 255 all through and was weighed`).toBe(isGraded);
      if (isGraded) {
        graded += 1;
        expect(r.minW, `${f} is weighed but every weight is one`).toBeLessThan(1);
      } else {
        expect(r.minW, f).toBe(1);
      }
      await page.locator("#lensback").click();
      await expect(page.locator("#lens")).toBeHidden();
    }
    // And the repository is not all flat, which would make the line above
    // true of everything without the scorer weighing anything.
    expect(graded, "no shipped stencil carries strengths").toBeGreaterThan(0);
  });

  test("the mask sits where the stencil is drawn, to the pixel", async ({ page }) => {
    // What the golden digest of Park gate's ten used to hold: an absolute
    // pin on where the mask lands, rather than one mask compared with
    // another. A stencil symmetric about both axes has to give a mask whose
    // centre of gravity is the frame's centre; an off-by-one anywhere in the
    // centring, the shrink or the thickening moves it by a whole pixel, and
    // every score in the game is taken over pixels that have moved.
    await page.goto("fixture/");
    await openStill(page, bare.id);
    // A cross and a border, drawn at the stencil's own resolution, symmetric
    // under a flip about either axis. Built here rather than read from the
    // repository so that recutting a hunt cannot change what this pins.
    await wear(page, await page.evaluate(() => {
      const c = document.createElement("canvas");
      c.width = 600; c.height = 800;
      const ctx = c.getContext("2d");
      ctx.strokeStyle = "rgba(255,61,0,1)";
      ctx.lineWidth = 6;
      ctx.beginPath();
      ctx.moveTo(300, 40); ctx.lineTo(300, 760);
      ctx.moveTo(40, 400); ctx.lineTo(560, 400);
      ctx.strokeRect(60, 100, 480, 600);
      ctx.stroke();
      return c.toDataURL();
    }));
    const c = await maskCentre(page);
    expect(c.n).toBeGreaterThan(100);
    expect(c.x).toBeCloseTo((c.w - 1) / 2, 0);
    expect(c.y).toBeCloseTo((c.h - 1) / 2, 0);
  });

  test("the distance line reads the mocked position and blanks on a poor fix", async ({ page, context }) => {
    const loc = withClue.location;
    await context.setGeolocation({ ...destPoint(loc.lat, loc.lon, 225, 240), accuracy: 15 });
    await page.goto("fixture/");
    await openTile(page, withClue.id);
    await expect(page.locator("#lensdist")).toHaveText("About 240 m · NE");
    await context.setGeolocation({ ...destPoint(loc.lat, loc.lon, 0, 620), accuracy: 15 });
    await expect(page.locator("#lensdist")).toHaveText("About 600 m · S");
    await context.setGeolocation({ ...destPoint(loc.lat, loc.lon, 90, 1240), accuracy: 15 });
    await expect(page.locator("#lensdist")).toHaveText("About 1.2 km · W");
    await context.setGeolocation({ ...destPoint(loc.lat, loc.lon, 225, 240), accuracy: 100 });
    await expect(page.locator("#lensdist")).toHaveText("");
    // Under the clue, in the same strip.
    const clue = await page.locator("#lensclue").boundingBox();
    const dist = await page.locator("#lensdist").boundingBox();
    expect(dist.y).toBeGreaterThanOrEqual(clue.y + clue.height - 1);
    // One watch while open, cleared on back.
    expect(await page.evaluate(() => window.__geo.watches)).toBe(1);
    await page.locator("#lensback").click();
    expect(await page.evaluate(() => window.__geo.clears)).toBe(1);
  });

  test("an unlocated stencil shows no line and asks for no permission", async ({ page }) => {
    await page.goto("fixture/");
    await openTile(page, bare.id);
    await page.waitForTimeout(500);
    expect(await page.evaluate(() => window.__geo.watches)).toBe(0);
    await expect(page.locator("#lensdist")).toBeHidden();
  });

  test("says when the camera was refused, or is missing, and keeps the back button", async ({ page }) => {
    await page.addInitScript(() => {
      navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException("no", "NotAllowedError"));
    });
    await page.goto("fixture/");
    await openTile(page, bare.id);
    await expect(page.locator("#lensmsg")).toHaveText("The camera was refused.");
    await expect(page.locator("#lensback")).toBeVisible();
    await expect(page.locator("input[type=file]")).toHaveCount(0);
    await page.locator("#lensback").click();
    await expect(page.locator("#lens")).toBeHidden();

    await page.addInitScript(() => {
      navigator.mediaDevices.getUserMedia = () => Promise.reject(new DOMException("no", "NotFoundError"));
    });
    await page.reload();
    await openTile(page, bare.id);
    await expect(page.locator("#lensmsg")).toHaveText("No camera here.");
  });

  test("a stream that arrives after back was tapped is stopped on arrival", async ({ page }) => {
    await page.addInitScript(() => {
      window.__stopped = 0;
      const real = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
      navigator.mediaDevices.getUserMedia = async (c) => {
        const s = await real(c);
        await new Promise((r) => setTimeout(r, 600));
        for (const t of s.getTracks()) { const stop = t.stop.bind(t); t.stop = () => { window.__stopped += 1; stop(); }; }
        return s;
      };
    });
    await page.goto("fixture/");
    await openTile(page, bare.id);
    await page.locator("#lensback").click();
    await page.waitForTimeout(900);
    expect(await page.evaluate(() => window.__stopped)).toBeGreaterThan(0);
    expect(await page.evaluate(() => document.getElementById("lensfeed").srcObject)).toBeNull();
  });
});
