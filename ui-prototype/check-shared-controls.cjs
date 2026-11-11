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
    const measure = async (locator) => {
      await locator.evaluate((e) => e.blur());
      await page.mouse.move(1, 1);
      const base = await locator.evaluate((e) => {
        const c = getComputedStyle(e);
        return {
          radius: c.borderRadius,
          border: c.borderWidth,
          bg: c.backgroundColor,
          font: c.fontSize,
          line: c.lineHeight,
          padding: c.paddingTop,
          resize: c.resize,
          height: c.height,
        };
      });
      await locator.focus();
      const focus = await locator.evaluate((e) => {
        const c = getComputedStyle(e);
        return {
          border: c.borderColor,
          shadow: c.boxShadow,
          outline: c.outlineStyle,
        };
      });
      return { base, focus };
    };
    const styles = { search: await measure(page.locator("#list-search")) };
    await page.getByRole("button", { name: "陈屿", exact: true }).click();
    assert.equal(await page.locator(".detail-rail").count(), 0);
    const widths = await page.evaluate(() => ({
      layout: document.querySelector(".detail-layout").clientWidth,
      content: document.querySelector(".detail-content").clientWidth,
    }));
    assert.equal(widths.layout, widths.content);
    await page.screenshot({
      path: "ui-prototype/artifacts/profile-without-rail.png",
    });
    await page
      .getByRole("button", { name: "编辑货品概况", exact: true })
      .click();
    styles.editorInput = await measure(
      page.locator("#section-form input").first(),
    );
    styles.editorTextarea = await measure(
      page.locator("#section-form textarea").first(),
    );
    await page.keyboard.press("Escape");
    await page.getByRole("tab", { name: "备货记录", exact: true }).click();
    await page
      .locator(".shipment")
      .first()
      .getByRole("button", { name: "录入单号", exact: true })
      .click();
    styles.shipmentNumbers = await measure(
      page.locator("#number-form textarea"),
    );
    await page.screenshot({
      path: "ui-prototype/artifacts/number-control-unified.png",
    });
    await page
      .locator("#number-form textarea")
      .fill("DEMO-SHARED-01\nDEMO-SHARED-02");
    await page.getByRole("button", { name: "保存单号", exact: true }).click();
    assert.equal(
      await page.locator(".shipment").first().locator(".number-chip").count(),
      2,
    );
    assert.equal(
      await page.locator(".shipment").first().locator(".state-tag").innerText(),
      "询价中",
    );
    await page.keyboard.press("Escape");
    await page.getByRole("link", { name: "设置", exact: true }).click();
    await page.getByRole("heading", { name: "设置", exact: true }).waitFor();
    styles.time = await measure(page.locator("#daily-time"));
    for (const [name, style] of Object.entries(styles)) {
      assert.equal(style.base.radius, "12px", name);
      assert.equal(style.base.height, "48px", name);
      assert.equal(style.base.border, "1px", name);
      assert.equal(style.base.font, "14px", name);
      assert.equal(style.base.line, "22px", name);
      assert.equal(style.base.padding, "12px", name);
      assert.equal(style.base.resize, "none", name);
      assert.deepEqual(style.focus, styles.search.focus, name);
      assert.equal(style.base.bg, styles.search.base.bg, name);
    }
    await page.getByRole("button", { name: "深色", exact: true }).click();
    const darkTime = await measure(page.locator("#daily-time"));
    await page.getByRole("link", { name: "工作台", exact: true }).click();
    await page.getByRole("heading", { name: "工作台", exact: true }).waitFor();
    const darkSearch = await measure(page.locator("#list-search"));
    assert.deepEqual(darkTime.focus, darkSearch.focus);
    assert.equal(darkTime.base.bg, darkSearch.base.bg);
    assert.deepEqual(errors, []);
    const report = {
      passed: true,
      checks: [
        "All five writing controls share neutral and focus styles",
        "No textarea resize handles",
        "Customer detail rail removed and content spans full width",
        "Shipment number saving preserves stage",
        "Dark controls use the same theme skin",
      ],
      styles,
      consoleErrors: errors,
    };
    fs.writeFileSync(
      "ui-prototype/artifacts/shared-control-checks.json",
      JSON.stringify(report, null, 2),
    );
    console.log("Shared text-control checks passed.");
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exitCode = 1;
});
