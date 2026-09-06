// The three timers, on passRule with made-up sequences at 250 ms steps, the
// first evaluation at 0 ms.
const { test, expect } = require("@playwright/test");
const { prepare, withName, stubBoard } = require("./helpers");

// Run a constant score through the rule and return the index of the first
// passing evaluation, or -1.
async function firstPass(page, score, steps) {
  return page.evaluate(([score, steps]) => {
    let st = null;
    for (let i = 0; i < steps; i++) {
      st = window.Lens.passRule(st, score, i * 250);
      if (st.passed) return i;
    }
    return -1;
  }, [score, steps]);
}

test.describe("the pass rule", () => {
  test.beforeEach(async ({ page }) => {
    await prepare(page);
    await withName(page);
    stubBoard(page);
    await page.goto("fixture/");
    await expect(page.locator("#s-main")).toBeVisible();
  });

  test("0.36 passes on the fourth evaluation (750 ms) and not the third", async ({ page }) => {
    expect(await firstPass(page, 0.36, 20)).toBe(3);
  });
  test("0.31 passes on the fifth evaluation (1000 ms) and not the fourth", async ({ page }) => {
    expect(await firstPass(page, 0.31, 20)).toBe(4);
  });
  test("0.26 passes on the ninth evaluation (2000 ms) and not the eighth", async ({ page }) => {
    expect(await firstPass(page, 0.26, 20)).toBe(8);
  });
  test("0.24 never passes", async ({ page }) => {
    expect(await firstPass(page, 0.24, 400)).toBe(-1);
  });
  test("a single dip below a line resets that line's timer and no other", async ({ page }) => {
    const out = await page.evaluate(() => {
      const seq = [0.36, 0.36, 0.31, 0.36, 0.36];
      let st = null;
      const trace = [];
      seq.forEach((s, i) => { st = window.Lens.passRule(st, s, i * 250); trace.push({ since: st.since.slice(), passed: st.passed }); });
      return trace;
    });
    // At 500 ms the score dipped under 0.35: that timer is cleared, the
    // 0.30 and 0.25 timers keep their start at 0.
    expect(out[1]).toEqual({ since: [0, 0, 0], passed: false });
    expect(out[2]).toEqual({ since: [null, 0, 0], passed: false });
    expect(out[3]).toEqual({ since: [750, 0, 0], passed: false });
    // At 1000 ms the 0.30 line has held for a second, so it passes, while
    // the restarted 0.35 timer has only 250 ms on it.
    expect(out[4]).toEqual({ since: [750, 0, 0], passed: true });
  });
  test("is pure: the state handed in is not changed", async ({ page }) => {
    const out = await page.evaluate(() => {
      const st = { since: [0, 0, 0], passed: false };
      const copy = JSON.stringify(st);
      const next = window.Lens.passRule(st, 0.1, 250);
      return { same: JSON.stringify(st) === copy, next };
    });
    expect(out.same).toBe(true);
    expect(out.next).toEqual({ since: [null, null, null], passed: false });
  });
});
