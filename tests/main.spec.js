// The main screen, the clock, the tiles, the menu and the name screen.
const { test, expect } = require("@playwright/test");
const { hunt, prepare, withName, stubBoard, wordsOn } = require("./helpers");

const FIX = hunt("fixture");

test.describe("the main screen", () => {
  test("shows the name, the clock at 0:00, three-per-row tiles and no other words", async ({ page }) => {
    const errors = await prepare(page);
    await withName(page);
    stubBoard(page);
    await page.goto("fixture/");
    await expect(page.locator("#s-main")).toBeVisible();
    await expect(page.locator("#huntname")).toHaveText(FIX.name);
    await expect(page).toHaveTitle(FIX.name);
    await expect(page.locator("#clock")).toHaveText("0:00");

    const tiles = page.locator("#grid .tile");
    await expect(tiles).toHaveCount(FIX.stencils.length);
    for (let i = 0; i < FIX.stencils.length; i++) {
      await expect(tiles.nth(i)).toHaveAttribute("data-id", FIX.stencils[i].id);
      await expect(tiles.nth(i).locator("img")).toHaveAttribute("src", FIX.stencils[i].src);
      await expect(tiles.nth(i)).not.toHaveClass(/started|passed/);
    }
    // Three to a row: the first three share a top edge and the fourth is below.
    const boxes = [];
    for (let i = 0; i < 4; i++) boxes.push(await tiles.nth(i).boundingBox());
    expect(boxes[0].y).toBeCloseTo(boxes[1].y, 0);
    expect(boxes[1].y).toBeCloseTo(boxes[2].y, 0);
    expect(boxes[3].y).toBeGreaterThan(boxes[0].y + boxes[0].height - 1);
    expect(boxes[0].width).toBeCloseTo(boxes[0].height, 0);
    // The tiles carry no numbers and the screen no other words.
    expect(await wordsOn(page, "#s-main")).toBe(FIX.name);
    await expect(page.locator("#finish")).toBeHidden();
    expect(errors).toEqual([]);
  });

  test("the first thumbnail tap starts the clock and a reload continues it", async ({ page }) => {
    const errors = await prepare(page);
    await withName(page);
    stubBoard(page);
    await page.goto("fixture/");
    await expect(page.locator("#clock")).toHaveText("0:00");
    await page.locator("#grid .tile").first().click();
    await expect(page.locator("#lens")).toBeVisible();
    const t0 = await page.evaluate(() => window.__th.state().startedAt);
    expect(typeof t0).toBe("number");
    await page.locator("#lensback").click();
    await expect(page.locator("#lens")).toBeHidden();
    await expect(page.locator("#clock")).toHaveText(/^0:0[1-9]$/, { timeout: 4000 });
    await page.waitForTimeout(1200);
    await page.reload();
    const t1 = await page.evaluate(() => window.__th.state().startedAt);
    expect(t1).toBe(t0);
    await expect(page.locator("#clock")).not.toHaveText("0:00");
    const shown = await page.locator("#clock").textContent();
    const secs = parseInt(shown.split(":")[1], 10);
    expect(secs).toBeGreaterThanOrEqual(2);
    expect(errors).toEqual([]);
  });

  test("back marks the tile amber and the clock keeps going", async ({ page }) => {
    await prepare(page);
    await withName(page);
    stubBoard(page);
    await page.goto("fixture/");
    const second = page.locator("#grid .tile").nth(1);
    await second.click();
    await page.locator("#lensback").click();
    await expect(second).toHaveClass(/started/);
    await expect(second).not.toHaveClass(/passed/);
    const border = await second.evaluate((el) => getComputedStyle(el).borderTopWidth);
    expect(border).toBe("3px");
    const amber = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--amber").trim());
    const colour = await second.evaluate((el) => getComputedStyle(el).borderTopColor);
    const hex = (c) => "#" + c.match(/\d+/g).slice(0, 3).map((n) => (+n).toString(16).padStart(2, "0")).join("").toUpperCase();
    expect(hex(colour)).toBe(amber.toUpperCase());
    await expect(page.locator("#progressfill")).toHaveCSS("width", "0px");
  });

  test("Start over confirms, forgets everything including the clock, and keeps the name", async ({ page }) => {
    await prepare(page);
    await withName(page, "Grace");
    stubBoard(page);
    await page.goto("fixture/");
    await page.locator("#grid .tile").first().click();
    await page.locator("#lensback").click();
    await expect(page.locator("#grid .tile").first()).toHaveClass(/started/);
    await page.locator("#menubtn").click();
    await expect(page.locator("#modal")).toBeVisible();
    await page.locator("#mrestart").click();
    await expect(page.locator("#soyes")).toBeVisible();
    await page.locator("#sono").click();      // the confirm can be declined
    await expect(page.locator("#modal")).toBeHidden();
    await expect(page.locator("#grid .tile").first()).toHaveClass(/started/);
    await page.locator("#menubtn").click();
    await page.locator("#mrestart").click();
    await page.locator("#soyes").click();
    await expect(page.locator("#modal")).toBeHidden();
    await expect(page.locator("#clock")).toHaveText("0:00");
    await expect(page.locator("#grid .tile").first()).not.toHaveClass(/started|passed/);
    expect(await page.evaluate(() => localStorage.getItem("treasure.fixture.state"))).toBeNull();
    expect(await page.evaluate(() => localStorage.getItem("treasure.name"))).toBe("Grace");
    await page.reload();
    await expect(page.locator("#s-name")).toBeHidden();
    await expect(page.locator("#clock")).toHaveText("0:00");
  });

  test("the menu has Start over and nothing else; Test the tick only in test mode", async ({ page }) => {
    await prepare(page);
    await withName(page);
    stubBoard(page);
    await page.goto("fixture-plain/");
    await page.locator("#menubtn").click();
    await expect(page.locator("#mrestart")).toBeVisible();
    await expect(page.locator("#mtick")).toHaveCount(0);
    expect(await page.locator("#modalcard").innerText()).toMatch(/^Menu\s+Close\s+Start over$/);
    await page.locator("#mclose").click();
    await page.goto("fixture/");
    await page.locator("#menubtn").click();
    await expect(page.locator("#mtick")).toBeVisible();
    await page.locator("#mtick").click();
    await expect(page.locator("#tickinfo")).toContainText("vibrate:");
  });

  test("a hunt with no map has no map button", async ({ page }) => {
    await prepare(page);
    await withName(page);
    stubBoard(page);
    await page.goto("fixture-plain/");
    await expect(page.locator("#s-main")).toBeVisible();
    await expect(page.locator("#mapbtn")).toBeHidden();
    await page.goto("fixture/");
    await expect(page.locator("#mapbtn")).toBeVisible();
  });
});

