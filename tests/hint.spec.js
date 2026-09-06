// The hint: a denser stencil under the real one, thirty seconds on the clock.
const { test, expect } = require("@playwright/test");
const { hunt, prepare, withName, stubBoard } = require("./helpers");

const FIX = hunt("fixture");
const withHint = FIX.stencils.find((s) => s.hint);
const without = FIX.stencils.find((s) => !s.hint);

async function openTile(page, id) {
  await page.locator(`#grid .tile[data-id="${id}"]`).click();
  await expect(page.locator("#lens")).toBeVisible();
}
const secs = (t) => { const [m, s] = t.split(":").map(Number); return m * 60 + s; };

test.describe("the hint", () => {
  test.beforeEach(async ({ page }) => {
    await prepare(page);
    await withName(page);
    stubBoard(page);
    await page.goto("fixture/");
    await expect(page.locator("#s-main")).toBeVisible();
  });

  test("shows a ? button only for a stencil with a hint", async ({ page }) => {
    await openTile(page, withHint.id);
    await expect(page.locator("#lenshintbtn")).toBeVisible();
    await expect(page.locator("#lenshintbtn")).toHaveText("?");
    await expect(page.locator("#lenshint")).toBeHidden();
    const vp = page.viewportSize();
    const b = await page.locator("#lenshintbtn").boundingBox();
    expect(b.x + b.width).toBeGreaterThan(vp.width - 40);
    expect(b.y).toBeLessThan(80);
    await page.locator("#lensback").click();
    await openTile(page, without.id);
    await expect(page.locator("#lenshintbtn")).toBeHidden();
    await expect(page.locator("#lenshint")).toBeHidden();
  });

  test("a tap lays the denser stencil under the real one, in the same place, and costs thirty seconds at once", async ({ page }) => {
    await openTile(page, withHint.id);
    await page.waitForFunction(() => document.getElementById("lensfeed").videoWidth > 0);
    const before = secs(await page.locator("#clock").textContent());
    await page.locator("#lenshintbtn").click();
    await expect(page.locator("#lenshint")).toBeVisible();
    await expect(page.locator("#lenshint")).toHaveAttribute("src", withHint.hint);
    await expect(page.locator("#lenshintbtn")).toBeHidden();
    const real = await page.locator("#lensstencil").boundingBox();
    const hint = await page.locator("#lenshint").boundingBox();
    expect(hint).toEqual(real);
    // Under, not over: the real stencil comes later in the document.
    const order = await page.evaluate(() => {
      const h = document.getElementById("lenshint"), s = document.getElementById("lensstencil");
      return h.compareDocumentPosition(s) & Node.DOCUMENT_POSITION_FOLLOWING ? "hint-first" : "stencil-first";
    });
    expect(order).toBe("hint-first");
    const after = secs(await page.locator("#clock").textContent());
    expect(after - before).toBeGreaterThanOrEqual(30);
    expect(after - before).toBeLessThan(33);
    const st = await page.evaluate(() => window.__th.state());
    expect(st.hints[withHint.id]).toBe(true);
    // The tap ticked like any tap.
    const vibes = await page.evaluate(() => window.__vibes);
    expect(vibes[vibes.length - 1]).toEqual({ p: 50, inTap: true });
    // The scorer still reads the real stencil, not the hint.
    expect(await page.evaluate(() => window.Lens.stats().hinted)).toBe(true);
  });

  test("a hint is paid once: reopening shows it with no button and no second charge, and a reload keeps it", async ({ page }) => {
    await openTile(page, withHint.id);
    await page.locator("#lenshintbtn").click();
    await page.locator("#lensback").click();
    const t1 = secs(await page.locator("#clock").textContent());
    await openTile(page, withHint.id);
    await expect(page.locator("#lenshint")).toBeVisible();
    await expect(page.locator("#lenshintbtn")).toBeHidden();
    await page.locator("#lensback").click();
    const t2 = secs(await page.locator("#clock").textContent());
    expect(t2 - t1).toBeLessThan(5);
    await page.reload();
    expect(secs(await page.locator("#clock").textContent())).toBeGreaterThanOrEqual(30);
    await openTile(page, withHint.id);
    await expect(page.locator("#lenshint")).toBeVisible();
    await expect(page.locator("#lenshintbtn")).toBeHidden();
  });

  test("the finishing time and the posted time carry the penalty", async ({ page }) => {
    const log = stubBoard(page);
    await openTile(page, withHint.id);
    await page.locator("#lenshintbtn").click();
    await page.locator("#lensskip").click();
    await page.locator("#lenswash").click();
    for (const s of FIX.stencils) {
      if (s.id === withHint.id) continue;
      await openTile(page, s.id);
      await page.locator("#lensskip").click();
      await page.locator("#lenswash").click();
    }
    await expect(page.locator(".congrats")).toBeVisible();
    await expect.poll(() => log.posts.length).toBe(1);
    const st = await page.evaluate(() => window.__th.state());
    const raw = Math.max(...Object.values(st.done)) - st.startedAt;
    expect(log.posts[0].body.ms).toBe(raw + 30000);
    expect(secs(await page.locator("#clock").textContent())).toBe(Math.floor((raw + 30000) / 1000));
  });

  test("Start over forgets the hints too", async ({ page }) => {
    await openTile(page, withHint.id);
    await page.locator("#lenshintbtn").click();
    await page.locator("#lensback").click();
    await page.locator("#menubtn").click();
    await page.locator("#mrestart").click();
    await page.locator("#soyes").click();
    await expect(page.locator("#clock")).toHaveText("0:00");
    await openTile(page, withHint.id);
    await expect(page.locator("#lenshintbtn")).toBeVisible();
    await expect(page.locator("#lenshint")).toBeHidden();
  });
});

test.describe("a hunt with no hints", () => {
  test("has no ? button anywhere", async ({ page }) => {
    await prepare(page);
    await withName(page);
    stubBoard(page);
    await page.goto("fixture-plain/");
    await page.locator("#grid .tile").first().click();
    await expect(page.locator("#lens")).toBeVisible();
    await expect(page.locator("#lenshintbtn")).toBeHidden();
    await expect(page.locator("#lenshint")).toBeHidden();
  });
});
