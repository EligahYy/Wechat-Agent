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
      reducedMotion: "no-preference",
    });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto("http://127.0.0.1:8765/preview.html");
    await page.getByRole("tab", { name: /全部联系人/ }).click();
    await page.waitForTimeout(350);
    await page.evaluate(() => {
      window.keepToolbar = document.querySelector(".filter-group");
      window.keepTable = document.querySelector(".contacts-table");
      window.keepRow = document.querySelector(".contacts-table tbody tr");
    });
    await page.locator('[data-filter="商家"]').click();
    assert.equal(
      await page.evaluate(
        () =>
          window.keepToolbar === document.querySelector(".filter-group") &&
          window.keepTable === document.querySelector(".contacts-table") &&
          window.keepRow === document.querySelector(".contacts-table tbody tr"),
      ),
      true,
    );
    assert.equal(
      await page
        .locator("#list-region")
        .evaluate((e) => getComputedStyle(e).opacity),
      "1",
    );
    for (const role of ["服务商", "平台", "待识别", "全部"])
      await page.locator(`[data-filter="${role}"]`).click();
    await page.waitForTimeout(350);
    assert.equal(await page.locator(".role-filter-indicator").count(), 1);
    await page.screenshot({
      path: "ui-prototype/artifacts/typography-contact-list.png",
    });
    const btn = page.locator(".head-actions .btn").first();
    await page.mouse.move(800, 50);
    await page.waitForTimeout(250);
    const before = await btn.boundingBox();
    await btn.hover();
    await page.waitForTimeout(250);
    const after = await btn.boundingBox();
    assert.ok(Math.abs(before.y - after.y) < 0.1);
    assert.equal(
      await btn.evaluate((e) => getComputedStyle(e).transform),
      "none",
    );
    await page.getByRole("tab", { name: /商家档案/ }).click();
    await page.getByRole("button", { name: "陈屿", exact: true }).click();
    await page
      .getByRole("button", { name: "查看物流需求来源", exact: true })
      .click();
    await page.waitForTimeout(350);
    const first = page.locator(".evidence-group").first();
    await first.locator("summary").click();
    assert.equal(await first.evaluate((e) => e.open), true);
    assert.ok((await first.evaluate((e) => e.getAnimations().length)) > 0);
    await page.waitForFunction(
      () => !document.querySelector(".evidence-group").open,
    );
    await first.locator("summary").click();
    await page.waitForFunction(
      () =>
        document.querySelector(".evidence-group").open &&
        !document.querySelector(".evidence-group")._accordion,
    );
    await first.locator("summary").evaluate((e) => {
      e.click();
      e.click();
      e.click();
    });
    await page.waitForFunction(
      () => !document.querySelector(".evidence-group").open,
    );
    await page.keyboard.press("Escape");
    await page.waitForFunction(
      () => !document.querySelector("#overlay-dialog").open,
    );
    await page
      .getByRole("button", { name: "编辑货品概况", exact: true })
      .click();
    await page.waitForTimeout(350);
    const hierarchy = await page.evaluate(() => ({
      dialog: parseFloat(
        getComputedStyle(document.querySelector(".overlay-header h2")).fontSize,
      ),
      group: parseFloat(
        getComputedStyle(document.querySelector(".editor-group legend"))
          .fontSize,
      ),
      label: parseFloat(
        getComputedStyle(document.querySelector(".editor-field>span")).fontSize,
      ),
      value: parseFloat(
        getComputedStyle(document.querySelector(".editor-field input"))
          .fontSize,
      ),
    }));
    assert.ok(
      hierarchy.dialog > hierarchy.group && hierarchy.group > hierarchy.label,
    );
    assert.equal(hierarchy.value, 14);
    await page
      .getByRole("textbox", { name: "补充资料", exact: true })
      .fill("人工补充：本批外包装需要防潮。");
    await page.screenshot({
      path: "ui-prototype/artifacts/editor-typography-supplement.png",
    });
    await page.getByRole("button", { name: "保存资料", exact: true }).click();
    assert.match(
      await page.locator(".dossier-card").first().innerText(),
      /人工补充：本批外包装/,
    );
    assert.ok(
      (await page
        .locator(".overview-intro .eyebrow")
        .evaluate((e) => parseFloat(getComputedStyle(e).fontSize))) >= 12,
    );
    await page.waitForTimeout(300);
    await page.screenshot({
      path: "ui-prototype/artifacts/profile-readable-tags.png",
    });
    await page.reload();
    await page.getByRole("button", { name: "陈屿", exact: true }).click();
    assert.match(
      await page.locator(".dossier-supplement").innerText(),
      /人工补充：本批外包装/,
    );
    await page
      .getByRole("button", { name: "查看货品概况来源", exact: true })
      .click();
    assert.equal(
      await page
        .locator(".evidence-sections")
        .getByText("人工补充：本批外包装需要防潮。", { exact: true })
        .count(),
      0,
    );
    await page.keyboard.press("Escape");
    await page.waitForFunction(
      () => !document.querySelector("#overlay-dialog").open,
    );
    await page
      .getByRole("button", { name: "编辑货品概况", exact: true })
      .click();
    await page.getByRole("textbox", { name: "补充资料", exact: true }).fill("");
    await page.getByRole("button", { name: "保存资料", exact: true }).click();
    assert.equal(await page.locator(".dossier-supplement").count(), 0);
    assert.deepEqual(errors, []);
    const report = {
      passed: true,
      checks: [
        "Filter preserves toolbar, table and retained rows without whole-list opacity reset",
        "Stable button hover geometry",
        "Accordion closes, opens and reverses on rapid clicks",
        "Dialog/group/label typography hierarchy",
        "Manual supplement saves, reloads and removes independently of source evidence",
        "Larger status labels",
      ],
      hierarchy,
      consoleErrors: errors,
    };
    fs.writeFileSync(
      "ui-prototype/artifacts/motion-typography-checks.json",
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
