const { chromium } = require("playwright");
const fs = require("fs");
const assert = require("assert/strict");
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/chromium",
    headless: true,
    args: ["--no-sandbox"],
  });
  const page = await browser.newPage({
    viewport: { width: 1440, height: 1000 },
  });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const base = "http://127.0.0.1:8768";
  const token = fs
    .readFileSync(process.env.WA_BROWSER_DATA_DIR + "/session-token", "utf8")
    .trim();
  let destination = "/workspace?view=customers";
  // The outside page is fulfilled locally; no external service is contacted.
  await page.route("https://outside.invalid/**", (route) =>
    route.fulfill({
      contentType: "text/html",
      body: `<!doctype html><a id="entry" href="${base + destination}">打开本机工作台</a>`,
    }),
  );
  async function openExternal(path) {
    destination = path;
    await page.goto("https://outside.invalid/entry");
    const canonical = base + path.replace("/workspace/", "/workspace");
    const responsePromise = page.waitForResponse(
      (r) => r.url() === canonical && r.request().isNavigationRequest(),
    );
    await page.locator("#entry").click();
    const response = await responsePromise;
    assert.equal(response.status(), 200);
    assert.equal(response.headers()["x-test-fetch-site"], "cross-site");
    await page.waitForURL(canonical);
    assert(
      !(await page.locator("body").innerText()).includes(
        '"error":"cross_site"',
      ),
    );
  }
  async function enter() {
    if (await page.locator("#login").count()) {
      await page.locator("#token").fill(token);
      await page.locator("#login button").click();
    }
    await page.locator("nav [data-view=settings]").waitFor();
  }
  await openExternal("/workspace?view=customers");
  await page.locator("#login").waitFor();
  await enter();
  await page.locator("#customer-search").waitFor();
  await page.getByRole("button", { name: "设置", exact: true }).click();
  await page.locator("#settings-view").waitFor();
  assert.equal(new URL(page.url()).pathname, "/workspace");
  const reload = await page.reload();
  assert.equal(reload.status(), 200);
  await enter();
  await page.locator("#settings-view").waitFor();
  await openExternal("/workspace/?view=scope");
  await enter();
  await page.locator("#scope-view").waitFor();
  await openExternal("/?page=settings");
  await enter();
  await page.locator("#settings-view").waitFor();
  const denied = await page.request.get(base + "/api/workspace/documents", {
    headers: {
      "sec-fetch-site": "cross-site",
      "sec-fetch-mode": "navigate",
      "sec-fetch-dest": "document",
    },
  });
  assert.equal(denied.status(), 403);
  // Revoking this synthetic session must show a login page on the bookmarked URL.
  await page.context().clearCookies();
  await page.goto(base + "/workspace?view=customers");
  await page.locator("#login").waitFor();
  await enter();
  await page.locator("#customer-search").waitFor();
  assert.deepEqual(errors, []);
  await browser.close();
  console.log(
    "Cross-site link clicks with verified navigation metadata, deep-link login, history URL reload, slash redirect, expired sessions and protected API navigation passed.",
  );
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
