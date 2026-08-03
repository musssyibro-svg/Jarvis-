/**
 * tools/check_ui.mjs — does the UI actually put pixels on the screen?
 *
 * WHY THIS EXISTS
 *
 * `npm run build` passed while the app was completely broken. A circular import
 * (JarvisOS.jsx -> pages/Planner.jsx -> JarvisOS.jsx) threw
 * "Cannot access 'T' before initialization" the moment the browser evaluated the
 * module graph, so React never mounted and the page was blank and white — with
 * every single file returning HTTP 200 in the network tab, because loading was
 * never the problem. Evaluation was.
 *
 * Rollup bundles into one scope and hoists, so the cycle resolves at BUILD time
 * and the build is green. Vite's dev server evaluates each module natively with
 * strict temporal-dead-zone semantics, so it is not. Dev and prod genuinely
 * disagree, which means a passing build is not evidence that the app runs.
 *
 * So this loads the real dev server in a real browser and asserts the only thing
 * that actually matters: something rendered.
 *
 *     node tools/check_ui.mjs                 # starts vite itself
 *     node tools/check_ui.mjs http://...:5173 # checks a server already running
 *
 * Exit 0 = the UI rendered. Exit 1 = blank page, with the exception printed.
 *
 * Chromium comes from Playwright, which this project already depends on for
 * browser automation — no new dependency for the sake of a test.
 */
import { spawn } from "node:child_process";
import { setTimeout as sleep } from "node:timers/promises";

const PORT = 5199;                  // deliberately not 5173, so it can run while
const OWN_URL = `http://127.0.0.1:${PORT}/`;   // you have the real UI open
const given = process.argv[2];

let vite = null;

async function waitForServer(url, seconds = 40) {
  for (let i = 0; i < seconds * 2; i++) {
    try {
      const r = await fetch(url);
      if (r.ok) return true;
    } catch { /* not up yet */ }
    await sleep(500);
  }
  return false;
}

function startVite() {
  const npx = process.platform === "win32" ? "npx.cmd" : "npx";
  const child = spawn(npx, ["vite", "--port", String(PORT), "--strictPort"], {
    cwd: new URL("../frontend/", import.meta.url).pathname,
    stdio: ["ignore", "pipe", "pipe"],
    detached: false,
  });
  child.stdout.on("data", () => {});
  child.stderr.on("data", () => {});
  return child;
}

async function main() {
  let url = given;
  if (!url) {
    console.log(`Starting vite on ${PORT}...`);
    vite = startVite();
    if (!(await waitForServer(OWN_URL))) {
      console.error("vite never came up. Run `npm install` in frontend/ first.");
      return 1;
    }
    url = OWN_URL;
  } else if (!(await waitForServer(url, 10))) {
    console.error(`Nothing is serving ${url}`);
    return 1;
  }

  // Playwright lives in frontend/node_modules, and Node resolves bare specifiers
  // upward from THIS file — which never reaches frontend/. Resolve explicitly.
  // playwright ships CommonJS, so `await import()` of its resolved path hands
  // back a namespace whose named exports aren't reliably picked up. require()
  // it directly and read `chromium` off the object.
  let chromium;
  try {
    const { createRequire } = await import("node:module");
    const req = createRequire(new URL("../frontend/package.json", import.meta.url));
    chromium = req("playwright").chromium;
    if (!chromium) throw new Error("no chromium export");
  } catch {
    try {
      const mod = await import("playwright");
      chromium = mod.chromium || mod.default?.chromium;
      if (!chromium) throw new Error("no chromium export");
    } catch {
      console.error("This check needs Playwright's node package:");
      console.error("    cd frontend && npm i -D playwright");
      console.error("Skipping — the UI is UNVERIFIED, which is not the same as working.");
      return 2;                     // distinct from a real failure
    }
  }

  // Launch the default way first — that is what works on a normal machine after
  // `npx playwright install`. Some environments (this project's own container,
  // CI images) ship Chromium somewhere else and set PLAYWRIGHT_BROWSERS_PATH=0,
  // which points Playwright at a local folder that has no browser in it. Rather
  // than fail there, try the known locations before giving up.
  const candidates = [
    process.env.JARVIS_CHROMIUM,
    "/opt/pw-browsers/chromium",
    "/opt/pw-browsers/chromium-1194/chrome-linux/chrome",
    "/usr/bin/chromium",
    "/usr/bin/chromium-browser",
    "/usr/bin/google-chrome",
  ].filter(Boolean);

  let browser = null;
  let launchError = null;
  for (const executablePath of [null, ...candidates]) {
    try {
      browser = await chromium.launch(executablePath ? { executablePath } : {});
      break;
    } catch (e) {
      launchError = e;
    }
  }
  if (!browser) {
    console.error("Couldn't start a browser to look at the page:");
    console.error("   " + String(launchError?.message || launchError).split("\n")[0]);
    console.error("Install one with:  npx playwright install chromium");
    console.error("Skipping — the UI is UNVERIFIED, which is not the same as working.");
    return 2;
  }
  const page = await browser.newPage();

  // Only crashes matter. Failed fetches to a backend that isn't running are
  // expected when checking the UI on its own, and counting them as failures
  // would make this test cry wolf until nobody reads it.
  const crashes = [];
  page.on("pageerror", (e) => crashes.push(String(e.message || e)));
  page.on("console", (m) => {
    const t = m.text();
    if (m.type() === "error" && !/ERR_CONNECTION_REFUSED|Failed to fetch|net::/i.test(t)) {
      crashes.push("console: " + t);
    }
  });

  // NOT networkidle. The console holds an SSE connection to /orchestrator/feed
  // that never closes, so the network is never idle while the backend is up —
  // waiting for that meant this check only worked when the backend was DOWN,
  // which is the least interesting case. Load the document, then give React a
  // moment to mount.
  await page.goto(url, { waitUntil: "domcontentloaded", timeout: 60000 });
  await page.waitForTimeout(3000);

  const mounted = await page.evaluate(
    () => document.getElementById("root")?.children.length ?? -1);
  const bg = await page.evaluate(
    () => getComputedStyle(document.body).backgroundColor);
  const text = await page.evaluate(
    () => (document.getElementById("root")?.innerText || "").trim());

  await browser.close();

  console.log(`  mounted elements : ${mounted}`);
  console.log(`  body background  : ${bg}`);
  console.log(`  visible text     : ${text.slice(0, 90).replace(/\n/g, " / ") || "(none)"}`);
  console.log(`  crashes          : ${crashes.length}`);
  crashes.slice(0, 5).forEach((c) => console.log(`     ${c.slice(0, 160)}`));

  if (mounted <= 0) {
    console.error("\nFAIL — React did not mount. The page is blank.");
    if (crashes.length) console.error(`The exception was: ${crashes[0]}`);
    else console.error("No exception was raised; check main.jsx and index.html.");
    return 1;
  }
  if (crashes.length) {
    console.error("\nFAIL — it rendered, but threw. Those errors are real bugs.");
    return 1;
  }
  // A transparent body means index.css never applied, which is the fingerprint
  // of a module graph that died before main.jsx finished its imports.
  if (/rgba\(0, 0, 0, 0\)/.test(bg)) {
    console.error("\nFAIL — the stylesheet never applied; the import chain broke.");
    return 1;
  }
  console.log("\nOK — the UI mounts and renders.");
  return 0;
}

let code = 1;
try {
  code = await main();
} catch (e) {
  console.error("check_ui crashed:", e.message);
  code = 1;
} finally {
  if (vite) { try { vite.kill("SIGTERM"); } catch { /* already gone */ } }
}
process.exit(code);
