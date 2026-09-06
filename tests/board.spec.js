// The leaderboard, against a stubbed Supabase: the post on the last pass, a
// post that fails then succeeds on reload, and the board with the player's
// own row marked.
const { test, expect } = require("@playwright/test");
const { hunt, prepare, withName, stubBoard, wordsOn } = require("./helpers");

const FIX = hunt("fixture");

async function passAll(page) {
  for (const s of FIX.stencils) {
    await page.locator(`#grid .tile[data-id="${s.id}"]`).click();
    await page.locator("#lensskip").click();
    await page.locator("#lenswash").click();
    await expect(page.locator("#lens")).toBeHidden();
  }
}
function fmt(ms) {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

test.describe("the leaderboard", () => {
  test("posts the run on the last pass and shows the board with the player's row marked", async ({ page }) => {
    const errors = await prepare(page);
    await withName(page, "Ada");
    const log = stubBoard(page, {
      rows: (l) => {
        const mine = l.posts[0] ? l.posts[0].body : { run_id: "none", ms: 0 };
        return [{ run_id: "r-1", name: "Fast Eddie", ms: 61000 },
                { run_id: mine.run_id, name: "Ada", ms: mine.ms },
                { run_id: "r-3", name: "Slow Coach", ms: 3725000 }];
      },
    });
    await page.goto("fixture/");
    await passAll(page);
    await expect.poll(() => log.posts.length).toBe(1);
    const post = log.posts[0];
    expect(post.headers.apikey).toBe("stub-anon-key");
    expect(post.headers.authorization).toBe("Bearer stub-anon-key");
    expect(post.headers["content-type"]).toBe("application/json");
    expect(post.headers.prefer).toBe("return=minimal");
    expect(post.body.hunt).toBe("fixture");
    expect(post.body.name).toBe("Ada");
    expect(post.body.run_id).toMatch(/^[0-9a-f-]{36}$/);
    const st = await page.evaluate(() => window.__th.state());
    expect(post.body.ms).toBe(Math.max(...Object.values(st.done)) - st.startedAt);
    expect(post.body.run_id).toBe(st.run_id);

    await expect(page.locator("#board li")).toHaveCount(3);
    await expect(page.locator("#board li.me")).toHaveCount(1);
    await expect(page.locator("#board li.me")).toHaveAttribute("data-run", st.run_id);
    await expect(page.locator("#board li").nth(0)).toContainText("1");
    await expect(page.locator("#board li").nth(0)).toContainText("Fast Eddie");
    await expect(page.locator("#board li").nth(0)).toContainText("1:01");
    await expect(page.locator("#board li").nth(2)).toContainText("1:02:05");
    await expect(page.locator("#owntime")).toHaveText(fmt(post.body.ms));
    await expect(page.locator("#board li.me .who")).toHaveText("Ada");
    const accent = await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--accent").trim());
    const colour = await page.locator("#board li.me").evaluate((el) => getComputedStyle(el).color);
    const hex = (c) => "#" + c.match(/\d+/g).slice(0, 3).map((n) => (+n).toString(16).padStart(2, "0")).join("").toUpperCase();
    expect(hex(colour)).toBe(accent.toUpperCase());
    expect(await page.evaluate(() => window.__th.state().posted)).toBe(true);
    // A reload of a finished walk fetches again and does not post again.
    await page.reload();
    await expect(page.locator("#board li")).toHaveCount(3);
    expect(log.posts.length).toBe(1);
    expect(log.gets).toBe(2);
    expect(errors).toEqual([]);
  });

  test("a post that fails leaves the board empty, and a reload posts it and shows it", async ({ page }) => {
    await prepare(page);
    await withName(page, "Ada");
    const log = stubBoard(page, {
      failPost: (n) => n === 1,
      rows: (l) => l.posts.length >= 2 ? [{ run_id: l.posts[1].body.run_id, name: "Ada", ms: l.posts[1].body.ms }] : [],
    });
    await page.goto("fixture/");
    await passAll(page);
    await expect.poll(() => log.posts.length).toBe(1);
    await page.waitForTimeout(400);
    await expect(page.locator(".congrats")).toBeVisible();
    await expect(page.locator("#board li")).toHaveCount(0);
    expect(await page.evaluate(() => window.__th.state().posted)).toBeUndefined();
    // No error text: only the line and the time.
    const words = await wordsOn(page, "#finish");
    expect(words).toMatch(/^Congratulations! \d+:\d\d$/);
    await page.reload();
    await expect.poll(() => log.posts.length).toBe(2);
    expect(log.posts[1].body.run_id).toBe(log.posts[0].body.run_id);
    await expect(page.locator("#board li.me")).toHaveCount(1);
    expect(await page.evaluate(() => window.__th.state().posted)).toBe(true);
  });

  test("a 409 counts as posted", async ({ page }) => {
    await prepare(page);
    await withName(page, "Ada");
    await page.route("https://stub.supabase.co/**", (route) => {
      if (route.request().method() === "POST") return route.fulfill({ status: 409, body: "" });
      return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
    });
    await page.goto("fixture/");
    await passAll(page);
    await expect.poll(() => page.evaluate(() => window.__th.state().posted)).toBe(true);
  });

  test("a board that cannot be fetched is simply empty", async ({ page }) => {
    await prepare(page);
    await withName(page, "Ada");
    stubBoard(page, { failGet: true });
    await page.goto("fixture/");
    await passAll(page);
    await page.waitForTimeout(600);
    await expect(page.locator(".congrats")).toBeVisible();
    await expect(page.locator("#board li")).toHaveCount(0);
    expect(await wordsOn(page, "#finish")).toMatch(/^Congratulations! \d+:\d\d$/);
  });

  test("without the config there is no board, no time, and no request", async ({ page }) => {
    const errors = await prepare(page);
    const requests = [];
    page.on("request", (r) => { if (!r.url().startsWith("http://127.0.0.1:8765/")) requests.push(r.url()); });
    await page.goto("fixture-nosb/");
    await passAll(page);
    await expect(page.locator(".congrats")).toBeVisible();
    await expect(page.locator("#board")).toBeHidden();
    await expect(page.locator("#owntime")).toBeHidden();
    expect(await wordsOn(page, "#finish")).toBe("Congratulations!");
    await page.waitForTimeout(300);
    expect(requests).toEqual([]);
    expect(errors).toEqual([]);
  });
});
