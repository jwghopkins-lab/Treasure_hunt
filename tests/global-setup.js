// Build every page the suites open, from the fixture hunts, with a stubbed
// Supabase config the tests intercept, and the fake-camera files.
const { execFileSync } = require("child_process");
const fs = require("fs");
const path = require("path");

const ROOT = path.resolve(__dirname, "..");
const SITE = path.join(__dirname, ".site");
const Y4M = path.join(__dirname, ".y4m");
const STUB = path.join(__dirname, "content", "supabase-stub.json");

function py(args) {
  execFileSync("python3", args, { cwd: ROOT, stdio: ["ignore", "inherit", "inherit"] });
}

module.exports = async () => {
  fs.rmSync(SITE, { recursive: true, force: true });
  fs.mkdirSync(SITE, { recursive: true });
  fs.mkdirSync(Y4M, { recursive: true });
  const build = path.join(ROOT, "pipeline", "build.py");
  py([build, "content/fixture.json", path.join(SITE, "fixture"), "--supabase", STUB]);
  py([build, "tests/content/fixture-image.json", path.join(SITE, "fixture-image"), "--supabase", STUB]);
  py([build, "tests/content/fixture-plain.json", path.join(SITE, "fixture-plain"), "--supabase", STUB]);
  py([build, "content/fixture.json", path.join(SITE, "fixture-nosb"), "--no-supabase"]);
  py([build, "--capture", path.join(SITE, "capture"), "--supabase", STUB]);
  py([build, "--capture", path.join(SITE, "capture-nosb"), "--no-supabase"]);
  py([build, "--index", path.join(SITE, "index.html"), "content/fixture.json"]);

  // The fake camera's pictures: a blank grey frame, and every fixture
  // photograph at its own portrait size.
  const y4m = path.join(__dirname, "png2y4m.py");
  const grey = path.join(Y4M, "grey.y4m");
  if (!fs.existsSync(grey)) py([y4m, "--grey", "600x800", grey]);
  const photos = path.join(ROOT, "photos", "fixture");
  for (const f of fs.readdirSync(photos)) {
    if (!/\.(jpe?g|png)$/i.test(f)) continue;
    const out = path.join(Y4M, "fixture-" + f.replace(/\.[^.]+$/, "").toLowerCase().replace(/\s+/g, "-") + ".y4m");
    if (!fs.existsSync(out) || fs.statSync(out).mtimeMs < fs.statSync(path.join(photos, f)).mtimeMs) {
      py([y4m, path.join(photos, f), out]);
    }
  }
};
