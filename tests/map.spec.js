// The map screen, both kinds.
const { test, expect } = require("@playwright/test");
const { hunt, prepare, withName, stubBoard } = require("./helpers");

const FIX = hunt("fixture");
const IMG = hunt("fixture-image");
const located = FIX.stencils.filter((s) => s.location);
const unlocated = FIX.stencils.filter((s) => !s.location);

// A one-pixel tile for every OpenStreetMap request, so the suite stays off
// the network and the tile policy is not troubled by tests.
const PNG = Buffer.from("iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAQAAAC1HAwCAAAAC0lEQVR42mNkYAAAAAYAAjCB0C8AAAAASUVORK5CYII=", "base64");
async function offlineTiles(page) {
  const tiles = [];
  await page.route("https://tile.openstreetmap.org/**", (route) => {
    tiles.push(route.request().url());
    return route.fulfill({ status: 200, contentType: "image/png", body: PNG });
  });
  return tiles;
}
const hex = (c) => "#" + c.match(/\d+/g).slice(0, 3).map((n) => (+n).toString(16).padStart(2, "0")).join("").toUpperCase();

// The circle markers on the map, by their fill colour and where they are.
async function circles(page) {
  return page.evaluate(() => {
    const map = window.__th.map();
    const out = [];
    map.eachLayer((l) => {
      if (l.getRadius && l.getLatLng && !(l instanceof L.Circle)) {
        const p = l.getLatLng();
        out.push({ id: l.stencilId || null, lat: p.lat, lon: p.lng, fill: l.options.fillColor,
                   radius: l.getRadius(), edge: l.options.color });
      }
    });
    return out;
  });
}

