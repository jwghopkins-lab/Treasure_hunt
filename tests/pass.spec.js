// The pass by Skip: Complete!, the return to the main screen, the tile, the
// meter, Congratulations, the frozen clock, and the ticks.
const { test, expect } = require("@playwright/test");
const { hunt, prepare, withName, stubBoard, wordsOn } = require("./helpers");

const FIX = hunt("fixture");

async function skipTile(page, id) {
  await page.locator(`#grid .tile[data-id="${id}"]`).click();
  await expect(page.locator("#lens")).toBeVisible();
  await page.locator("#lensskip").click();
}

test.describe("the pass", () => {
  let log = null;
  test.beforeEach(async ({ page }) => {
    await prepare(page);
    await withName(page);
    log = stubBoard(page);
    await page.goto("fixture/");
    await expect(page.locator("#s-main")).toBeVisible();
  });

  test("shows Complete! and returns by itself within two seconds with the tile green", async ({ page }) => {
    const id = FIX.stencils[0].id;
    await skipTile(page, id);
    const t0 = Date.now();
    await expect(page.locator("#lenswash")).toBeVisible();
    await expect(page.locator("#lenswash")).toHaveText("Complete!");
    await expect(page.locator("#lens")).toBeHidden({ timeout: 2000 });
    expect(Date.now() - t0).toBeLessThan(2000);
    // A skip is recorded as a skip, on no line, once the screen has gone.
    await expect.poll(() => log.attempts.length, { timeout: 5000 }).toBe(1);
    expect(log.attempts[0]).toMatchObject({ outcome: "skip", line: null, stencil: id, hunt: "fixture" });
    const tile = page.locator(`#grid .tile[data-id="${id}"]`);
    await expect(tile).toHaveClass(/passed/);
    await expect(tile.locator(".badge svg")).toHaveCount(1);
    const good = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--good").trim());
    const colour = await tile.evaluate((el) => getComputedStyle(el).borderTopColor);
    const hex = (c) => "#" + c.match(/\d+/g).slice(0, 3).map((n) => (+n).toString(16).padStart(2, "0")).join("").toUpperCase();
    expect(hex(colour)).toBe(good.toUpperCase());
    // The meter moved: one of six.
    const bar = await page.locator("#topbar .mbar").boundingBox();
    const fill = await page.locator("#progressfill").boundingBox();
    expect(fill.width).toBeCloseTo(bar.width / FIX.stencils.length, 0);
    // The pass is stored with its time, and a passed tile opens nothing.
    const st = await page.evaluate(() => window.__th.state());
    expect(typeof st.done[id]).toBe("number");
    expect(st.started[id]).toBeUndefined();
    await tile.click();
    await page.waitForTimeout(300);
    await expect(page.locator("#lens")).toBeHidden();
  });

  test("a tap on the wash returns at once with a strong tick", async ({ page }) => {
    const id = FIX.stencils[1].id;
    await skipTile(page, id);
    await expect(page.locator("#lenswash")).toBeVisible();
    await page.locator("#lenswash").click();
    await expect(page.locator("#lens")).toBeHidden({ timeout: 400 });
    const vibes = await page.evaluate(() => window.__vibes);
    const last = vibes[vibes.length - 1];
    expect(last.p).toEqual([60, 50, 60]);
    expect(last.inTap).toBe(true);
    await expect(page.locator(`#grid .tile[data-id="${id}"]`)).toHaveClass(/passed/);
  });

  test("every tap ticks inside the tap; a tile tap is a single pulse", async ({ page }) => {
    await page.locator("#grid .tile").first().click();
    let vibes = await page.evaluate(() => window.__vibes);
    expect(vibes.length).toBe(1);
    expect(vibes[0]).toEqual({ p: 50, inTap: true });
    await page.locator("#lensback").click();
    vibes = await page.evaluate(() => window.__vibes);
    expect(vibes.length).toBe(2);
    expect(vibes[1]).toEqual({ p: 50, inTap: true });
    await page.locator("#menubtn").click();
    await page.locator("#mclose").click();
    vibes = await page.evaluate(() => window.__vibes);
    expect(vibes.length).toBe(4);
    expect(vibes.every((v) => v.p === 50 && v.inTap)).toBe(true);
  });

  test("all passed shows Congratulations and freezes the clock", async ({ page }) => {
    for (const s of FIX.stencils) {
      await skipTile(page, s.id);
      await page.locator("#lenswash").click();
      await expect(page.locator("#lens")).toBeHidden();
    }
    await expect(page.locator("#finish")).toBeVisible();
    await expect(page.locator(".congrats")).toHaveText("Congratulations!");
    await expect(page.locator("#progressfill")).toHaveAttribute("style", /width: 100%/);
    const t1 = await page.locator("#clock").textContent();
    await page.waitForTimeout(2200);
    const t2 = await page.locator("#clock").textContent();
    expect(t2).toBe(t1);
    const st = await page.evaluate(() => window.__th.state());
    const fin = Math.max(...Object.values(st.done)) - st.startedAt;
    const m = Math.floor(fin / 60000), s = Math.floor(fin / 1000) % 60;
    expect(t1).toBe(`${m}:${String(s).padStart(2, "0")}`);
    // The reload rebuilds the finished page: still frozen, still congratulating.
    await page.reload();
    await expect(page.locator(".congrats")).toBeVisible();
    await expect(page.locator("#clock")).toHaveText(t1);
    for (const s of FIX.stencils) await expect(page.locator(`#grid .tile[data-id="${s.id}"]`)).toHaveClass(/passed/);
  });

  test("a reload changes nothing: started, passed and the clock come back from state", async ({ page }) => {
    await skipTile(page, FIX.stencils[2].id);
    await page.locator("#lenswash").click();
    await page.locator(`#grid .tile[data-id="${FIX.stencils[3].id}"]`).click();
    await page.locator("#lensback").click();
    await page.reload();
    await expect(page.locator(`#grid .tile[data-id="${FIX.stencils[2].id}"]`)).toHaveClass(/passed/);
    await expect(page.locator(`#grid .tile[data-id="${FIX.stencils[3].id}"]`)).toHaveClass(/started/);
    await expect(page.locator(`#grid .tile[data-id="${FIX.stencils[0].id}"]`)).not.toHaveClass(/started|passed/);
    await expect(page.locator("#clock")).not.toHaveText("0:00");
  });
});

test.describe("test mode off", () => {
  test("there is no Skip anywhere", async ({ page }) => {
    await prepare(page);
    await withName(page);
    stubBoard(page);
    await page.goto("fixture-plain/");
    await page.locator("#grid .tile").first().click();
    await expect(page.locator("#lens")).toBeVisible();
    await expect(page.locator("#lensskip")).toHaveCount(0);
    expect(await page.evaluate(() => document.body.innerText.includes("Skip"))).toBe(false);
    await page.locator("#lensback").click();
    await page.locator("#menubtn").click();
    expect(await page.locator("#modalcard").innerText()).not.toContain("Skip");
    expect(await page.locator("#modalcard").innerText()).not.toContain("tick");
  });
});