test.describe("the name screen", () => {
  test("appears once, refuses an empty name, stores the trimmed name, and is not shown again", async ({ page }) => {
    const errors = await prepare(page);
    stubBoard(page);
    await page.goto("fixture/");
    await expect(page.locator("#s-name")).toBeVisible();
    await expect(page.locator("#s-main")).toBeHidden();
    await expect(page.locator("#huntname-name")).toHaveText(FIX.name);
    await expect(page.locator("#namebox")).toHaveAttribute("placeholder", "Your name");
    await expect(page.locator("#playbtn")).toHaveText("Play");
    await expect(page.locator("#playbtn")).toBeDisabled();
    await page.locator("#namebox").fill("   ");
    await expect(page.locator("#playbtn")).toBeDisabled();
    await page.locator("#namebox").fill("  Ada Lovelace  ");
    await expect(page.locator("#playbtn")).toBeEnabled();
    await page.locator("#playbtn").click();
    await expect(page.locator("#s-main")).toBeVisible();
    expect(await page.evaluate(() => localStorage.getItem("treasure.name"))).toBe("Ada Lovelace");
    await page.reload();
    await expect(page.locator("#s-main")).toBeVisible();
    await expect(page.locator("#s-name")).toBeHidden();
    expect(errors).toEqual([]);
  });

  test("a name is at most 24 characters", async ({ page }) => {
    await prepare(page);
    stubBoard(page);
    await page.goto("fixture/");
    await page.locator("#namebox").fill("x".repeat(40));
    await page.locator("#playbtn").click();
    expect(await page.evaluate(() => localStorage.getItem("treasure.name"))).toHaveLength(24);
  });

  test("without a Supabase config there is no name screen and no request", async ({ page }) => {
    const errors = await prepare(page);
    const requests = [];
    page.on("request", (r) => { if (!r.url().startsWith("http://127.0.0.1:8765/")) requests.push(r.url()); });
    await page.goto("fixture-nosb/");
    await expect(page.locator("#s-main")).toBeVisible();
    await expect(page.locator("#s-name")).toBeHidden();
    expect(await page.evaluate(() => window.__th.supabase)).toBeNull();
    expect(requests).toEqual([]);
    expect(errors).toEqual([]);
  });
});
