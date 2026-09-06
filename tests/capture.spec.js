// The capture page, with the fake camera and a stubbed Supabase.
const { test, expect } = require("@playwright/test");
const { prepare } = require("./helpers");

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
    const slug = page.locator("input[placeholder='hunt']");
    const clue = page.locator("input[placeholder='clue']");
    await expect(slug).toBeVisible();
    await expect(clue).toBeVisible();
    const shutter = page.locator("#shutter");
    await expect(shutter).toBeDisabled();
    await expect(page.locator("#count")).toHaveText("0");
    // No words but the placeholders.
    const words = await page.evaluate(() => document.body.innerText.replace(/\s+/g, " ").trim());
    expect(words.replace(/Treasure\s*Hunt/i, "").replace("0", "").trim()).toBe("");
    await slug.fill("Trafalgar");
    await expect(shutter).toBeEnabled();
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
    expect(rows[0].body).toEqual({ hunt: "trafalgar", path, clue: "Between the fountains, looking north.",
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
});
