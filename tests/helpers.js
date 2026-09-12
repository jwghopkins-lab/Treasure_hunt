// Shared by the suites: the stubs the pages run under, the hunts they open,
// and a browser with a chosen picture in its fake camera.
const { chromium, devices } = require("@playwright/test");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const Y4M = path.join(__dirname, ".y4m");
const BASE = "http://127.0.0.1:8765/";

// Runs in the page before any of its own script: a vibration that records
// what was asked and whether it was asked inside a tap; a geolocation whose
// watches are counted and can be turned off altogether.
const INIT = `
  (() => {
    window.__vibes = [];
    window.__inTap = false;
    window.addEventListener("click", () => {
      window.__inTap = true;
      setTimeout(() => { window.__inTap = false; }, 0);
    }, true);
    Object.defineProperty(navigator, "vibrate", {
      configurable: true,
      value: (p) => { window.__vibes.push({ p, inTap: window.__inTap }); return true; },
    });
    window.__geo = { watches: 0, clears: 0 };
    const g = navigator.geolocation;
    if (g) {
      const w = g.watchPosition.bind(g), c = g.clearWatch.bind(g);
      g.watchPosition = (ok, err, opts) => { window.__geo.watches += 1; return w(ok, err, opts); };
      g.clearWatch = (id) => { window.__geo.clears += 1; return c(id); };
    }
  })();
`;

function hunt(name) {
  const p = name === "fixture" ? path.join(ROOT, "content", "fixture.json")
                               : path.join(ROOT, "tests", "content", name + ".json");
  return JSON.parse(fs.readFileSync(p, "utf8"));
}

// Page errors are collected from the start; a test that ends with any is wrong.
async function prepare(page) {
  const errors = [];
  page.on("pageerror", (e) => errors.push(String(e)));
  await page.addInitScript(INIT);
  return errors;
}

// A name already on the phone, so the name screen does not open.
async function withName(page, name) {
  await page.addInitScript((n) => { localStorage.setItem("treasure.name", n); }, name || "Ada");
}

// A stub of the Supabase REST API for the leaderboard. Records posts, serves
// rows, and can be made to fail.
function stubBoard(page, opts) {
  const o = Object.assign({ rows: [], failPost: false, failGet: false }, opts || {});
  const log = { posts: [], gets: 0, attempts: [] };
  page.route("https://stub.supabase.co/**", async (route) => {
    const req = route.request();
    const url = req.url();
    // The telemetry drop: every opening of the camera screen posts a row
    // here as it closes, and a test reads what it said.
    if (url.includes("/rest/v1/attempts") && req.method() === "POST") {
      log.attempts.push(req.postDataJSON());
      return route.fulfill({ status: 201, body: "" });
    }
    if (url.includes("/rest/v1/completions")) {
      if (req.method() === "POST") {
        log.posts.push({ body: req.postDataJSON(), headers: req.headers() });
        if (o.failPost === true || (typeof o.failPost === "function" && o.failPost(log.posts.length))) {
          return route.fulfill({ status: 500, body: "nope" });
        }
        return route.fulfill({ status: 201, body: "" });
      }
      log.gets += 1;
      if (o.failGet) return route.fulfill({ status: 500, body: "nope" });
      return route.fulfill({ status: 200, contentType: "application/json",
                             body: JSON.stringify(typeof o.rows === "function" ? o.rows(log) : o.rows) });
    }
    return route.fulfill({ status: 404, body: "" });
  });
  return log;
}

// A browser whose fake camera shows the given picture. The y4m has to be
// named at launch, so these tests bring their own browser.
async function browserWithFeed(y4mFile) {
  const file = path.isAbsolute(y4mFile) ? y4mFile : path.join(Y4M, y4mFile);
  if (!fs.existsSync(file)) throw new Error("no y4m at " + file);
  return chromium.launch({
    args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream",
           "--use-file-for-fake-video-capture=" + file],
  });
}
async function mobileContext(browser, extra) {
  return browser.newContext(Object.assign({
    ...devices["Pixel 7"],
    baseURL: BASE,
    permissions: ["geolocation", "camera"],
    geolocation: { latitude: 51.5, longitude: -0.12, accuracy: 20 },
  }, extra || {}));
}

// Where a phone is that stands `metres` away on `bearing` from a place.
function destPoint(lat, lon, bearing, metres) {
  const R = 6371008.8, r = Math.PI / 180;
  const d = metres / R, b = bearing * r, p1 = lat * r, l1 = lon * r;
  const p2 = Math.asin(Math.sin(p1) * Math.cos(d) + Math.cos(p1) * Math.sin(d) * Math.cos(b));
  const l2 = l1 + Math.atan2(Math.sin(b) * Math.sin(d) * Math.cos(p1),
                             Math.cos(d) - Math.sin(p1) * Math.sin(p2));
  return { latitude: p2 / r, longitude: ((l2 / r + 540) % 360) - 180 };
}

// The words on a screen, with the clock and the glyph buttons taken out.
async function wordsOn(page, selector) {
  return page.evaluate((sel) => {
    const el = document.querySelector(sel);
    // innerText on the live element, so hidden parts stay out of it; the
    // clock, the glyph buttons and any input are taken back out of the text.
    let text = el.innerText;
    for (const n of el.querySelectorAll("#clock, #menubtn, #mapbtn")) text = text.replace(n.innerText, " ");
    return text.replace(/\s+/g, " ").trim();
  }, selector);
}

module.exports = { ROOT, Y4M, BASE, INIT, hunt, prepare, withName, stubBoard, browserWithFeed,
                   mobileContext, destPoint, wordsOn };
