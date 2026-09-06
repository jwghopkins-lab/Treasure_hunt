// The camera screen: the stencil fixed, the bar at the top, the clue and the
// distance line, the back button, and nothing else.
const { test, expect } = require("@playwright/test");
const { hunt, prepare, withName, stubBoard, destPoint } = require("./helpers");

const FIX = hunt("fixture");
const withClue = FIX.stencils.find((s) => s.clue && s.location);
const bare = FIX.stencils.find((s) => !s.clue && !s.location);

async function openTile(page, id) {
  await page.locator(`#grid .tile[data-id="${id}"]`).click();
  await expect(page.locator("#lens")).toBeVisible();
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
