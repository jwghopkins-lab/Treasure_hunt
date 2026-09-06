// Playwright, headless Chromium, a phone-sized viewport, against a local
// python3 -m http.server serving the site that global-setup builds into
// tests/.site. The fake camera is on for every test; the tests that need a
// particular picture in it launch their own browser with the y4m file.
const { defineConfig, devices } = require("@playwright/test");
const path = require("path");

const SITE = path.join(__dirname, ".site");
const PORT = 8765;

module.exports = defineConfig({
  testDir: __dirname,
  testMatch: /.*\.spec\.js$/,
  globalSetup: require.resolve("./global-setup"),
  timeout: 60000,
  expect: { timeout: 8000 },
  fullyParallel: true,
  workers: process.env.CI ? 2 : 4,
  retries: 0,
  reporter: [["list"]],
  outputDir: path.join(__dirname, "test-results"),
  use: {
    ...devices["Pixel 7"],
    baseURL: `http://127.0.0.1:${PORT}/`,
    permissions: ["geolocation", "camera"],
    geolocation: { latitude: 51.5, longitude: -0.12, accuracy: 20 },
    launchOptions: {
      args: ["--use-fake-device-for-media-stream", "--use-fake-ui-for-media-stream"],
    },
  },
  webServer: {
    command: `python3 -m http.server ${PORT} --bind 127.0.0.1 --directory "${SITE}"`,
    port: PORT,
    reuseExistingServer: true,
    stdout: "ignore",
    stderr: "ignore",
    timeout: 20000,
  },
});
