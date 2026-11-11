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
      viewport: { width: 1280, height: 900 },
      reducedMotion: "reduce",
    });
    const errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto("http://127.0.0.1:8765/preview.html");
    await page.getByRole("link", { name: "设置", exact: true }).click();
    await page.getByRole("heading", { name: "设置", exact: true }).waitFor();
    assert.equal(await page.locator(".time-zone").count(), 0);
    assert.ok(
      (await page
        .locator(".time-picker-field")
        .evaluate((e) => e.getBoundingClientRect().width)) < 160,
    );
    await page
      .getByRole("button", { name: "选择每日整理时间", exact: true })
      .click();
    await page.getByRole("option", { name: "09 时", exact: true }).click();
    await page.getByRole("option", { name: "45 分", exact: true }).click();
    assert.equal(await page.locator("#daily-time").inputValue(), "08:30");
    await page.screenshot({ path: "ui-prototype/artifacts/time-picker.png" });
    await page
      .locator("#time-popover")
      .getByRole("button", { name: "应用", exact: true })
      .click();
    assert.equal(await page.locator("#daily-time").inputValue(), "09:45");
    await page.locator("#time-trigger").click();
    await page.getByRole("option", { name: "10 时", exact: true }).click();
    await page
      .locator("#time-popover")
      .getByRole("button", { name: "取消", exact: true })
      .click();
    assert.equal(await page.locator("#daily-time").inputValue(), "09:45");
    await page.locator("#time-trigger").click();
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Escape");
    assert.equal(await page.locator("#daily-time").inputValue(), "09:45");
    assert.equal(
      await page
        .locator("#time-popover")
        .evaluate((e) => e.matches(":popover-open")),
      false,
    );
    await page.locator("#daily-time").fill("8:05");
    await page.locator("#daily-time").dispatchEvent("change");
    assert.equal(await page.locator("#daily-time").inputValue(), "08:05");
    await page.reload();
    assert.equal(await page.locator("#daily-time").inputValue(), "08:05");
    await page.getByRole("switch", { name: "每日自动整理" }).click();
    assert.equal(await page.locator("#daily-time").isDisabled(), true);
    assert.equal(await page.locator("#time-trigger").isDisabled(), true);
    assert.deepEqual(errors, []);
    const report = {
      passed: true,
      checks: [
        "Single compact field and clock, no adjacent timezone",
        "Hour/minute draft commits only on Apply",
        "Cancel and Escape retain saved value",
        "Direct typing normalizes and persists",
        "Daily switch disables field and clock together",
      ],
      consoleErrors: errors,
    };
    fs.writeFileSync(
      "ui-prototype/artifacts/time-picker-checks.json",
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
