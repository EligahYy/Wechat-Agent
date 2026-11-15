const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/chromium",
    headless: true,
    args: ["--no-sandbox"],
  });
  try {
    const page = await browser.newPage({
      viewport: { width: 1440, height: 1050 },
      reducedMotion: "reduce",
    });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto("http://127.0.0.1:8765/preview.html");
    await page.getByRole("button", { name: "同步并整理", exact: true }).click();
    assert.match(
      await page.locator("#overlay-dialog").innerText(),
      /微信未连接/,
    );
    await page.screenshot({ path: "ui-prototype/artifacts/sync-entry.png" });
    await page.getByRole("button", { name: "前往设置", exact: true }).click();
    await page.getByRole("heading", { name: "设置", exact: true }).waitFor();
    await page.getByRole("link", { name: "工作台", exact: true }).click();
    await page.getByRole("heading", { name: "工作台", exact: true }).waitFor();
    await page.getByRole("button", { name: "陈屿", exact: true }).click();
    await page.screenshot({
      path: "ui-prototype/artifacts/customer-sync-entry.png",
    });
    await page.getByRole("button", { name: "同步此客户", exact: true }).click();
    assert.match(
      await page.locator("#overlay-dialog").innerText(),
      /此联系人的私信与相关群聊/,
    );
    await page.getByRole("button", { name: "演示整理", exact: true }).click();
    assert.equal(await page.locator(".queue-list li").count(), 1);
    assert.match(await page.locator(".queue-list").innerText(), /陈屿/);
    await page
      .locator("#overlay-dialog")
      .getByRole("button", { name: "停止本次", exact: true })
      .click();
    await page.keyboard.press("Escape");
    await page.keyboard.press("Escape");
    await page.getByRole("tab", { name: /全部联系人/ }).click();
    const colors = await page
      .locator(".contacts-table .role-tag")
      .evaluateAll((es) =>
        Object.fromEntries(
          es.map((e) => [e.textContent, getComputedStyle(e).color]),
        ),
      );
    assert.equal(colors["服务商"], "rgb(112, 70, 170)");
    assert.equal(colors["平台"], "rgb(24, 112, 80)");
    await page.screenshot({
      path: "ui-prototype/artifacts/contact-role-colors.png",
    });
    await page
      .getByRole("button", { name: "陆远 · 海运服务", exact: true })
      .click();
    await page.getByRole("button", { name: "同步消息", exact: true }).click();
    assert.equal(
      await page.getByRole("button", { name: "演示整理", exact: true }).count(),
      0,
    );
    assert.deepEqual(errors, []);
    const report = {
      passed: true,
      checks: [
        "Global sync entry shows unconnected source",
        "Settings navigation works",
        "Customer sync handles private/group scope",
        "Single customer demo queues one merchant",
        "Non-merchants do not start analysis",
        "Provider purple and platform green",
      ],
      colors,
      consoleErrors: errors,
    };
    fs.writeFileSync(
      "ui-prototype/artifacts/sync-entry-checks.json",
      JSON.stringify(report, null, 2),
    );
    console.log(JSON.stringify(report, null, 2));
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
