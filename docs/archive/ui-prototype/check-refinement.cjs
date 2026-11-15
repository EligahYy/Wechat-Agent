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
    await page.getByRole("button", { name: "陈屿", exact: true }).click();
    await page.waitForTimeout(350);
    assert.equal(
      await page.locator(".detail-header .header-avatar").count(),
      1,
    );
    assert.equal(await page.locator(".detail-rail .avatar").count(), 0);
    assert.equal(
      await page.getByRole("button", { name: "修改身份", exact: true }).count(),
      1,
    );
    assert.equal(await page.locator(".detail-title-row .role-tag").count(), 1);
    assert.equal(
      await page
        .locator(".detail-header")
        .getByText("CY Home", { exact: false })
        .count(),
      0,
    );
    await page.screenshot({
      path: "ui-prototype/artifacts/profile-unified-header.png",
    });
    await page
      .getByRole("button", { name: "编辑物流需求", exact: true })
      .click();
    assert.equal(await page.locator("#section-form input").count(), 3);
    assert.equal(await page.locator("#section-form textarea").count(), 7);
    assert.equal(await page.locator(".editor-group").count(), 4);
    const boxes = await page.locator("#section-form input").evaluateAll((es) =>
      es.map((e) => ({
        x: e.getBoundingClientRect().x,
        y: e.getBoundingClientRect().y,
        h: parseFloat(getComputedStyle(e).height),
      })),
    );
    assert.equal(boxes[0].y, boxes[1].y);
    assert.ok(boxes.every((b) => b.h === 48));
    assert.equal(
      await page
        .locator("#section-form textarea")
        .first()
        .evaluate((e) => getComputedStyle(e).resize),
      "none",
    );
    assert.equal(
      await page
        .getByRole("button", { name: "保存资料", exact: true })
        .isDisabled(),
      true,
    );
    await page
      .locator("#section-form input")
      .first()
      .fill("浙江义乌 · 待约提货");
    await page.getByRole("button", { name: "保存资料", exact: true }).click();
    assert.match(
      await page.locator(".dossier-card").last().innerText(),
      /待约提货/,
    );
    await page
      .getByRole("button", { name: "编辑物流需求", exact: true })
      .click();
    await page.waitForTimeout(350);
    await page.screenshot({
      path: "ui-prototype/artifacts/logistics-editor-compact.png",
    });
    await page.keyboard.press("Escape");
    await page.waitForFunction(
      () => !document.querySelector("#overlay-dialog").open,
    );
    await page.keyboard.press("Escape");
    await page.waitForFunction(
      () => !document.querySelector("#detail-dialog").open,
    );
    const input = page.getByRole("searchbox", { name: "搜索商家档案" });
    await input.fill("陈");
    assert.ok(
      (await page
        .locator("#list-region")
        .evaluate((e) => e.getAnimations().length)) > 0,
    );
    await input.fill("陈屿");
    await page.getByRole("button", { name: "清空搜索", exact: true }).click();
    await page.waitForTimeout(300);
    assert.equal(await page.locator(".merchant-table tbody tr").count(), 6);
    assert.equal(
      await page
        .getByText("按联系人归一 · 结论可查来源", { exact: true })
        .count(),
      0,
    );
    await page.getByRole("tab", { name: /全部联系人/ }).click();
    await page.waitForTimeout(350);
    await page.evaluate(() => {
      window.originalFirstRow = document.querySelector(
        ".contacts-table tbody tr",
      );
    });
    const checkbox = page.getByRole("checkbox", {
      name: "选择陈屿",
      exact: true,
    });
    await checkbox.check();
    assert.equal(
      await page.evaluate(
        () =>
          window.originalFirstRow ===
          document.querySelector(".contacts-table tbody tr"),
      ),
      true,
    );
    assert.ok(
      (await page
        .locator(".selection-slot")
        .evaluate((e) => e.getAnimations().length)) > 0,
    );
    await page.waitForTimeout(300);
    assert.match(await page.locator(".selection-bar").innerText(), /已选 1/);
    const batch = page.getByRole("button", { name: "设置身份", exact: true });
    await batch.hover();
    await page.waitForTimeout(180);
    assert.notEqual(
      await batch.evaluate((e) => getComputedStyle(e).boxShadow),
      "none",
    );
    await page.screenshot({
      path: "ui-prototype/artifacts/selection-toolbar-smooth.png",
    });
    await checkbox.uncheck();
    await page.waitForTimeout(300);
    assert.equal(
      await page.locator(".selection-slot").getAttribute("aria-hidden"),
      "true",
    );
    assert.equal(
      await page
        .locator(".selection-slot")
        .evaluate((e) => Math.round(e.getBoundingClientRect().height)),
      0,
    );
    await page
      .getByRole("checkbox", { name: "选择本页联系人", exact: true })
      .check();
    await page.getByRole("button", { name: "清空", exact: true }).click();
    await page.waitForTimeout(300);
    assert.equal(
      await page.locator("[data-contact-select]:checked").count(),
      0,
    );
    assert.deepEqual(errors, []);
    const report = {
      passed: true,
      checks: [
        "Single identity header with avatar",
        "Compact grouped editor: three single-line and six auto-height fields",
        "Editor save and persistence",
        "Animated search and clear",
        "Removed footer copy",
        "Selection toolbar transitions without rebuilding rows",
        "Select-page and clear",
        "Batch identity button hover",
      ],
      consoleErrors: errors,
    };
    fs.writeFileSync(
      "ui-prototype/artifacts/editor-selection-checks.json",
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