test.describe("the map screen, bounds kind", () => {
  test.beforeEach(async ({ page }) => {
    await prepare(page);
    await withName(page);
    stubBoard(page);
  });

  test("opens fitted to the hunt's bounds with a marker per located stencil, a ? tile per unlocated one, the player's dot and the attribution", async ({ page, context }) => {
    const tiles = await offlineTiles(page);
    const me = { latitude: 51.5075, longitude: -0.1660, accuracy: 12 };
    await context.setGeolocation(me);
    await page.goto("fixture/");
    // One passed, one started, before the map is opened.
    await page.locator(`#grid .tile[data-id="${located[0].id}"]`).click();
    await page.locator("#lensskip").click();
    await page.locator("#lenswash").click();
    await page.locator(`#grid .tile[data-id="${located[1].id}"]`).click();
    await page.locator("#lensback").click();

    const atOpen = await page.evaluate(() => window.__geo);
    await page.locator("#mapbtn").click();
    await expect(page.locator("#s-map")).toBeVisible();
    await expect(page.locator("#mapback")).toHaveText("←");
    await expect.poll(() => tiles.length).toBeGreaterThan(0);

    const [[s, w], [n, e]] = FIX.map.bounds;
    const b = await page.evaluate(() => {
      const bb = window.__th.map().getBounds();
      return { s: bb.getSouth(), w: bb.getWest(), n: bb.getNorth(), e: bb.getEast() };
    });
    // Contained, to within a pixel: Leaflet rounds the pixel origin of the fit.
    const tol = { lat: (n - s) / 400, lon: (e - w) / 400 };
    expect(b.s).toBeLessThanOrEqual(s + tol.lat);
    expect(b.n).toBeGreaterThanOrEqual(n - tol.lat);
    expect(b.w).toBeLessThanOrEqual(w + tol.lon);
    expect(b.e).toBeGreaterThanOrEqual(e - tol.lon);
    // Fitted: one of the two spans is the hunt's own, within a few percent;
    // the other is only as much bigger as the screen's shape makes it.
    const rLat = (b.n - b.s) / (n - s), rLon = (b.e - b.w) / (e - w);
    expect(Math.min(rLat, rLon)).toBeLessThan(1.08);
    expect(Math.max(rLat, rLon)).toBeLessThan(3.5);

    const marks = await circles(page);
    const good = (await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--good"))).trim().toUpperCase();
    const amber = (await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--amber"))).trim().toUpperCase();
    const accent = (await page.evaluate(() => getComputedStyle(document.documentElement).getPropertyValue("--accent"))).trim().toUpperCase();
    const stencilMarks = marks.filter((m) => m.id);
    expect(stencilMarks.map((m) => m.id).sort()).toEqual(located.map((l) => l.id).sort());
    for (const m of stencilMarks) {
      const st = located.find((l) => l.id === m.id);
      expect(m.lat).toBeCloseTo(st.location.lat, 6);
      expect(m.lon).toBeCloseTo(st.location.lon, 6);
      expect(m.edge).toBe("#fff");
      expect(m.radius).toBe(10);
      const want = m.id === located[0].id ? good : m.id === located[1].id ? amber : accent;
      expect(m.fill.toUpperCase()).toBe(want);
    }
    // The player: a blue dot at the mocked position.
    const dot = marks.find((m) => !m.id);
    expect(dot).toBeTruthy();
    expect(dot.lat).toBeCloseTo(me.latitude, 5);
    expect(dot.lon).toBeCloseTo(me.longitude, 5);
    expect(dot.fill).toBe("#2A7FFF");
    // The ? tiles along the bottom, in the hunt's order.
    const q = page.locator("#qrow .tile.q");
    await expect(q).toHaveCount(unlocated.length);
    for (let i = 0; i < unlocated.length; i++) {
      await expect(q.nth(i)).toHaveAttribute("data-id", unlocated[i].id);
      await expect(q.nth(i)).toContainText("?");
    }
    const vp = page.viewportSize();
    const qb = await q.first().boundingBox();
    expect(qb.y + qb.height).toBeGreaterThan(vp.height - 60);
    // The attribution, small, bottom-right; Leaflet's zoom buttons hidden.
    await expect(page.locator(".leaflet-control-attribution")).toContainText("OpenStreetMap");
    const ab = await page.locator(".leaflet-control-attribution").boundingBox();
    expect(ab.x + ab.width).toBeGreaterThan(vp.width - 4);
    await expect(page.locator(".leaflet-control-zoom")).toHaveCount(0);
    // No words on this screen beyond the attribution and the ? tiles.
    const words = await page.evaluate(() => {
      const el = document.getElementById("s-map").cloneNode(true);
      for (const n of el.querySelectorAll(".leaflet-control-attribution, #qrow")) n.remove();
      return el.innerText.replace(/\s+/g, " ").replace("←", "").trim();
    });
    expect(words).toBe("");
    // One watch for the map (the camera screens before it had their own,
    // each cleared), and it is cleared on back.
    const before = await page.evaluate(() => window.__geo);
    expect(before.watches).toBe(atOpen.watches + 1);
    expect(before.clears).toBe(atOpen.clears);
    await page.locator("#mapback").click();
    await expect(page.locator("#s-map")).toBeHidden();
    const after = await page.evaluate(() => window.__geo);
    expect(after.clears).toBe(before.clears + 1);
  });

  test("a marker tap opens a popup holding the thumbnail; so does a ? tile; the player's dot moves and a passed tile shows its tick", async ({ page, context }) => {
    await offlineTiles(page);
    await context.setGeolocation({ latitude: 51.5075, longitude: -0.1660, accuracy: 12 });
    await page.goto("fixture/");
    await page.locator(`#grid .tile[data-id="${unlocated[0].id}"]`).click();
    await page.locator("#lensskip").click();
    await page.locator("#lenswash").click();
    await page.locator("#mapbtn").click();
    await expect(page.locator("#s-map")).toBeVisible();
    const target = located[2];
    const pt = await page.evaluate((loc) => {
      const map = window.__th.map();
      const p = map.latLngToContainerPoint([loc.lat, loc.lon]);
      const r = map.getContainer().getBoundingClientRect();
      return { x: r.left + p.x, y: r.top + p.y };
    }, target.location);
    await page.mouse.click(pt.x, pt.y);
    await expect(page.locator(".leaflet-popup img")).toHaveAttribute("src", target.src);
    expect(await page.locator(".leaflet-popup-content").innerText()).toBe("");
    await page.locator(`#qrow .tile.q[data-id="${unlocated[0].id}"] .badge`).waitFor();
    await page.locator(`#qrow .tile.q[data-id="${unlocated[1].id}"]`).click();
    // The marker's popup fades out over 200 ms; wait until only the new one is there.
    await expect(page.locator(".leaflet-popup img")).toHaveCount(1);
    await expect(page.locator(".leaflet-popup img")).toHaveAttribute("src", unlocated[1].src);
    await page.evaluate(() => window.__th.map().closePopup());
    await page.waitForTimeout(300);
    // The map does not follow the player: a fix well away from the centre
    // moves the dot and nothing else.
    const centre = () => page.evaluate(() => { const c = window.__th.map().getCenter(); return [c.lat, c.lng]; });
    const c0 = await centre();
    await context.setGeolocation({ latitude: 51.5090, longitude: -0.1620, accuracy: 30 });
    await expect.poll(async () => (await circles(page)).find((m) => !m.id).lat).toBeCloseTo(51.5090, 5);
    await page.waitForTimeout(300);
    expect(await centre()).toEqual(c0);
  });

  test("tiles come from OpenStreetMap's standard server with a maximum zoom of 19", async ({ page }) => {
    const tiles = await offlineTiles(page);
    await page.goto("fixture/");
    await page.locator("#mapbtn").click();
    await expect.poll(() => tiles.length).toBeGreaterThan(0);
    expect(tiles[0]).toMatch(/^https:\/\/tile\.openstreetmap\.org\/\d+\/\d+\/\d+\.png$/);
    const maxZoom = await page.evaluate(() => { let z = null; window.__th.map().eachLayer((l) => { if (l.options && l.options.maxZoom && l.getTileUrl) z = l.options.maxZoom; }); return z; });
    expect(maxZoom).toBe(19);
  });
});

test.describe("the map screen, image kind", () => {
  test("shows the picture filling the screen, pans and pinches, with no marker, dot, ? row, attribution or watch", async ({ page, context }) => {
    const errors = await prepare(page);
    await withName(page);
    stubBoard(page);
    const requests = [];
    page.on("request", (r) => { if (/openstreetmap/.test(r.url())) requests.push(r.url()); });
    await context.setGeolocation({ latitude: 51.5075, longitude: -0.1660, accuracy: 12 });
    await page.goto("fixture-image/");
    await expect(page.locator("#mapbtn")).toBeVisible();
    await page.locator("#mapbtn").click();
    await expect(page.locator("#s-map")).toBeVisible();
    const img = page.locator("#mapview .leaflet-image-layer");
    await expect(img).toHaveAttribute("src", IMG.map.image);
    await expect(img).toBeVisible();
    const vp = page.viewportSize();
    await expect.poll(async () => { const b = await img.boundingBox(); return Math.max(b.width / vp.width, b.height / vp.height); }).toBeGreaterThan(0.97);
    const b0 = await img.boundingBox();
    expect(Math.abs(b0.x + b0.width / 2 - vp.width / 2)).toBeLessThan(3);
    expect(Math.abs(b0.y + b0.height / 2 - vp.height / 2)).toBeLessThan(3);

    expect(await circles(page)).toEqual([]);
    await expect(page.locator("#qrow")).toBeHidden();
    await expect(page.locator(".leaflet-control-attribution")).toHaveCount(0);
    await expect(page.locator(".leaflet-control-zoom")).toHaveCount(0);
    expect(await page.evaluate(() => window.__geo.watches)).toBe(0);
    expect(requests).toEqual([]);
    const words = await page.evaluate(() => document.getElementById("s-map").innerText.replace(/\s+/g, " ").replace("←", "").trim());
    expect(words).toBe("");

    // Pan with a drag: the picture moves.
    await page.mouse.move(vp.width / 2, vp.height / 2);
    await page.mouse.down();
    await page.mouse.move(vp.width / 2 - 120, vp.height / 2 - 80, { steps: 8 });
    await page.mouse.up();
    await page.waitForTimeout(400);
    const b1 = await img.boundingBox();
    expect(Math.abs(b1.x - b0.x) + Math.abs(b1.y - b0.y)).toBeGreaterThan(60);
    // Pinch with two fingers: the picture grows.
    const z0 = await page.evaluate(() => window.__th.map().getZoom());
    const cdp = await context.newCDPSession(page);
    const cx = vp.width / 2, cy = vp.height / 2;
    const touches = (d) => [{ x: cx - d, y: cy, id: 1 }, { x: cx + d, y: cy, id: 2 }];
    await cdp.send("Input.dispatchTouchEvent", { type: "touchStart", touchPoints: touches(40) });
    for (let d = 50; d <= 140; d += 15) {
      await cdp.send("Input.dispatchTouchEvent", { type: "touchMove", touchPoints: touches(d) });
      await page.waitForTimeout(30);
    }
    await cdp.send("Input.dispatchTouchEvent", { type: "touchEnd", touchPoints: [] });
    await expect.poll(() => page.evaluate(() => window.__th.map().getZoom()), { timeout: 4000 }).toBeGreaterThan(z0 + 0.5);
    const b2 = await img.boundingBox();
    expect(b2.width).toBeGreaterThan(b1.width * 1.3);
    await page.locator("#mapback").click();
    await expect(page.locator("#s-map")).toBeHidden();
    expect(await page.evaluate(() => window.__geo.watches)).toBe(0);
    expect(errors).toEqual([]);
  });
});
