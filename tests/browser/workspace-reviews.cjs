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
  await page.goto(base + "/");
  await page.request.post(base + "/login", { data: { token } });
  await page.goto(base + "/workspace?view=customers");
  const csrf = await page.locator("meta[name=csrf]").getAttribute("content");
  const post = async (path, data = {}) => {
    const r = await page.request.post(base + path, {
      headers: { "X-CSRF-Token": csrf },
      data,
    });
    assert(r.ok(), await r.text());
    return r.json();
  };
  await post("/api/crm/configure", { enabled: true });
  await post("/__test__/review-fixture");
  await page.reload();
  await page.locator("#dashboard-search input").fill("张先生");
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  await page.locator('[data-open-source="merchant"]').first().click();
  await page.locator("dialog[open]").waitFor();
  const initialRuns = await (
    await page.request.get(base + "/api/workspace/runs")
  ).json();
  let packetRequests = 0;
  page.on("request", (r) => {
    if (r.url().includes("/api/workspace/packets?")) packetRequests++;
  });
  const packet = page.locator("#packet-disclosure > summary");
  await packet.click();
  await page.getByText("我方提到卡航，等待报价反馈", { exact: true }).waitFor();
  await page.getByText("我方（工作微信）", { exact: true }).waitFor();
  assert(!/\bSELF\b/.test(await page.locator("#packet-ledger").innerText()));
  assert.equal(packetRequests, 1);
  await packet.click();
  assert(await page.locator("#packet-ledger").isHidden());
  await packet.click();
  await page.getByText("我方提到卡航，等待报价反馈", { exact: true }).waitFor();
  assert.equal(packetRequests, 1, "reopening must reuse loaded book");
  await packet.click();
  await page.getByRole("button", { name: "关闭详情", exact: true }).click();
  await page.locator('[data-open-source="merchant"]').first().click();
  await page.locator("dialog[open]").waitFor();
  let release;
  const hold = new Promise((resolve) => (release = resolve));
  await page.route(
    "**/api/workspace/packets?*",
    async (route) => {
      await hold;
      await route.continue();
    },
    { times: 1 },
  );
  await packet.click();
  await page.getByText("正在读取已保存资料…", { exact: true }).waitFor();
  await packet.click();
  assert(
    await page.locator("#packet-ledger").isHidden(),
    "can collapse during load",
  );
  release();
  await page.waitForFunction(
    () =>
      document.querySelector("#packet-disclosure").dataset.loaded === "ready",
  );
  assert(
    await page.locator("#packet-ledger").isHidden(),
    "response must not force expansion",
  );
  await packet.click();
  await page.getByText("我方提到卡航，等待报价反馈", { exact: true }).waitFor();
  await packet.click();

  await page.locator("#clue-disclosure > summary").click();
  const cards = page.locator("[data-clue]");
  await cards.first().getByText("核实或编辑这条线索", { exact: true }).click();
  await cards.nth(1).getByText("核实或编辑这条线索", { exact: true }).click();
  await cards.nth(1).locator("textarea").fill("保留的另一条未保存草稿");
  await cards
    .first()
    .locator("textarea")
    .fill("已核对：客户需要我方确认英国报价");
  await cards
    .first()
    .getByRole("button", { name: "保存为已核实资料", exact: true })
    .click();
  assert.equal(
    await page.locator("[data-clue]").count(),
    2,
    "attribution checkbox is required",
  );
  await cards.first().getByRole("checkbox").check();
  await cards
    .first()
    .getByRole("button", { name: "保存为已核实资料", exact: true })
    .click();
  await page
    .getByText("已核实并保存到客户资料；未创建待办。", { exact: true })
    .waitFor();
  assert.equal(
    await page.locator("[data-clue] textarea").inputValue(),
    "保留的另一条未保存草稿",
  );
  await page
    .locator("[data-clue]")
    .getByRole("button", { name: "不采纳此线索", exact: true })
    .click();
  await page
    .getByText("已不采纳，可在已处理线索中撤销。", { exact: true })
    .waitFor();
  assert.equal(await page.locator("[data-clue]").count(), 0);
  await page.reload();
  await page.locator("#dashboard-search input").fill("张先生");
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  await page.locator('[data-open-source="merchant"]').first().click();
  await page.locator("dialog[open]").waitFor();
  assert.equal(await page.locator("[data-clue]").count(), 0);
  await page.locator("#reviewed-clues > summary").click();
  const reviewed = page
    .locator("#reviewed-clues .insight-card")
    .filter({ hasText: "已核对：客户需要我方确认英国报价" });
  await reviewed
    .getByRole("button", { name: "撤销这次判断", exact: true })
    .click();
  await page
    .getByText("已撤销判断，恢复为待核实线索。", { exact: true })
    .waitFor();
  assert.equal(await page.locator("[data-clue]").count(), 1);
  const runs = await (
    await page.request.get(base + "/api/workspace/runs")
  ).json();
  assert.equal(
    runs.length,
    initialRuns.length,
    "review and book browsing must not call model",
  );
  const tabs = page.locator("[data-detail-tab]");
  for (const width of [1440, 768, 600, 390, 320]) {
    await page.setViewportSize({ width, height: 1000 });
    for (const key of ["overview", "work", "timeline", "journal"]) {
      await page.locator("[data-detail-tab=" + key + "]").click();
      const rects = await tabs.evaluateAll((bs) =>
        bs.map((b) => {
          const r = b.getBoundingClientRect();
          return {
            x: r.x,
            y: r.y,
            w: r.width,
            h: r.height,
            scroll: b.scrollWidth,
            client: b.clientWidth,
          };
        }),
      );
      assert(
        Math.max(...rects.map((r) => r.y)) -
          Math.min(...rects.map((r) => r.y)) <
          1,
        "tab y alignment " + width,
      );
      assert(
        Math.max(...rects.map((r) => r.w)) -
          Math.min(...rects.map((r) => r.w)) <
          1,
        "equal-width tabs " + width,
      );
      assert(
        rects.every((r) => r.h >= 44 && r.scroll <= r.client + 1),
        "tab clipping or touch size " + width,
      );
      assert(
        !(await page
          .locator("dialog")
          .evaluate((el) => el.scrollWidth > el.clientWidth + 1)),
        "drawer overflow " + width,
      );
    }
  }
  await page.locator("[data-detail-tab=overview]").click();
  await page.locator("[data-detail-tab=overview]").focus();
  await page.keyboard.press("ArrowRight");
  assert.equal(
    await page.locator("[data-detail-tab=work]").getAttribute("aria-selected"),
    "true",
  );
  await page.keyboard.press("End");
  assert.equal(
    await page
      .locator("[data-detail-tab=journal]")
      .getAttribute("aria-selected"),
    "true",
  );
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
  await page.locator("[data-detail-tab=overview]").click();
  if ((await page.locator("#clue-disclosure").getAttribute("open")) === null)
    await page.locator("#clue-disclosure > summary").click();
  await page
    .locator("[data-clue] details")
    .filter({ has: page.locator("form") })
    .locator("summary")
    .click();
  await page.locator("[data-clue]").scrollIntoViewIfNeeded();
  await page.screenshot({
    path: "/tmp/workspace-review-desktop.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "关闭详情", exact: true }).click();
  assert.equal(
    await page.locator("#dashboard-search input").inputValue(),
    "张先生",
    "opening details must preserve customer search",
  );
  const nav = await page.locator("aside nav button").evaluateAll((bs) =>
    bs.map((b) => {
      const r = b.getBoundingClientRect();
      return { x: r.x, w: r.width, h: r.height };
    }),
  );
  assert(
    nav.every((r) => r.x === nav[0].x && r.w === nav[0].w && r.h >= 44),
    "sidebar alignment",
  );
  assert.deepEqual(errors, []);
  await browser.close();
  console.log(
    "Book collapse/cache, review edit/confirm/dismiss/undo, persistence, SELF labels, tab alignment at 5 widths, keyboard navigation and customer filter preservation passed.",
  );
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
