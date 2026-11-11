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
    const checks = [];
    const animations = await page.evaluate(() => {
      document.querySelector("#tab-contacts").click();
      return {
        line: document.querySelector(".workspace-indicator").getAnimations()
          .length,
        panel: document.querySelector(".list-surface").getAnimations().length,
      };
    });
    assert.equal(animations.line, 1);
    assert.equal(animations.panel, 1);
    await page.getByRole("tab", { name: /商家档案/ }).click();
    await page.locator("#filter-trigger").click();
    await page.getByRole("option", { name: "待更新", exact: true }).click();
    assert.equal(await page.locator(".merchant-table tbody tr").count(), 1);
    assert.match(
      await page.locator(".merchant-table tbody").innerText(),
      /陈屿/,
    );
    await page.locator("#filter-trigger").click();
    await page.getByRole("option", { name: "待整理", exact: true }).click();
    assert.equal(await page.locator(".merchant-table tbody tr").count(), 1);
    assert.match(
      await page.locator(".merchant-table tbody").innerText(),
      /叶青/,
    );
    await page.locator("#filter-trigger").click();
    await page.getByRole("option", { name: "全部资料", exact: true }).click();
    checks.push(
      "Workspace underline and content animate; pending-update and first-analysis filters differ",
    );
    await page.getByRole("button", { name: "陈屿", exact: true }).click();
    assert.equal(
      await page.locator(".current-identity .role-tag").innerText(),
      "商家",
    );
    assert.equal(await page.locator(".detail-rail").count(), 0);
    assert.equal(
      await page
        .locator(".detail-layout")
        .evaluate((e) => getComputedStyle(e).display),
      "block",
    );
    await page
      .getByRole("button", { name: "编辑货品概况", exact: true })
      .click();
    const save = page.getByRole("button", { name: "保存资料", exact: true });
    assert.equal(await save.isDisabled(), true);
    const input = page.locator("#section-form input").first();
    await input.fill("");
    await save.click();
    assert.equal(await input.getAttribute("aria-invalid"), "true");
    assert.match(await page.locator(".input-error").innerText(), /主营类目/);
    await input.fill("家居日用");
    assert.equal(await input.getAttribute("aria-invalid"), null);
    await input.focus();
    const focus = await input.evaluate((e) => ({
      outline: getComputedStyle(e).outlineStyle,
      border: getComputedStyle(e).borderColor,
      shadow: getComputedStyle(e).boxShadow,
    }));
    assert.equal(focus.outline, "none");
    assert.match(focus.shadow, /3px/);
    await page.waitForTimeout(250);
    await page.screenshot({
      path: "ui-prototype/artifacts/editor-polished.png",
    });
    await save.click();
    assert.match(
      await page.locator(".dossier-card").first().innerText(),
      /家居日用/,
    );
    checks.push(
      "Current identity and metadata tags; dirty/save/invalid/focus states in shared editor",
    );
    await page.keyboard.press("Escape");
    await page.waitForFunction(
      () => !document.querySelector("#detail-dialog").open,
    );
    await page
      .getByRole("button", { name: "切换深色外观", exact: true })
      .click();
    await page.waitForTimeout(350);
    await page.addStyleTag({ content: "body { background: white; }" });
    const backgrounds = await page.evaluate(() =>
      ["html", "body", "main"].map((s) => ({
        element: s,
        bg: getComputedStyle(document.querySelector(s)).backgroundColor,
      })),
    );
    backgrounds.forEach((x) => assert.equal(x.bg, "rgb(22, 22, 23)"));
    assert.equal(
      await page.locator(".theme-quick").getAttribute("aria-pressed"),
      "true",
    );
    await page.getByRole("link", { name: "设置", exact: true }).click();
    await page.getByRole("heading", { name: "设置", exact: true }).waitFor();
    await page.locator("#daily-time").focus();
    await page.waitForTimeout(250);
    await page.screenshot({
      path: "ui-prototype/artifacts/settings-dark-fixed.png",
    });
    await page.locator("#daily-time").fill("28:90");
    await page.locator("#daily-time").dispatchEvent("change");
    assert.equal(
      await page.locator("#daily-time").getAttribute("aria-invalid"),
      "true",
    );
    await page.locator("#daily-time").fill("9:05");
    await page.locator("#daily-time").dispatchEvent("change");
    assert.equal(await page.locator("#daily-time").inputValue(), "09:05");
    assert.equal(
      await page.locator("#daily-time").getAttribute("aria-invalid"),
      null,
    );
    await page.reload();
    assert.equal(await page.locator("#daily-time").inputValue(), "09:05");
    assert.equal(await page.locator("html").getAttribute("data-theme"), "dark");
    await page.getByRole("link", { name: "工作台", exact: true }).click();
    await page.getByRole("heading", { name: "工作台", exact: true }).waitFor();
    await page.getByRole("button", { name: "陈屿", exact: true }).click();
    await page.waitForTimeout(350);
    await page.screenshot({
      path: "ui-prototype/artifacts/profile-dark-tags.png",
    });
    await page.keyboard.press("Escape");
    await page.waitForFunction(
      () => !document.querySelector("#detail-dialog").open,
    );
    await page
      .getByRole("button", { name: "切换浅色外观", exact: true })
      .click();
    await page.waitForTimeout(350);
    await page.getByRole("button", { name: "陈屿", exact: true }).click();
    await page.waitForTimeout(350);
    await page.screenshot({
      path: "ui-prototype/artifacts/profile-glass-desktop.png",
    });
    checks.push(
      "Sun/moon toggle animates, persists, and explicit dark page backgrounds resist white host body",
    );
    checks.push(
      "Time field validates inline, normalizes 9:05, and persists valid values only",
    );
    await page.emulateMedia({ reducedMotion: "reduce" });
    await page.keyboard.press("Escape");
    const reduced = await page.evaluate(() => {
      document.querySelector("#tab-contacts").click();
      return document.querySelector(".workspace-indicator").getAnimations()
        .length;
    });
    assert.equal(reduced, 0);
    assert.deepEqual(errors, []);
    checks.push("Reduced-motion preference disables workspace movement");
    const report = { passed: true, checks, backgrounds, consoleErrors: errors };
    fs.writeFileSync(
      "ui-prototype/artifacts/control-polish-checks.json",
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
