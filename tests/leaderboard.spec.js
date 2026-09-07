// The board the player can open at any time: the run's row upserted as it
// goes, and everyone's row read back.
const { test, expect } = require("@playwright/test");
const { hunt, prepare, withName, wordsOn } = require("./helpers");

const FIX = hunt("fixture");
const withHint = FIX.stencils.find((s) => s.hint);

// The Supabase stub for this suite: the progress table, and enough of
// completions to keep the finish board's own sync quiet.
function stubRuns(page, opts) {
  const o = Object.assign({ rows: [], failPost: false, failGet: false }, opts || {});
  const log = { posts: [], gets: 0, getUrls: [], seq: [] };
  page.route("https://stub.supabase.co/**", async (route) => {
    const req = route.request();
    const url = req.url();
    if (url.includes("/rest/v1/progress")) {
      if (req.method() === "POST") {
        log.posts.push({ body: req.postDataJSON(), headers: req.headers() });
        log.seq.push("post");
        if (o.failPost === true || (typeof o.failPost === "function" && o.failPost(log.posts.length))) {
          return route.fulfill({ status: 500, body: "nope" });
        }
        return route.fulfill({ status: 201, body: "" });
      }
      log.gets += 1;
      log.getUrls.push(url);
      log.seq.push("get");
      if (o.failGet === true || (typeof o.failGet === "function" && o.failGet(log.gets))) {
        return route.fulfill({ status: 500, body: "nope" });
      }
      return route.fulfill({ status: 200, contentType: "application/json",
                             body: JSON.stringify(typeof o.rows === "function" ? o.rows(log) : o.rows) });
    }
    if (url.includes("/rest/v1/completions")) {
      if (req.method() === "POST") return route.fulfill({ status: 201, body: "" });
      return route.fulfill({ status: 200, contentType: "application/json", body: "[]" });
    }
    return route.fulfill({ status: 404, body: "" });
  });
  return log;
}

