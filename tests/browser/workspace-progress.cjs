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
    viewport: { width: 1920, height: 970 },
  });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const base = "http://127.0.0.1:8768";
  await page.goto(base + "/");
  const token = fs
    .readFileSync(process.env.WA_BROWSER_DATA_DIR + "/session-token", "utf8")
    .trim();
  await page.request.post(base + "/login", { data: { token } });
  await page.goto(base + "/workspace?view=pilot");
  const csrf = await page.locator("meta[name=csrf]").getAttribute("content");
  const headers = { "X-CSRF-Token": csrf };
  assert(
    (
      await page.request.post(base + "/__test__/progress-fixture", {
        headers,
        data: {},
      })
    ).ok(),
  );
  await page.reload();
  await page.locator(".progress-card").nth(19).waitFor();
  assert.equal(await page.locator(".progress-card").count(), 20);
  assert.equal(
    await page.locator(".progress-card h3").first().textContent(),
    "客户42",
  );
  await page.locator("#progress-next").click();
  await page.getByText("第 2 / 3 页 · 43 位客户", { exact: true }).waitFor();
  assert.equal(await page.locator(".progress-card").count(), 20);
  await page.locator("#progress-next").click();
  await page.getByText("第 3 / 3 页 · 43 位客户", { exact: true }).waitFor();
  assert.equal(await page.locator(".progress-card").count(), 3);
  assert(await page.locator("#progress-next").isDisabled());
  await page.locator("#progress-prev").click();
  await page.locator("#progress-prev").click();
  const first = page.locator('[data-progress-source="progress-42"]');
  await first.getByRole("button", { name: "暂停分析", exact: true }).click();
  await first.getByRole("button", { name: "继续分析", exact: true }).waitFor();
  await page
    .getByRole("button", { name: "刷新会话与队列", exact: true })
    .click();
  await first.getByRole("button", { name: "继续分析", exact: true }).waitFor();
  await page.reload();
  await first.getByRole("button", { name: "继续分析", exact: true }).click();
  await page.getByText("分析完成，档案已更新。", { exact: true }).waitFor();
  await first.waitFor({ state: "detached" });
  const progress = await (
    await page.request.get(base + "/api/workspace/progress")
  ).json();
  assert.equal(progress.total, 42);
  assert(!progress.items.some((i) => i.source_id === "progress-42"));
  for (const colorScheme of ["dark", "light"]) {
    await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
    for (const width of [1920, 1440, 768, 390]) {
      await page.setViewportSize({ width, height: 970 });
      for (const view of ["today", "scope"]) {
        await page.goto(base + "/workspace?view=" + view);
        const controls = page.locator(
          view === "scope"
            ? '[role=tablist][aria-label="跟进范围"]'
            : ".toolbar.segments",
        );
        await controls.waitFor();
        const boxes = await controls.locator("button").evaluateAll((bs) =>
          bs.map((b) => {
            const r = b.getBoundingClientRect();
            return {
              left: r.left,
              right: r.right,
              top: r.top,
              bottom: r.bottom,
            };
          }),
        );
        for (let n = 1; n < boxes.length; n++)
          if (Math.abs(boxes[n].top - boxes[n - 1].top) < 3)
            assert(
              boxes[n].left - boxes[n - 1].right <= 20,
              "tabs spread across container",
            );
        assert(
          await page.evaluate(
            () => document.documentElement.scrollWidth <= innerWidth,
          ),
          "horizontal overflow",
        );
      }
      if (width === 1920)
        await page.screenshot({
          path: "/tmp/workspace-compact-" + colorScheme + ".png",
          fullPage: false,
        });
    }
  }
  await page.goto(base + "/workspace?view=settings");
  await page.locator("#settings-view").waitFor();
  assert.equal(await page.locator("input[name=budget]").count(), 0);
  await page.getByText(/只统计用量，不设每日 Token 上限/).waitFor();
  assert.deepEqual(errors, []);
  await browser.close();
  console.log(
    "Customer progress pause/resume, 20-item pagination, completed hiding, compact tabs, and budget-free settings passed.",
  );
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
