/* The camera screen: the phone's back camera with a stencil fixed over the
   live view, and a number that says how well the edges in the frame agree
   with it.

   Taken from architect-order's lens and cut down to the one thing this game
   needs. There the overlay was placed by the player's thumb; here it cannot
   be moved at all. The stencil sits where the photograph's edges will sit
   when the phone stands where the photograph was taken and points the same
   way, and the only way to make the number rise is to go and stand there.

   No dependencies, no library. The scorer looks at how well the shape under
   the stencil agrees with it and nothing else: nothing snaps, nothing is
   detected, nothing is measured for the player.

   window.Lens.open(stencil, opts) where stencil is one entry of the hunt's
   list ({ id, src, clue?, location? }) and opts carries what the screen needs
   from the page:
     testMode      true shows Skip
     distanceLine  (lat, lon, acc) => "About 240 m · NE", or "" for nothing
     hinted        true if the hint was already taken for this stencil
     onHint        () => void, the hint was taken, inside the tap
     onPass        (how) => void, called once, inside the pass, how is "match" or "skip"
     onClose       () => void, the screen has closed, back or after the pass */
(function () {
  "use strict";

  const MATCH_EVERY_MS = 250;
  const MATCH_ALPHA = 0.3;          // exponential smoothing of the score
  const MATCH_SHIFTS = [-5, 0, 5];  // working-resolution pixels
  // Five scales, ±15%: photographs taken with the camera app rather than the
  // capture page lean on this, and the first hunt showed ±10% was tight.
  const MATCH_SCALES = [0.85, 0.925, 1, 1.075, 1.15];
  const WORK_PX = 320;              // longest side of the working frame
  const WORK_PX_SLOW = 240;         // and where it drops to if a phone cannot keep up
  const SLOW_MS = 10;
  // The pass rule (section 7 of the handoff): a score held at a line for long
  // enough, on consecutive evaluations. Three lines, each with its own timer.
  // Each line is 0.05 under the handoff's, after the first hunt was walked.
  const PASS_LINES = [[0.30, 600], [0.25, 1000], [0.20, 2000]];
  const BAR_FULL = 0.30;            // the score at which the bar is all the way across
  const COMPLETE_MS = 1500;         // how long Complete! stays before the screen closes itself

  let root = null;        // the full-screen container, built once and reused
  let stream = null;      // the live camera tracks, so they can all be stopped
  let cfg = null;         // { stencil, opts }
  let match = null;       // the live match state while the screen is open
  let rect = null;        // the video's rendered rectangle on the screen, in CSS px
  let place = null;       // the stencil's drawn rectangle, in CSS px
  let fixWatch = null;    // a watchPosition, only while a located stencil is open
  let completeTimer = null;
  let generation = 0;     // which opening of the screen a camera request belongs to

  function el(tag, cls, text) {
    const n = document.createElement(tag);
    if (cls) n.className = cls;
    if (text != null) n.textContent = text;
    return n;
  }
  const q = (sel) => root.querySelector(sel);

  /* ---- styles, injected once so the page stays one file of markup ---- */
  function injectStyle() {
    if (document.getElementById("lensstyle")) return;
    const s = el("style");
    s.id = "lensstyle";
    s.textContent = `
    #lens { position: fixed; inset: 0; z-index: 40; background: #000;
            display: none; touch-action: none; overscroll-behavior: none;
            user-select: none; -webkit-user-select: none;
            color: #fff; font-family: system-ui, -apple-system, sans-serif; }
    #lens.on { display: block; }
    #lensfeed { position: absolute; inset: 0; width: 100%; height: 100%;
                object-fit: contain; background: #000; }
    /* A dark halo round the lines, so they read on a bright wall as well as
       a dark one. Display only: the scorer reads the PNG, not the screen. */
    #lensstencil, #lenshint { position: absolute; left: 0; top: 0; display: block;
                   pointer-events: none;
                   filter: drop-shadow(0 0 1.5px rgba(0,0,0,.95)) drop-shadow(0 0 1px rgba(0,0,0,.7)); }
    /* The hint: the same picture with twice as much of it, laid under the
       real stencil, dimmer, so the lines that count still stand out. */
    #lenshint { opacity: .55; }
    /* The bar at the very top, the full width. Green, always. */
    #matchbar { position: absolute; left: 0; right: 0; top: env(safe-area-inset-top, 0px);
                height: 8px; background: rgba(255,255,255,.18); z-index: 3; }
    #matchfill { height: 100%; width: 0; background: #3FBF7F;
                 transition: width .2s linear; }
    #lensback, #lensskip, #lenshintbtn { position: absolute; z-index: 4;
                           top: calc(18px + env(safe-area-inset-top, 0px)); }
    #lensback, #lenshintbtn { border: none; background: rgba(0,0,0,.45); color: #fff;
                width: 44px; height: 44px; border-radius: 999px; font-size: 1.3rem;
                cursor: pointer; }
    #lensback { left: 12px; }
    /* The hint button, top-right: one glyph, one tap, gone once taken. */
    #lenshintbtn { right: 12px; font-family: Georgia, serif; font-weight: 700; }
    /* Skip. Plain on purpose: it exists only in test mode, and it should never
       look like the thing you are meant to press. */
    #lensskip { right: 12px; border: none; background: none; color: rgba(255,255,255,.85);
                font: inherit; font-size: .82rem; text-decoration: underline dotted;
                text-underline-offset: 3px; padding: 12px 10px; min-height: 44px;
                cursor: pointer; }
    #lensmsg { position: absolute; left: 18px; right: 18px; top: 44%; text-align: center;
               font-size: 1rem; line-height: 1.5; text-shadow: 0 1px 4px rgba(0,0,0,.9); }
    /* The clue and the distance line, one translucent strip across the bottom. */
    #lensfoot { position: absolute; left: 0; right: 0; bottom: 0; z-index: 3;
                padding: 12px 16px calc(14px + env(safe-area-inset-bottom, 0px));
                background: rgba(0,0,0,.55); display: flex; flex-direction: column; gap: 4px; }
    #lensclue { font-family: Georgia, "Times New Roman", serif; font-size: 1.02rem;
                line-height: 1.4; }
    #lensdist { font-size: .9rem; opacity: .92; font-variant-numeric: tabular-nums;
                min-height: 1.2em; }
    /* Complete! A full-screen button over a green wash: it closes on a tap,
       and being a tap, that ticks on iPhone. */
    #lenswash { position: absolute; inset: 0; z-index: 5; border: none; cursor: pointer;
                background: rgba(47,107,79,.78); color: #fff; font-family: Georgia, serif;
                font-weight: 700; font-size: 2.6rem; letter-spacing: .02em; }
    `;
    document.head.appendChild(s);
  }

  /* ---- the shell ---- */
  function build() {
    injectStyle();
    root = el("div");
    root.id = "lens";
    root.innerHTML = `
      <video id="lensfeed" autoplay playsinline muted></video>
      <img id="lenshint" alt="" hidden>
      <img id="lensstencil" alt="">
      <div id="matchbar"><div id="matchfill"></div></div>
      <button id="lensback" aria-label="Back">←</button>
      <button id="lenshintbtn" aria-label="Hint" hidden>?</button>
      <div id="lensmsg" hidden></div>
      <div id="lensfoot" hidden><div id="lensclue" hidden></div><div id="lensdist" hidden></div></div>
      <button id="lenswash" data-strong hidden>Complete!</button>`;
    document.body.appendChild(root);
    // The tick happens on the tap itself, before this runs: the switch under
    // the finger on iPhone, the page's capture-phase vibration elsewhere.
    q("#lensback").onclick = () => { close(); if (cfg && cfg.opts.onClose) cfg.opts.onClose(); };
    q("#lenswash").onclick = finish;
    q("#lenshintbtn").onclick = () => showHint(true);
    q("#lensfeed").addEventListener("loadedmetadata", layout);
    q("#lensstencil").addEventListener("load", layout);
    window.addEventListener("resize", () => { if (isOpen()) layout(); });
    window.addEventListener("orientationchange", () => { if (isOpen()) layout(); });
  }
  function isOpen() { return !!(root && root.classList.contains("on")); }

  /* ---- opening and closing ---- */
  async function open(stencil, opts) {
    if (!root) build();
    cfg = { stencil, opts: opts || {} };
    root.classList.add("on");
    const img = q("#lensstencil");
    img.src = stencil.src;
    // The hint, if the hunt made one: already showing if it was taken on an
    // earlier opening of this stencil, else behind the button.
    const hint = q("#lenshint");
    if (stencil.hint) hint.src = stencil.hint; else hint.removeAttribute("src");
    hint.hidden = !(stencil.hint && cfg.opts.hinted);
    q("#lenshintbtn").hidden = !stencil.hint || !!cfg.opts.hinted;
    q("#lensclue").textContent = stencil.clue || "";
    q("#lensclue").hidden = !stencil.clue;
    q("#lensdist").textContent = "";
    q("#lensdist").hidden = !stencil.location;
    q("#lensfoot").hidden = !(stencil.clue || stencil.location);
    q("#lensmsg").hidden = true;
    q("#lenswash").hidden = true;
    // Skip exists only in test mode. Not hidden: absent.
    const old = q("#lensskip");
    if (old) old.remove();
    if (cfg.opts.testMode) {
      const skip = el("button", null, "Skip");
      skip.id = "lensskip";
      skip.style.right = stencil.hint ? "68px" : "12px";
      skip.onclick = () => pass("skip");
      root.appendChild(skip);
    }
    layout();
    startMatch();
    startWatch();
    await startCamera();
  }

  function stopStream() {
    if (stream) { for (const t of stream.getTracks()) t.stop(); stream = null; }
  }

  async function startCamera() {
    const video = q("#lensfeed");
    if (!navigator.mediaDevices || !navigator.mediaDevices.getUserMedia) {
      message("No camera here.");
      return;
    }
    stopStream();
    const mine = generation;
    try {
      // Exactly this request and nothing more: an aspectRatio or a size
      // constraint changes the crop a phone hands over, and the capture page
      // has to get the same crop the game gets.
      const got = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "environment" } }, audio: false });
      // The permission prompt can outlive the screen: tap a thumbnail, tap
      // back before answering, and the camera arrives for a view that is
      // gone. A stream nobody is looking at is stopped on arrival.
      if (mine !== generation || !isOpen()) {
        for (const t of got.getTracks()) t.stop();
        return;
      }
      stream = got;
      video.srcObject = stream;
      q("#lensmsg").hidden = true;
    } catch (err) {
      if (mine !== generation || !isOpen()) return;
      message(err && err.name === "NotAllowedError" ? "The camera was refused." : "No camera here.");
    }
  }
  // No photo fallback: a chosen photo would be the answer.
  function message(text) {
    const m = q("#lensmsg");
    m.textContent = text;
    m.hidden = false;
  }

  function close() {
    stopMatch();
    stopWatch();
    clearTimeout(completeTimer);
    completeTimer = null;
    generation += 1;
    stopStream();
    if (!root) return;
    const video = q("#lensfeed");
    video.srcObject = null;
    q("#lenswash").hidden = true;
    root.classList.remove("on");
  }

  /* ---- the stencil, fixed ----
     The video is letterboxed, not cropped, so first the rectangle it actually
     draws in, from videoWidth and videoHeight against the screen; then the
     largest rectangle of the stencil's own aspect that fits inside it,
     centred. The stencil is sized to exactly that with explicit width and
     height, so stencil pixel (x, y) sits over video pixel (x, y) scaled, and
     stencilMasks can read the drawn size off the element. Until the stream
     arrives the screen itself is the rectangle, so the stencil is already
     there over the black. */
  function layout() {
    if (!root) return;
    const W = root.clientWidth || window.innerWidth;
    const H = root.clientHeight || window.innerHeight;
    const video = q("#lensfeed");
    if (video.videoWidth > 0 && video.videoHeight > 0) {
      const s = Math.min(W / video.videoWidth, H / video.videoHeight);
      const rw = video.videoWidth * s, rh = video.videoHeight * s;
      rect = { x: (W - rw) / 2, y: (H - rh) / 2, w: rw, h: rh };
    } else {
      rect = { x: 0, y: 0, w: W, h: H };
    }
    const img = q("#lensstencil");
    if (img.naturalWidth > 0 && img.naturalHeight > 0) {
      const t = Math.min(rect.w / img.naturalWidth, rect.h / img.naturalHeight);
      const dw = img.naturalWidth * t, dh = img.naturalHeight * t;
      place = { x: rect.x + (rect.w - dw) / 2, y: rect.y + (rect.h - dh) / 2, w: dw, h: dh };
      for (const node of [img, q("#lenshint")]) {
        node.style.left = place.x + "px";
        node.style.top = place.y + "px";
        node.style.width = place.w + "px";
        node.style.height = place.h + "px";
      }
    } else {
      place = null;
    }
    if (match) match.maskKey = "";       // the placement moved: masks are rebuilt on the next tick
  }

  /* ---- the distance line ----
     One watch, started when a located stencil opens and cleared the moment the
     screen closes. The page turns a fix into the words; this only asks. */
  function startWatch() {
    stopWatch();
    if (!cfg.stencil.location || !navigator.geolocation || !cfg.opts.distanceLine) return;
    const paint = (text) => {
      const d = q("#lensdist");
      d.textContent = text || "";
      d.hidden = false;
    };
    fixWatch = navigator.geolocation.watchPosition(
      (pos) => {
        if (!isOpen()) return;
        const c = pos.coords;
        paint(cfg.opts.distanceLine(c.latitude, c.longitude, c.accuracy));
      },
      () => { if (isOpen()) paint(""); },
      { enableHighAccuracy: true, maximumAge: 5000 });
  }
  function stopWatch() {
    if (fixWatch !== null && navigator.geolocation) navigator.geolocation.clearWatch(fixWatch);
    fixWatch = null;
  }

  /* ---- the hint ----
     The denser stencil appears under the real one and the button goes. It
     is display only: the scorer keeps reading #lensstencil. The page is
     told inside the tap, so the cost lands on the clock at once. */
  function showHint(charge) {
    if (!cfg || !cfg.stencil.hint) return;
    q("#lenshint").hidden = false;
    q("#lenshintbtn").hidden = true;
    if (charge && cfg.opts.onHint) cfg.opts.onHint();
  }

  /* ---- the pass ---- */
  // The rule as one pure function: the timers so far, the smoothed score, the
  // time now; back come the timers and whether it passed. A line's timer
  // starts at the evaluation where the score first reaches it and is cleared
  // the moment the score drops below it; the first to expire passes.
  function passRule(state, score, now) {
    const prev = state && state.since ? state.since : [];
    const since = PASS_LINES.map(([line], i) => {
      if (score < line) return null;
      return prev[i] == null ? now : prev[i];
    });
    const passed = PASS_LINES.some(([, hold], i) => since[i] != null && now - since[i] >= hold);
    return { since, passed };
  }

  function pass(how) {
    if (!isOpen() || completeTimer) return;
    stopMatch();
    stopWatch();
    if (cfg.opts.onPass) cfg.opts.onPass(how);
    q("#lenswash").hidden = false;
    completeTimer = setTimeout(finish, COMPLETE_MS);
  }
  function finish() {
    if (!completeTimer) return;
    close();
    if (cfg && cfg.opts.onClose) cfg.opts.onClose();
  }

  /* ---- the match ----
     Edges in the frame are compared under the stencil's lines against a ring
     just beside them: if the edges are no more likely under the stencil than
     next to it, the score is zero; if every edge nearby is under it, one. A
     small search in shift and scale forgives a phone standing a little off,
     and a camera whose crop is a little different from the photograph's. */
  function startMatch() {
    stopMatch();
    match = {
      smooth: null, on: 0, off: 0, best: 0, ms: null,
      pass: { since: [], passed: false },
      workPx: WORK_PX, slow: [],
      frame: document.createElement("canvas"), stencil: document.createElement("canvas"),
      masks: null, maskKey: "", native: new Map(), rebuilt: false,
      timer: null,
    };
    paintBar();
    match.timer = setInterval(matchTick, MATCH_EVERY_MS);
  }
  function stopMatch() {
    if (match && match.timer) clearInterval(match.timer);
    match = null;
  }

  // The working frame is the video's rendered rectangle, not the screen.
  function workSize() {
    const k = match.workPx / Math.max(rect.w, rect.h);
    return { w: Math.max(8, Math.round(rect.w * k)), h: Math.max(8, Math.round(rect.h * k)), k };
  }

  function matchTick() {
    if (!match) return;
    const t0 = performance.now();
    const img = q("#lensstencil");
    const video = q("#lensfeed");
    if (!img.naturalWidth || !place || !(video.videoWidth > 0)) { paintBar(); return; }

    const { w, h, k } = workSize();
    const E = edgeMap(video, w, h);
    const masks = stencilMasks(img, w, h, k);

    let best = { score: 0, on: 0, off: 0 };
    for (const mk of masks) {
      for (const dy of MATCH_SHIFTS) for (const dx of MATCH_SHIFTS) {
        const on = meanAt(E, mk.M, w, h, dx, dy);
        const off = meanAt(E, mk.R, w, h, dx, dy);
        const score = Math.max(0, (on - off) / (on + off + 0.001));
        if (score > best.score) best = { score, on, off };
      }
    }
    match.best = best.score;
    match.on = best.on; match.off = best.off;
    // The smoothing starts at the first raw score rather than at zero, so a
    // good alignment passes about a second after the first evaluation.
    match.smooth = match.smooth == null ? best.score
                 : MATCH_ALPHA * best.score + (1 - MATCH_ALPHA) * match.smooth;

    const now = performance.now();
    match.pass = passRule(match.pass, match.smooth, now);

    // Keep each evaluation cheap. A phone that cannot manage it at 320 px
    // drops to 240 px and stays there for the rest of the screen. Only the
    // steady ticks count: the one that rebuilds the masks pays for the
    // layout, not the frame. The median of the last eight, not the mean of
    // the last four: one garbage-collection pause is a hiccup, and a hiccup
    // should not demote the screen for the rest of the stencil.
    const took = now - t0;
    match.ms = took;
    if (!match.rebuilt) {
      match.slow.push(took);
      if (match.slow.length > 8) match.slow.shift();
      if (match.workPx === WORK_PX && match.slow.length === 8) {
        const sorted = [...match.slow].sort((a, b) => a - b);
        if ((sorted[3] + sorted[4]) / 2 > SLOW_MS) {
          match.workPx = WORK_PX_SLOW;
          match.maskKey = "";
        }
      }
    }
    paintBar();
    if (match.pass.passed) pass("match");
  }

  // Grayscale, a 3×3 box blur, a 3×3 Sobel, and the magnitude scaled so that
  // the frame's 99th percentile is one. That last step is what stops the score
  // swinging with the light: a dim wall and a bright one give the same map.
  function edgeMap(src, w, h) {
    const c = match.frame;
    if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
    const ctx = c.getContext("2d", { willReadFrequently: true });
    // The whole frame, no crop: the working frame is the rendered rectangle,
    // which has the frame's own aspect.
    ctx.drawImage(src, 0, 0, w, h);
    const px = ctx.getImageData(0, 0, w, h).data;
    const n = w * h;
    const g = new Float32Array(n);
    for (let i = 0, j = 0; i < n; i++, j += 4) {
      g[i] = 0.299 * px[j] + 0.587 * px[j + 1] + 0.114 * px[j + 2];
    }
    // The blur clamps at the border: a pixel outside the frame reads as its
    // nearest pixel inside. Left at zero, the border makes the Sobel see a
    // bright line all the way round the frame, in the live view and in every
    // stencil alike, and a line that is always there is a match for free:
    // with the stencil filling the rectangle, a blank wall scored a pass.
    const b = new Float32Array(n);
    for (let y = 0; y < h; y++) {
      const r0 = Math.max(0, y - 1) * w, r1 = y * w, r2 = Math.min(h - 1, y + 1) * w;
      for (let x = 0; x < w; x++) {
        const x0 = Math.max(0, x - 1), x2 = Math.min(w - 1, x + 1);
        b[r1 + x] = (g[r0 + x0] + g[r0 + x] + g[r0 + x2]
                   + g[r1 + x0] + g[r1 + x] + g[r1 + x2]
                   + g[r2 + x0] + g[r2 + x] + g[r2 + x2]) / 9;
      }
    }
    const mag = new Float32Array(n);
    const hist = new Uint32Array(256);
    const MAXMAG = 1443;                      // sqrt(2) × 4 × 255, the Sobel ceiling
    for (let y = 1; y < h - 1; y++) {
      for (let x = 1; x < w - 1; x++) {
        const i = y * w + x;
        const gx = -b[i - w - 1] + b[i - w + 1] - 2 * b[i - 1] + 2 * b[i + 1]
                   - b[i + w - 1] + b[i + w + 1];
        const gy = -b[i - w - 1] - 2 * b[i - w] - b[i - w + 1]
                   + b[i + w - 1] + 2 * b[i + w] + b[i + w + 1];
        const mg = Math.sqrt(gx * gx + gy * gy);
        mag[i] = mg;
        hist[Math.min(255, (mg * 255 / MAXMAG) | 0)]++;
      }
    }
    // The histogram holds the interior only: the one-pixel border has no
    // gradient. Counting to 99% of the whole frame instead would never get
    // there on a small frame, and the loop would run off the end and hand
    // back the Sobel ceiling as the "percentile".
    const want = (w - 2) * (h - 2) * 0.99;
    let seen = 0, bin = 0;
    for (; bin < 255; bin++) { seen += hist[bin]; if (seen >= want) break; }
    const p99 = Math.max(1e-6, (bin + 1) * MAXMAG / 255);
    for (let i = 0; i < n; i++) mag[i] = Math.min(1, mag[i] / p99);
    return mag;
  }

  // The stencil's alpha where it is drawn, at three scales, each thresholded,
  // thickened by two pixels into the mask M, then thickened by six more and
  // hollowed out into the ring R. Cached against the placement: while the
  // phone holds still, only the frame is recomputed.
  //
  // The threshold and the first thickening happen at the stencil's own
  // resolution, not the working frame's. A 3 px line on a 600 px stencil is
  // under half a pixel once the stencil is 90 px wide, and thresholding that
  // after the shrink leaves nothing: the line's alpha never reaches 128. So
  // the PNG's own pixels are thresholded, where it is exact, thickened by the
  // native equivalent of two working pixels, and only then drawn small.
  function stencilMasks(img, w, h, k) {
    const key = [w, h, rect.x, rect.y, rect.w, rect.h, img.offsetWidth, img.offsetHeight, img.src].join(",");
    match.rebuilt = !(match.masks && match.maskKey === key);
    if (!match.rebuilt) return match.masks;
    const c = match.stencil;
    if (c.width !== w || c.height !== h) { c.width = w; c.height = h; }
    const ctx = c.getContext("2d", { willReadFrequently: true });
    const elW = img.offsetWidth;
    const elH = img.offsetHeight || elW * img.naturalHeight / img.naturalWidth;
    // The stencil's centre in the rectangle's own coordinates, then scaled by
    // k, so working pixel (0, 0) is the rectangle's corner.
    const cx = (place.x + place.w / 2 - rect.x) * k;
    const cy = (place.y + place.h / 2 - rect.y) * k;
    const out = [];
    for (const sc of MATCH_SCALES) {
      const perNative = elW * sc * k / img.naturalWidth;   // working px per stencil px
      // Not laid out yet: no size, no mask, and nothing to score this tick.
      if (!(perNative > 0)) { match.maskKey = ""; return []; }
      const thick = nativeMask(img, Math.min(64, Math.max(1, Math.ceil(2 / perNative))));
      ctx.clearRect(0, 0, w, h);
      ctx.save();
      ctx.translate(cx, cy);
      ctx.scale(sc * k, sc * k);
      ctx.drawImage(thick, -elW / 2, -elH / 2, elW, elH);
      ctx.restore();
      const a = ctx.getImageData(0, 0, w, h).data;
      const n = w * h;
      const M = new Uint8Array(n);
      for (let i = 0, j = 3; i < n; i++, j += 4) M[i] = a[j] >= 128 ? 1 : 0;
      const D = dilate(M, w, h, 6);
      const Mi = [], Ri = [];
      for (let i = 0; i < n; i++) {
        if (M[i]) Mi.push(i);
        else if (D[i]) Ri.push(i);
      }
      out.push({ M: Int32Array.from(Mi), R: Int32Array.from(Ri) });
    }
    match.masks = out;
    match.maskKey = key;
    return out;
  }

  // The stencil's alpha at its own size, thresholded at 128 and thickened by
  // r pixels, as an opaque white shape on nothing that drawImage can shrink.
  // Cached by radius: only a change of layout asks for another.
  function nativeMask(img, r) {
    const key = img.src + "|" + r;
    if (match.native.has(key)) return match.native.get(key);
    const nw = img.naturalWidth, nh = img.naturalHeight;
    const c = document.createElement("canvas");
    c.width = nw; c.height = nh;
    const ctx = c.getContext("2d", { willReadFrequently: true });
    ctx.drawImage(img, 0, 0);
    const a = ctx.getImageData(0, 0, nw, nh).data;
    const n = nw * nh;
    const bin = new Uint8Array(n);
    for (let i = 0, j = 3; i < n; i++, j += 4) bin[i] = a[j] >= 128 ? 1 : 0;
    const thick = dilate(bin, nw, nh, r);
    const out = ctx.createImageData(nw, nh);
    for (let i = 0, j = 0; i < n; i++, j += 4) {
      if (thick[i]) { out.data[j] = out.data[j + 1] = out.data[j + 2] = out.data[j + 3] = 255; }
    }
    ctx.putImageData(out, 0, 0);
    match.native.set(key, c);
    return c;
  }

  // A square dilation as two one-dimensional passes, stamping runs out from
  // each set pixel. Cheap because a stencil is thin lines on nothing.
  function dilate(src, w, h, r) {
    const tmp = new Uint8Array(w * h), out = new Uint8Array(w * h);
    for (let y = 0; y < h; y++) {
      const row = y * w;
      for (let x = 0; x < w; x++) {
        if (!src[row + x]) continue;
        tmp.fill(1, row + Math.max(0, x - r), row + Math.min(w - 1, x + r) + 1);
      }
    }
    for (let y = 0; y < h; y++) {
      const row = y * w;
      for (let x = 0; x < w; x++) {
        if (!tmp[row + x]) continue;
        const a = Math.max(0, y - r), b = Math.min(h - 1, y + r);
        for (let yy = a; yy <= b; yy++) out[yy * w + x] = 1;
      }
    }
    return out;
  }

  // Mean of E over a set of pixel indices, with the set shifted by (dx, dy).
  // Shifting the sample instead of redrawing the stencil is what makes the
  // twenty-seven evaluations affordable.
  function meanAt(E, idx, w, h, dx, dy) {
    let sum = 0, cnt = 0;
    const n = w * h, off = dy * w + dx;
    for (let t = 0; t < idx.length; t++) {
      const i = idx[t];
      const x = i % w + dx;
      if (x < 0 || x >= w) continue;
      const j = i + off;
      if (j < 0 || j >= n) continue;
      sum += E[j]; cnt++;
    }
    return cnt ? sum / cnt : 0;
  }

  // The bar's fill is the smoothed score against the top line: the full
  // width is a pass on that line, and a pass that comes from a lower line's
  // timer is seen with the bar part of the way across. No numbers.
  function paintBar() {
    if (!root) return;
    const s = match && match.smooth != null ? match.smooth : 0;
    q("#matchfill").style.width = (Math.min(1, s / BAR_FULL) * 100) + "%";
  }

  // For the tests: paint the bar as if the smoothed score were v, and stop
  // the match loop for the rest of this opening so the camera does not paint
  // over it. It does not feed the pass rule; a pass comes from the camera or
  // from Skip.
  function fakeScore(v) {
    if (!match) return;
    if (match.timer) { clearInterval(match.timer); match.timer = null; }
    match.smooth = v;
    paintBar();
  }

  // How the match is doing on this phone: the last evaluation's cost and the
  // working size it settled on. Read-only, for checking the 10 ms budget.
  function stats() {
    return match ? { ms: match.ms == null ? null : Math.round(match.ms * 100) / 100,
                     recent: match.slow.map((v) => Math.round(v * 10) / 10),
                     workPx: match.workPx, score: match.smooth, best: match.best,
                     on: match.on, off: match.off, since: match.pass.since,
                     rect, place, hinted: !q("#lenshint").hidden }
                 : { rect, place, score: null };
  }

  window.Lens = { open, close, stats, passRule, fakeScore, isOpen };
})();