async function passTile(page, id) {
  await page.locator(`#grid .tile[data-id="${id}"]`).click();
  await expect(page.locator("#lens")).toBeVisible();
  await page.locator("#lensskip").click();
  await page.locator("#lenswash").click();
  await expect(page.locator("#lens")).toBeHidden();
}
function fmt(ms) {
  const s = Math.floor(ms / 1000);
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

test.describe("the board button", () => {
  test("is beside the map button and the menu, and carries no word", async ({ page }) => {
    const errors = await prepare(page);
    await withName(page, "Ada");
    stubRuns(page);
    await page.goto("fixture/");
    await expect(page.locator("#boardbtn")).toBeVisible();
    await expect(page.locator("#boardbtn svg")).toHaveCount(1);
    expect(await page.locator("#boardbtn").innerText()).toBe("");
    const board = await page.locator("#boardbtn").boundingBox();
    const menu = await page.locator("#menubtn").boundingBox();
    const map = await page.locator("#mapbtn").boundingBox();
    expect(board.width).toBeCloseTo(menu.width, 0);
    expect(board.height).toBeCloseTo(menu.height, 0);
    expect(board.x).toBeGreaterThan(map.x);
    expect(board.x).toBeLessThan(menu.x);
    // The header gained a button and no word.
    expect(await wordsOn(page, "#s-main")).toBe(FIX.name);
    expect(errors).toEqual([]);
  });

  test("is not there without a config, and nothing is asked for", async ({ page }) => {
    const errors = await prepare(page);
    const requests = [];
    page.on("request", (r) => { if (!r.url().startsWith("http://127.0.0.1:8765/")) requests.push(r.url()); });
    await page.goto("fixture-nosb/");
    await expect(page.locator("#s-main")).toBeVisible();
    await expect(page.locator("#boardbtn")).toBeHidden();
    await page.locator("#grid .tile").first().click();
    await page.locator("#lensskip").click();
    await page.locator("#lenswash").click();
    await page.waitForTimeout(300);
    expect(requests).toEqual([]);
    expect(errors).toEqual([]);
  });
});

test.describe("the run's row", () => {
  test("is upserted on a pass, with the time the clock shows, and again on the next pass", async ({ page }) => {
    const errors = await prepare(page);
    await withName(page, "Ada");
    const log = stubRuns(page);
    await page.goto("fixture/");
    // Nothing is said before the run has started.
    await page.waitForTimeout(300);
    expect(log.posts.length).toBe(0);

    // A hint first, so the posted time carries the penalty the clock carries.
    await page.locator(`#grid .tile[data-id="${withHint.id}"]`).click();
    await page.locator("#lenshintbtn").click();
    await page.locator("#lensskip").click();
    await page.locator("#lenswash").click();
    await expect(page.locator("#lens")).toBeHidden();
    await expect.poll(() => log.posts.length).toBe(1);

    const post = log.posts[0];
    expect(post.headers.apikey).toBe("stub-anon-key");
    expect(post.headers.authorization).toBe("Bearer stub-anon-key");
    expect(post.headers["content-type"]).toBe("application/json");
    expect(post.headers.prefer).toBe("resolution=merge-duplicates,return=minimal");
    const st = await page.evaluate(() => window.__th.state());
    expect(post.body.run_id).toBe(await page.evaluate(() => window.__th.boardId()));
    expect(post.body.run_id).toMatch(/^[0-9a-f-]{36}$/);
    expect(post.body.hunt).toBe("fixture");
    expect(post.body.name).toBe("Ada");
    expect(post.body.done).toBe(1);
    expect(post.body.total).toBe(FIX.stencils.length);
    expect(post.body.ms).toBeGreaterThanOrEqual(30000);
    expect(post.body.ms).toBeLessThan(40000);

    const later = FIX.stencils.find((s) => s.id !== withHint.id);
    await passTile(page, later.id);
    await expect.poll(() => log.posts.length).toBe(2);
    expect(log.posts[1].body.run_id).toBe(await page.evaluate(() => window.__th.boardId()));
    expect(log.posts[1].body.done).toBe(2);
    expect(log.posts[1].body.ms).toBeGreaterThanOrEqual(post.body.ms);
    expect(errors).toEqual([]);
  });

  test("is sent again on the next load of a run that has been started", async ({ page }) => {
    await prepare(page);
    await withName(page, "Ada");
    const log = stubRuns(page);
    await page.goto("fixture/");
    await page.locator("#grid .tile").first().click();
    await page.locator("#lensback").click();
    await page.waitForTimeout(300);
    expect(log.posts.length).toBe(0);      // started, nothing passed, nothing posted yet
    await page.reload();
    await expect.poll(() => log.posts.length).toBe(1);
    expect(log.posts[0].body.done).toBe(0);
    expect(log.posts[0].body.total).toBe(FIX.stencils.length);
    expect(log.posts[0].body.ms).toBeGreaterThan(0);
  });

  test("is capped at the day the server allows, and carries the time it was sent", async ({ page }) => {
    await prepare(page);
    await withName(page, "Ada");
    // A run started the evening before last and opened again this morning:
    // the clock has run past the ms column's ceiling.
    await page.addInitScript(() => {
      localStorage.setItem("treasure.fixture.state", JSON.stringify({
        startedAt: Date.now() - 30 * 3600 * 1000, started: {}, done: {}, hints: {},
        run_id: "11111111-2222-4333-8444-555555555555",
      }));
    });
    const log = stubRuns(page);
    const before = Date.now();
    await page.goto("fixture/");
    await expect.poll(() => log.posts.length).toBe(1);
    const body = log.posts[0].body;
    expect(body.ms).toBe(86400000);
    expect(body.done).toBe(0);
    // updated_at is sent because the column's default only fires on the insert.
    expect(Date.parse(body.updated_at)).toBeGreaterThanOrEqual(before - 2000);
    expect(Date.parse(body.updated_at)).toBeLessThanOrEqual(Date.now() + 2000);
  });

  test("is final once the run is finished: the same time on the pass and on a reload", async ({ page }) => {
    await prepare(page);
    await withName(page, "Ada");
    const log = stubRuns(page);
    await page.goto("fixture/");
    for (const s of FIX.stencils) await passTile(page, s.id);
    await expect(page.locator(".congrats")).toBeVisible();
    await expect.poll(() => log.posts.length).toBe(FIX.stencils.length);
    const last = log.posts[log.posts.length - 1].body;
    expect(last.done).toBe(FIX.stencils.length);
    expect(last.total).toBe(FIX.stencils.length);
    await expect(page.locator("#clock")).toHaveText(fmt(last.ms));
    await page.reload();
    await expect.poll(() => log.posts.length).toBe(FIX.stencils.length + 1);
    const after = log.posts[log.posts.length - 1].body;
    expect(after.ms).toBe(last.ms);
    expect(after.done).toBe(FIX.stencils.length);
  });

  test("a post that fails is silent and blocks nothing", async ({ page }) => {
    const errors = await prepare(page);
    await withName(page, "Ada");
    const log = stubRuns(page, { failPost: (n) => n === 1 });
    await page.goto("fixture/");
    await passTile(page, FIX.stencils[0].id);
    await expect.poll(() => log.posts.length).toBe(1);
    await expect(page.locator(`#grid .tile[data-id="${FIX.stencils[0].id}"]`)).toHaveClass(/passed/);
    await expect(page.locator("#clock")).not.toHaveText("0:00");
    expect(await wordsOn(page, "#s-main")).toBe(FIX.name);
    // The next pass sends it again, with the ground it has gained since.
    await passTile(page, FIX.stencils[1].id);
    await expect.poll(() => log.posts.length).toBe(2);
    expect(log.posts[1].body.done).toBe(2);
    expect(errors).toEqual([]);
  });
});

test.describe("the board screen", () => {
  test("opens on the button, fetches, and closes leaving the main screen as it was", async ({ page }) => {
    const errors = await prepare(page);
    await withName(page, "Ada");
    const log = stubRuns(page, { rows: [{ run_id: "r-1", name: "Bo", done: 2, total: 6, ms: 120000 }] });
    await page.goto("fixture/");
    await passTile(page, FIX.stencils[0].id);
    const before = await page.evaluate(() => window.__geo);
    const clock = await page.locator("#clock").textContent();

    await expect(page.locator("#s-board")).toBeHidden();
    await page.locator("#boardbtn").click();
    await expect(page.locator("#s-board")).toBeVisible();
    await expect(page.locator("#boardback")).toHaveText("←");
    await expect(page.locator("#fullboard li")).toHaveCount(1);
    await expect.poll(() => log.gets).toBe(1);
    // The screen fills it and asks for no position of its own.
    const vp = page.viewportSize();
    const box = await page.locator("#s-board").boundingBox();
    expect(box.width).toBeCloseTo(vp.width, 0);
    expect(await page.evaluate(() => window.__geo)).toEqual(before);

    await page.locator("#boardback").click();
    await expect(page.locator("#s-board")).toBeHidden();
    await expect(page.locator("#s-main")).toBeVisible();
    await expect(page.locator("#grid .tile")).toHaveCount(FIX.stencils.length);
    await expect(page.locator(`#grid .tile[data-id="${FIX.stencils[0].id}"]`)).toHaveClass(/passed/);
    expect(await page.evaluate(() => window.__geo)).toEqual(before);
    // The clock kept going while the board was over it.
    await expect(page.locator("#clock")).not.toHaveText(clock, { timeout: 4000 });
    expect(await wordsOn(page, "#s-main")).toBe(FIX.name);
    expect(errors).toEqual([]);
  });

  test("posts the run before it reads, so the player is on their own board", async ({ page }) => {
    const errors = await prepare(page);
    await withName(page, "Ada");
    // The board is whatever has been posted, so the player's own row is there
    // only if the run posted itself on the way in.
    const log = stubRuns(page, {
      rows: (l) => l.posts.map((p) => ({ run_id: p.body.run_id, name: p.body.name,
                                         done: p.body.done, total: p.body.total, ms: p.body.ms }))
                    .concat([{ run_id: "r-1", name: "Bo", done: 2, total: 6, ms: 120000 }]),
    });
    await page.goto("fixture/");
    // Started and nothing passed: on the old page there was no row at all.
    await page.locator("#grid .tile").first().click();
    await page.locator("#lensback").click();
    await page.waitForTimeout(300);
    expect(log.posts.length).toBe(0);

    await page.locator("#boardbtn").click();
    await expect(page.locator("#s-board")).toBeVisible();
    await expect(page.locator("#fullboard li.me")).toHaveCount(1);
    expect(log.seq).toEqual(["post", "get"]);
    const st = await page.evaluate(() => window.__th.state());
    expect(log.posts[0].body.run_id).toBe(await page.evaluate(() => window.__th.boardId()));
    expect(log.posts[0].body.done).toBe(0);
    // The player's own row carries the time the clock had as the board opened.
    await expect(page.locator("#fullboard li.me .when")).toHaveText(fmt(log.posts[0].body.ms));
    await expect(page.locator("#fullboard li.me .far")).toHaveText(`0/${FIX.stencils.length}`);
    expect(errors).toEqual([]);
  });

  test("asks the server for the fifty that belong on the board", async ({ page }) => {
    await prepare(page);
    await withName(page, "Ada");
    const log = stubRuns(page, { rows: [{ run_id: "r-1", name: "Bo", done: 2, total: 6, ms: 120000 }] });
    await page.goto("fixture/");
    await passTile(page, FIX.stencils[0].id);
    await page.locator("#boardbtn").click();
    await expect.poll(() => log.getUrls.length).toBe(1);
    // Without an order the limit would hand back fifty arbitrary rows.
    const url = decodeURIComponent(log.getUrls[0]);
    expect(url).toContain("order=done.desc,ms.asc");
    expect(url).toContain("limit=50");
    expect(url).toContain("hunt=eq.fixture");
  });

  test("ranks the finished above the rest, marks them, and marks the player's own row", async ({ page }) => {
    const errors = await prepare(page);
    await withName(page, "Ada");
    const mine = { id: null };
    stubRuns(page, {
      rows: () => [
        { run_id: "r-cleo", name: "Cleo", done: 6, total: 6, ms: 900000 },
        { run_id: "r-bo", name: "Bo", done: 3, total: 6, ms: 120000 },
        { run_id: mine.id, name: "Ada", done: 2, total: 6, ms: 300000 },
        { run_id: "r-dee", name: "Dee", done: 6, total: 6, ms: 600000 },
        { run_id: "r-eli", name: "Eli", done: 3, total: 6, ms: 90000 },
      ],
    });
    await page.goto("fixture/");
    await passTile(page, FIX.stencils[0].id);
    mine.id = await page.evaluate(() => window.__th.boardId());
    await page.locator("#boardbtn").click();

    const rows = page.locator("#fullboard li");
    await expect(rows).toHaveCount(5);
    // Finished first, by time; the rest by how far they have got, then time.
    const want = [["1", "Dee", "6/6", "10:00"], ["2", "Cleo", "6/6", "15:00"],
                  ["3", "Eli", "3/6", "1:30"], ["4", "Bo", "3/6", "2:00"],
                  ["5", "Ada", "2/6", "5:00"]];
    for (let i = 0; i < want.length; i++) {
      await expect(rows.nth(i).locator(".rank")).toHaveText(want[i][0]);
      await expect(rows.nth(i).locator(".who")).toHaveText(want[i][1]);
      await expect(rows.nth(i).locator(".far")).toHaveText(want[i][2]);
      await expect(rows.nth(i).locator(".when")).toHaveText(want[i][3]);
    }
    await expect(page.locator("#fullboard li.fin")).toHaveCount(2);
    await expect(rows.nth(0)).toHaveClass(/fin/);
    await expect(rows.nth(1)).toHaveClass(/fin/);
    await expect(rows.nth(2)).not.toHaveClass(/fin/);
    await expect(page.locator("#fullboard li.me")).toHaveCount(1);
    await expect(page.locator("#fullboard li.me")).toHaveAttribute("data-run", mine.id);
    await expect(rows.nth(4)).toHaveClass(/me/);
    await expect(rows.nth(0)).toHaveAttribute("data-run", "r-dee");

    const hex = (c) => "#" + c.match(/\d+/g).slice(0, 3).map((n) => (+n).toString(16).padStart(2, "0")).join("").toUpperCase();
    const token = (n) => page.evaluate((k) => getComputedStyle(document.documentElement).getPropertyValue(k).trim(), n);
    const accent = await token("--accent");
    const good = await token("--good");
    expect(hex(await rows.nth(4).evaluate((el) => getComputedStyle(el).color))).toBe(accent.toUpperCase());
    expect(hex(await rows.nth(0).locator(".far").evaluate((el) => getComputedStyle(el).color))).toBe(good.toUpperCase());
    expect(hex(await rows.nth(2).locator(".far").evaluate((el) => getComputedStyle(el).color))).not.toBe(good.toUpperCase());
    // Nothing on the screen is a word except the names.
    const text = await page.evaluate(() => document.getElementById("s-board").innerText);
    expect(text.replace(/←/g, "").replace(/[\d/:]+/g, " ").split(/\s+/).filter(Boolean).sort())
      .toEqual(["Ada", "Bo", "Cleo", "Dee", "Eli"]);
    expect(errors).toEqual([]);
  });

  test("a fetch that fails leaves the board as it was, and says nothing", async ({ page }) => {
    const errors = await prepare(page);
    await withName(page, "Ada");
    const log = stubRuns(page, { failGet: (n) => n === 1,
                                 rows: [{ run_id: "r-1", name: "Bo", done: 2, total: 6, ms: 120000 },
                                        { run_id: "r-2", name: "Cleo", done: 6, total: 6, ms: 300000 }] });
    await page.goto("fixture/");
    await passTile(page, FIX.stencils[0].id);
    await page.locator("#boardbtn").click();
    await expect(page.locator("#s-board")).toBeVisible();
    await expect.poll(() => log.gets).toBe(1);
    await page.waitForTimeout(400);
    // Empty the first time, with no spinner and no error text.
    await expect(page.locator("#fullboard li")).toHaveCount(0);
    expect(await page.evaluate(() => document.getElementById("s-board").innerText.replace("←", "").trim())).toBe("");

    await page.locator("#boardback").click();
    await page.locator("#boardbtn").click();
    await expect(page.locator("#fullboard li")).toHaveCount(2);
    // A later failure leaves the rows that are there.
    await page.locator("#boardback").click();
    await page.route("https://stub.supabase.co/**", (route) => {
      if (route.request().url().includes("/rest/v1/progress") && route.request().method() === "GET") {
        return route.fulfill({ status: 500, body: "nope" });
      }
      return route.fallback();
    });
    await page.locator("#boardbtn").click();
    await page.waitForTimeout(500);
    await expect(page.locator("#fullboard li")).toHaveCount(2);
    expect(errors).toEqual([]);
  });

  test("the tiles still work after the board has been opened and closed", async ({ page }) => {
    const errors = await prepare(page);
    await withName(page, "Ada");
    stubRuns(page, { rows: [{ run_id: "r-1", name: "Bo", done: 2, total: 6, ms: 120000 }] });
    await page.goto("fixture/");
    await page.locator("#boardbtn").click();
    await expect(page.locator("#s-board")).toBeVisible();
    await page.locator("#boardback").click();
    await expect(page.locator("#s-board")).toBeHidden();
    const id = FIX.stencils[2].id;
    await page.locator(`#grid .tile[data-id="${id}"]`).click();
    await expect(page.locator("#lens")).toBeVisible();
    await page.locator("#lensskip").click();
    await page.locator("#lenswash").click();
    await expect(page.locator("#lens")).toBeHidden();
    await expect(page.locator(`#grid .tile[data-id="${id}"]`)).toHaveClass(/passed/);
    await expect(page.locator("#grid .tile")).toHaveCount(FIX.stencils.length);
    expect(errors).toEqual([]);
  });

  test("a second attempt after Start over moves the same row rather than leaving a stale twin", async ({ page }) => {
    await prepare(page);
    await withName(page, "Ada");
    const log = stubRuns(page);
    await page.goto("fixture/");
    await expect(page.locator("#s-main")).toBeVisible();
    await page.locator("#grid .tile").first().click();
    await page.locator("#lensskip").click();
    await page.locator("#lenswash").click();
    await expect.poll(() => log.posts.length).toBeGreaterThanOrEqual(1);
    const first = await page.evaluate(() => window.__th.boardId());
    const runOne = (await page.evaluate(() => window.__th.state())).run_id;
    await page.locator("#menubtn").click();
    await page.locator("#mrestart").click();
    await page.locator("#soyes").click();
    await expect(page.locator("#clock")).toHaveText("0:00");
    await page.locator("#grid .tile").nth(1).click();
    await page.locator("#lensskip").click();
    await page.locator("#lenswash").click();
    await expect.poll(() => log.posts.length).toBeGreaterThanOrEqual(2);
    const last = log.posts[log.posts.length - 1].body;
    // The board id is the same, so the upsert moves the one row; the run's
    // own id is new, because a second attempt is a second time.
    expect(await page.evaluate(() => window.__th.boardId())).toBe(first);
    expect(last.run_id).toBe(first);
    expect(last.done).toBe(1);
    expect((await page.evaluate(() => window.__th.state())).run_id).not.toBe(runOne);
  });
});
