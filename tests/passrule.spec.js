// The three timers, on passRule with made-up sequences at 250 ms steps, the
// first evaluation at 0 ms. The lines are 0.30, 0.25 and 0.20.
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

  test("0.31 passes on the fourth evaluation (750 ms) and not the third", async ({ page }) => {
    expect(await firstPass(page, 0.31, 20)).toBe(3);
  });
  test("0.26 passes on the fifth evaluation (1000 ms) and not the fourth", async ({ page }) => {
    expect(await firstPass(page, 0.26, 20)).toBe(4);
  });
  test("0.21 passes on the ninth evaluation (2000 ms) and not the eighth", async ({ page }) => {
    expect(await firstPass(page, 0.21, 20)).toBe(8);
  });
  test("0.19 never passes", async ({ page }) => {
    expect(await firstPass(page, 0.19, 400)).toBe(-1);
  });
  test("a single dip below a line resets that line's timer and no other", async ({ page }) => {
    const out = await page.evaluate(() => {
      const seq = [0.31, 0.31, 0.26, 0.31, 0.31];
      let st = null;
      const trace = [];
      seq.forEach((s, i) => { st = window.Lens.passRule(st, s, i * 250); trace.push({ since: st.since.slice(), passed: st.passed }); });
      return trace;
    });
    // At 500 ms the score dipped under 0.30: that timer is cleared, the
    // 0.25 and 0.20 timers keep their start at 0.
    expect(out[1]).toEqual({ since: [0, 0, 0], passed: false });
    expect(out[2]).toEqual({ since: [null, 0, 0], passed: false });
    expect(out[3]).toEqual({ since: [750, 0, 0], passed: false });
    // At 1000 ms the 0.25 line has held for a second, so it passes, while
    // the restarted 0.30 timer has only 250 ms on it.
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

  test("a stencil's own lines: lower, and the bar fills at the top one", async ({ page }) => {
    // The rule with three lower lines handed in: 0.16 passes on the lowest
    // after two seconds, 0.14 never does, and the standard rule is untouched.
    const out = await page.evaluate(() => {
      const L = [[0.225, 600], [0.188, 1000], [0.15, 2000]];
      const run = (score, lines) => {
        let st = { since: [], passed: false };
        for (let i = 0; i < 12; i++) { st = window.Lens.passRule(st, score, i * 250, lines); if (st.passed) return i; }
        return null;
      };
      return { low: run(0.16, L), lower: run(0.14, L), standard: run(0.16), of: window.Lens.linesOf({ lines: [0.225, 0.188, 0.15] }).map((l) => l[0]),
               bad: [window.Lens.linesOf({ lines: [0.2, 0.25, 0.3] }), window.Lens.linesOf({ lines: [0.3, 0.25] }),
                     window.Lens.linesOf({ lines: [1.2, 0.5, 0.2] }), window.Lens.linesOf({})].map((l) => l[0][0]) };
    });
    expect(out.low).toBe(8);
    expect(out.lower).toBe(null);
    expect(out.standard).toBe(null);
    expect(out.of).toEqual([0.225, 0.188, 0.15]);
    // Anything but three descending scores in (0, 1] is the standard rule.
    expect(out.bad).toEqual([0.3, 0.3, 0.3, 0.3]);
  });

  test("a hunt file's lines reach the screen: the bar is full at that stencil's top line", async ({ page }) => {
    await page.goto("fixture-lines/");
    const withLines = page.locator("#grid .tile").first();
    await withLines.click();
    await expect(page.locator("#lens")).toBeVisible();
    await page.waitForFunction(() => window.Lens.stats().place);
    expect((await page.evaluate(() => window.Lens.stats())).lines).toEqual([0.225, 0.188, 0.15]);
    await page.evaluate(() => window.Lens.fakeScore(0.225));
    await expect(page.locator("#matchfill")).toHaveAttribute("style", /width: 100%/);
    await page.evaluate(() => window.Lens.fakeScore(0.1125));
    await expect(page.locator("#matchfill")).toHaveAttribute("style", /width: 50%/);
    await page.locator("#lensback").click();
    await expect(page.locator("#lens")).toBeHidden();
    // The next stencil has no lines of its own and plays on the standard three.
    await page.locator("#grid .tile").nth(1).click();
    await expect(page.locator("#lens")).toBeVisible();
    await page.waitForFunction(() => window.Lens.stats().place);
    expect((await page.evaluate(() => window.Lens.stats())).lines).toEqual([0.3, 0.25, 0.2]);
  });
});

