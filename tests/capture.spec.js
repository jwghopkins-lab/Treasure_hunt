// The capture page, with the fake camera and a stubbed Supabase.
const { test, expect } = require("@playwright/test");
const { prepare, ROOT, browserWithFeed, mobileContext, INIT } = require("./helpers");
const { execFileSync } = require("child_process");
const fs = require("fs");
const os = require("os");
const path = require("path");

// The size a JPEG says it is, from its start-of-frame marker.
function jpegSize(buf) {
  let i = 2;
  while (i < buf.length) {
    if (buf[i] !== 0xff) { i++; continue; }
    const m = buf[i + 1];
    if (m === 0xd8 || m === 0x01 || (m >= 0xd0 && m <= 0xd7)) { i += 2; continue; }
    const len = buf.readUInt16BE(i + 2);
    if (m === 0xc0 || m === 0xc1 || m === 0xc2) return [buf.readUInt16BE(i + 7), buf.readUInt16BE(i + 5)];
    i += 2 + len;
  }
  return null;
}

test.describe("the capture page", () => {
  test("uploads a JPEG of the stream's size to the expected path and inserts a row with the slug, the clue and the position", async ({ page, context }) => {
    const errors = await prepare(page);
    await context.setGeolocation({ latitude: 51.50787, longitude: -0.12812, accuracy: 9 });
    const uploads = [], rows = [];
    await page.route("https://stub.supabase.co/**", (route) => {
      const r = route.request();
      if (r.url().includes("/storage/v1/object/")) {
        uploads.push({ url: r.url(), headers: r.headers(), body: r.postDataBuffer() });
        return route.fulfill({ status: 200, contentType: "application/json", body: '{"Key":"ok"}' });
      }
      if (r.url().includes("/rest/v1/captures")) {
        rows.push({ headers: r.headers(), body: r.postDataJSON() });
        return route.fulfill({ status: 201, body: "" });
      }
      return route.fulfill({ status: 404, body: "" });
    });
    await page.goto("capture/");
    // The line under the count reads the fix the next shot will carry.
    await expect(page.locator("#fix")).toHaveText("\u00b19 m");
    const slug = page.locator("input[placeholder='hunt']");
    const clue = page.locator("input[placeholder='clue']");
    await expect(slug).toBeVisible();
    await expect(clue).toBeVisible();
    const shutter = page.locator("#shutter");
    await expect(shutter).toBeEnabled();
    await expect(page.locator("#count")).toHaveText("0");
    // A tap with no hunt typed says so, in the red flash, and takes nothing.
    await shutter.click();
    await expect(page.locator("#flash")).toContainText("hunt");
    await expect(page.locator("#count")).toHaveText("0");
    await page.waitForTimeout(3600);
    // No words but the placeholders and the fix line: the count and the
    // live reading are numbers, the fix line is the one line of words the
    // page keeps, and all three are taken out here.
    const words = await page.evaluate(() => {
      let text = document.body.innerText;
      for (const n of document.querySelectorAll("#count, #gaugenum, #fix")) text = text.replace(n.innerText, " ");
      return text.replace(/\s+/g, " ").trim();
    });
    expect(words.replace(/Treasure\s*Hunt/i, "").trim()).toBe("");
    await slug.fill("Trafalgar");
    await clue.fill("Between the fountains, looking north.");
    await page.waitForFunction(() => { const v = document.querySelector("video"); return v && v.videoWidth > 0; });
    await shutter.click();
    await expect.poll(() => rows.length).toBe(1);
    expect(uploads.length).toBe(1);
    expect(uploads[0].url).toMatch(/^https:\/\/stub\.supabase\.co\/storage\/v1\/object\/captures\/trafalgar\/\d{13}-[0-9a-f]{16}\.jpg$/);
    expect(uploads[0].headers["content-type"]).toBe("image/jpeg");
    expect(uploads[0].headers.apikey).toBe("stub-anon-key");
    expect(uploads[0].headers.authorization).toBe("Bearer stub-anon-key");
    expect(jpegSize(uploads[0].body)).toEqual([640, 480]);
    const path = uploads[0].url.replace("https://stub.supabase.co/storage/v1/object/captures/", "");
    expect(rows[0].headers["content-type"]).toBe("application/json");
    expect(rows[0].headers.prefer).toBe("return=minimal");
    expect(rows[0].body).toEqual({ judged: expect.any(Number), hunt: "trafalgar", path, clue: "Between the fountains, looking north.",
                                   lat: 51.50787, lon: -0.12812, accuracy: 9 });
    await expect(page.locator("#count")).toHaveText("1");
    await expect(clue).toHaveValue("");
    await expect(slug).toHaveValue("trafalgar");
    await expect(page.locator("#flash")).toBeVisible();
    await expect(shutter).toBeEnabled();
    // A second shot with no clue writes null, and the slug is remembered.
    await shutter.click();
    await expect.poll(() => rows.length).toBe(2);
    expect(rows[1].body.clue).toBeNull();
    await expect(page.locator("#count")).toHaveText("2");
    await page.reload();
    await expect(slug).toHaveValue("trafalgar");
    await expect(page.locator("#count")).toHaveText("0");
    expect(errors).toEqual([]);
  });

  test("a failed upload flashes red with the message and writes no row", async ({ page }) => {
    await prepare(page);
    const rows = [];
    await page.route("https://stub.supabase.co/**", (route) => {
      if (route.request().url().includes("/storage/")) return route.fulfill({ status: 403, body: '{"message":"new row violates row-level security policy"}' });
      rows.push(1);
      return route.fulfill({ status: 201, body: "" });
    });
    await page.goto("capture/");
    await page.locator("input[placeholder='hunt']").fill("x");
    await page.waitForFunction(() => { const v = document.querySelector("video"); return v && v.videoWidth > 0; });
    await page.locator("#shutter").click();
    await expect(page.locator("#flash")).toBeVisible();
    await expect(page.locator("#flash")).toContainText("403");
    await page.waitForTimeout(300);
    expect(rows.length).toBe(0);
    await expect(page.locator("#count")).toHaveText("0");
  });

  test("with the config absent the shutter downloads the JPEG and writes nothing", async ({ page }) => {
    const errors = await prepare(page);
    const requests = [];
    page.on("request", (r) => { if (!r.url().startsWith("http://127.0.0.1:8765/")) requests.push(r.url()); });
    await page.goto("capture-nosb/");
    await page.locator("input[placeholder='hunt']").fill("indoors");
    await page.waitForFunction(() => { const v = document.querySelector("video"); return v && v.videoWidth > 0; });
    const [download] = await Promise.all([
      page.waitForEvent("download"),
      page.locator("#shutter").click(),
    ]);
    expect(download.suggestedFilename()).toMatch(/^indoors-\d+\.jpg$/);
    await expect(page.locator("#count")).toHaveText("1");
    expect(requests).toEqual([]);
    expect(errors).toEqual([]);
  });

  test("asks for the camera with exactly the game's request", async ({ page }) => {
    await page.addInitScript(() => {
      window.__gum = [];
      const real = navigator.mediaDevices.getUserMedia.bind(navigator.mediaDevices);
      navigator.mediaDevices.getUserMedia = (c) => { window.__gum.push(JSON.parse(JSON.stringify(c))); return real(c); };
    });
    await page.goto("capture/");
    await expect.poll(() => page.evaluate(() => window.__gum.length)).toBe(1);
    expect(await page.evaluate(() => window.__gum[0])).toEqual({ video: { facingMode: { ideal: "environment" } }, audio: false });
    const fit = await page.locator("video").evaluate((v) => getComputedStyle(v).objectFit);
    expect(fit).toBe("contain");
  });

  test("a frame with nothing in it is refused with advice, and nothing goes up", async () => {
    test.setTimeout(60000);
    // A blank grey feed: no edges, so the verdict is that there is too
    // little in the frame. The count stays at nought and no request leaves.
    const browser = await browserWithFeed("grey.y4m");
    // No position in this context, so the line under the count says so.
    const context = await mobileContext(browser, { geolocation: undefined });
    const page = await context.newPage();
    await page.addInitScript(INIT);
    const requests = [];
    await page.route("https://stub.supabase.co/**", (route) => {
      requests.push(route.request().url());
      return route.fulfill({ status: 201, body: "" });
    });
    try {
      await page.goto("capture/");
      await page.locator("input[placeholder='hunt']").fill("Nowhere");
      await page.waitForFunction(() => { const v = document.querySelector("video"); return v && v.videoWidth > 0; });
      // The live reading of a blank frame is nought, in the red band.
      await expect(page.locator("#gaugenum")).toHaveText("0.00");
      await expect(page.locator("#gaugefill")).toHaveClass("bad");
      await expect(page.locator("#fix")).toHaveText("no location");
      await page.locator("#shutter").click();
      // The preview is in the flash, above the words, even for a shot that
      // was refused; for a blank frame it is an empty canvas.
      await expect(page.locator("#preview")).toBeVisible();
      await expect(page.locator("#flash")).toContainText("Not this one 0.00");
      await expect(page.locator("#flash")).toContainText("too little in the frame");
      await expect(page.locator("#count")).toHaveText("0");
      await page.waitForTimeout(500);
      expect(requests).toEqual([]);
      await expect(page.locator("#shutter")).toBeEnabled();
    } finally {
      await browser.close();
    }
  });

  test("a good photograph goes up with its verdict in the row, and the verdict is the audit's", async () => {
    test.setTimeout(120000);
    // The fixture door in the fake camera scores high; the row carries the
    // page's number, and that number is what pipeline/audit.py's assess()
    // says of the same photograph, to within what the resize costs.
    const out = path.join(os.tmpdir(), "assess-door.json");
    execFileSync("python3", ["-c", `
import sys, json
sys.path.insert(0, "pipeline")
import audit
print(json.dumps(audit.assess(audit.upright("photos/fixture/door.jpg"))))`], { cwd: ROOT, stdio: ["ignore", fs.openSync(out, "w"), "inherit"] });
    const expected = JSON.parse(fs.readFileSync(out, "utf8"));
    const browser = await browserWithFeed("fixture-door.y4m");
    const context = await mobileContext(browser);
    const page = await context.newPage();
    await page.addInitScript(INIT);
    const rows = [];
    await page.route("https://stub.supabase.co/**", (route) => {
      const r = route.request();
      if (r.url().includes("/rest/v1/captures")) { rows.push(r.postDataJSON()); return route.fulfill({ status: 201, body: "" }); }
      return route.fulfill({ status: 200, contentType: "application/json", body: '{"Key":"ok"}' });
    });
    try {
      await page.goto("capture/");
      await page.locator("input[placeholder='hunt']").fill("Somewhere");
      await page.waitForFunction(() => { const v = document.querySelector("video"); return v && v.videoWidth > 0; });
      // The live reading, before any shot: the door is well into the green.
      await expect(page.locator("#gaugefill")).toHaveClass("good");
      const live = Number(await page.locator("#gaugenum").textContent());
      expect(live).toBeGreaterThan(0.5);
      expect(Math.abs(live - expected.score)).toBeLessThanOrEqual(0.03);
      await page.locator("#shutter").click();
      // The preview first, since it goes with the flash: the stencil's
      // shape, white, a canvas the size of the working frame with ink on it.
      const preview = page.locator("#preview");
      await expect(preview).toBeVisible();
      const inked = await preview.evaluate((c) => {
        const d = c.getContext("2d").getImageData(0, 0, c.width, c.height).data;
        let n = 0; for (let i = 3; i < d.length; i += 4) if (d[i]) n++;
        return { n, w: c.width, h: c.height };
      });
      expect(inked.w).toBe(240); expect(inked.h).toBe(320);
      expect(inked.n).toBeGreaterThan(1000);
      await expect.poll(() => rows.length).toBe(1);
      await expect(page.locator("#count")).toHaveText("1");
      expect(rows[0].judged).toBeGreaterThan(0.54);
      // The flash says it went up, with its number, and nothing about a
      // location: this context holds a fix.
      await expect(page.locator("#flashmsg")).toHaveText("Saved " + rows[0].judged.toFixed(2) + ".");
      await expect(page.locator("#fix")).toHaveText("\u00b120 m");
      // And the flash goes, the preview with it.
      await expect(preview).toBeHidden({ timeout: 8000 });
      expect(Math.abs(rows[0].judged - expected.score)).toBeLessThanOrEqual(0.03);
      // The page's own reading of the photograph, off the same arithmetic.
      const judged = await page.evaluate(() => window.Lens.assess(document.querySelector("video")));
      expect(judged.frame).toBe("240x320");
      expect(judged.sparse).toBe(false);
    } finally {
      await browser.close();
    }
  });
});

