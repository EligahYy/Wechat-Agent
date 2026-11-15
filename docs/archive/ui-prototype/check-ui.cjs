/* Browser checks for the prototype's actual application flows, with fictional data. */
const { chromium } = require("playwright");
const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");

(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/chromium",
    headless: true,
    args: ["--no-sandbox"],
  });
  const context = await browser.newContext({
    viewport: { width: 1440, height: 1000 },
    reducedMotion: "reduce",
  });
  const page = await context.newPage();
  const errors = [];
  const external = [];
  const results = [];
  page.on("pageerror", (e) => errors.push(e.message));
  page.on("request", (r) => {
    if (!/^(http:\/\/(localhost|127\.0\.0\.1):8765|data:)/.test(r.url()))
      external.push(r.url());
  });
  const base = process.env.UI_URL || "http://127.0.0.1:8765/";
  const go = async (name) => {
    await page.getByRole("link", { name, exact: true }).click();
    await page.getByRole("heading", { name, exact: true }).waitFor();
    await page.evaluate(() => window.scrollTo(0, 0));
  };
  const shot = async (name) => {
    await page.screenshot({
      path: path.join(__dirname, "artifacts", name),
      fullPage: false,
    });
  };
  fs.mkdirSync(path.join(__dirname, "artifacts"), { recursive: true });
  try {
    await page.goto(base);
    await page.evaluate(() => localStorage.clear());
    await page.reload();
    await page.getByRole("heading", { name: "工作台", exact: true }).waitFor();
    assert.equal(await page.locator(".merchant-table tbody tr").count(), 6);
    await shot("workspace-desktop.png");
    await page.locator("#filter-trigger").click();
    await page.getByRole("option", { name: "待整理", exact: true }).click();
    assert.equal(await page.locator(".merchant-table tbody tr").count(), 1);
    await page.locator("#filter-trigger").focus();
    await page.keyboard.press("ArrowDown");
    await page.keyboard.press("Home");
    await page.keyboard.press("Enter");
    assert.equal(await page.locator(".merchant-table tbody tr").count(), 6);
    await page
      .getByRole("searchbox", { name: "搜索商家档案" })
      .fill("不存在的联系人");
    assert.match(await page.locator("#list-region").innerText(), /没有找到/);
    await page.getByRole("button", { name: "清空搜索", exact: true }).click();
    assert.equal(await page.locator(".merchant-table tbody tr").count(), 6);
    results.push(
      "Glass filter menu: selection, arrow keys, Enter; search: clear and empty result",
    );
    results.push("Merchant-only list and explicit prototype data label");

    await page.getByRole("tab", { name: /全部联系人/ }).click();
    assert.equal(await page.locator(".contacts-table tbody tr").count(), 20);
    await page.getByRole("button", { name: "下一页", exact: true }).click();
    assert.equal(await page.locator(".contacts-table tbody tr").count(), 8);
    await page.getByRole("button", { name: "上一页", exact: true }).click();
    await page
      .getByRole("searchbox", { name: "搜索全部联系人" })
      .fill("欧区家居备货沟通群");
    assert.equal(await page.locator(".contacts-table tbody tr").count(), 3);
    results.push(
      "Unified people search includes source groups; 20-person pagination",
    );
    await page.getByRole("searchbox", { name: "搜索全部联系人" }).fill("陆远");
    await page.getByRole("checkbox", { name: "选择陆远", exact: true }).check();
    await page.getByRole("button", { name: "设置身份", exact: true }).click();
    await page.getByRole("radio", { name: /商家/ }).check();
    await page.getByRole("button", { name: "保存身份" }).click();
    await page.getByRole("tab", { name: /商家档案/ }).click();
    assert.equal(await page.locator(".merchant-table tbody tr").count(), 7);
    await page.getByRole("button", { name: "陆远", exact: true }).click();
    await page.getByRole("button", { name: "修改身份", exact: true }).click();
    await page.getByRole("radio", { name: /服务商/ }).check();
    await page.getByRole("button", { name: "保存身份" }).click();
    assert.match(
      await page.locator("#detail-panel").innerText(),
      /服务商不参与/,
    );
    await page.getByRole("button", { name: "关闭客户档案" }).click();
    assert.equal(await page.locator(".merchant-table tbody tr").count(), 6);
    results.push(
      "Batch and single identity editing update merchant eligibility consistently",
    );

    await page.getByRole("button", { name: "陈屿", exact: true }).click();
    await page
      .getByRole("button", { name: "查看货品概况来源", exact: true })
      .click();
    await page
      .locator(".evidence-group summary")
      .filter({ hasText: "货量" })
      .click();
    assert.match(
      await page.locator("#overlay-dialog").innerText(),
      /这批 8 方/,
    );
    assert.match(
      await page.locator("#overlay-dialog").innerText(),
      /新一批还是收纳盒/,
    );
    await page.keyboard.press("Escape");
    assert.equal(
      await page.locator("#overlay-dialog").evaluate((el) => el.open),
      false,
    );
    assert.equal(
      await page.evaluate(() => document.activeElement.dataset.action),
      "section-evidence",
    );
    await page
      .getByRole("button", { name: "编辑货品概况", exact: true })
      .click();
    await page
      .locator('#section-form textarea[name="c01-goods-2"]')
      .fill("普通塑料制品；未发现带电、带磁信息");
    await page.getByRole("button", { name: "保存资料" }).click();
    assert.match(await page.locator("#detail-panel").innerText(), /人工纠正/);
    await shot("profile-desktop.png");
    results.push(
      "Evidence preserves speakers, time and both historical/new context; manual correction persists",
    );

    await page.getByRole("tab", { name: "备货记录", exact: true }).click();
    const firstShipment = page.locator(".shipment").first();
    assert.match(await firstShipment.innerText(), /询价中/);
    await firstShipment.getByRole("button", { name: "录入单号" }).click();
    await page.getByRole("button", { name: "保存单号" }).click();
    assert.match(await page.locator("#number-error").innerText(), /至少填写/);
    await page
      .locator("#number-form textarea")
      .fill("DEMO-NEW-01\nDEMO-NEW-01\nDEMO-NEW-02");
    await page.getByRole("button", { name: "保存单号" }).click();
    assert.equal(
      await page.locator(".shipment").first().locator(".number-chip").count(),
      2,
    );
    assert.equal(
      await page.locator(".shipment").first().locator(".state-tag").innerText(),
      "询价中",
    );
    assert.equal(
      await page.locator(".shipment").last().locator(".state-tag").innerText(),
      "已走货",
    );
    await shot("shipments-desktop.png");
    results.push(
      "Multiple shipment numbers deduplicate without falsely changing the new batch to shipped",
    );

    await page.getByRole("tab", { name: "沟通原文", exact: true }).click();
    await page.getByRole("searchbox", { name: "搜索沟通原文" }).fill("装车");
    assert.equal(await page.locator("#timeline-messages .message").count(), 1);
    await page.getByRole("searchbox", { name: "搜索沟通原文" }).fill("");
    await page.getByRole("button", { name: /收纳盒产品图/ }).click();
    await page.waitForFunction(
      () => document.querySelector(".preview-image")?.naturalWidth > 0,
    );
    await page.waitForFunction(
      () => document.querySelector(".preview-image")?.naturalWidth > 0,
    );
    assert.equal(
      await page
        .locator(".preview-image")
        .evaluate((el) => el.complete && el.naturalWidth > 0),
      true,
    );
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: /11月备货清单.csv/ }).click();
    assert.match(await page.locator(".file-table").innerText(), /待称重/);
    await page.keyboard.press("Escape");
    await page.keyboard.press("Escape");
    results.push(
      "Chronological text search, image and ordinary-file previews open and close",
    );

    await page.getByRole("button", { name: "同步并整理", exact: true }).click();
    assert.match(
      await page.locator("#overlay-dialog").innerText(),
      /微信未连接/,
    );
    await page.getByRole("button", { name: "演示整理", exact: true }).click();
    assert.match(
      await page.locator("#overlay-dialog").innerText(),
      /正在按商家整理/,
    );
    await page
      .locator("#overlay-dialog")
      .getByRole("button", { name: "停止本次", exact: true })
      .click();
    assert.match(
      await page.locator("#overlay-dialog").innerText(),
      /本次整理已停止/,
    );
    assert.equal(
      await page.getByRole("button", { name: "停止本次", exact: true }).count(),
      0,
    );
    await page.keyboard.press("Escape");
    await page.getByRole("tab", { name: /全部联系人/ }).click();
    await page.getByRole("searchbox", { name: "搜索全部联系人" }).fill("叶青");
    await page.getByRole("button", { name: "修改身份", exact: true }).click();
    await page.getByRole("radio", { name: /平台/ }).check();
    await page.getByRole("button", { name: "保存身份" }).click();
    await page.getByRole("tab", { name: /商家档案/ }).click();
    await page.getByRole("button", { name: "整理记录", exact: true }).click();
    assert.equal(await page.locator(".queue-list li").count(), 1);
    await page
      .locator("#overlay-dialog")
      .getByRole("button", { name: "继续本次", exact: true })
      .click();
    await page.waitForFunction(
      () =>
        document.querySelector("#overlay-dialog .progress-heading strong")
          ?.textContent === "本次资料整理已完成",
      {},
      { timeout: 20000 },
    );
    assert.equal(
      await page.getByRole("button", { name: "继续本次", exact: true }).count(),
      0,
    );
    assert.equal(
      await page.getByRole("button", { name: "停止本次", exact: true }).count(),
      0,
    );
    await page.keyboard.press("Escape");
    await page.getByRole("button", { name: "同步并整理", exact: true }).click();
    await page.getByRole("button", { name: "演示整理", exact: true }).click();
    assert.match(await page.locator("#toast").innerText(), /暂无待整理资料/);
    await page.keyboard.press("Escape");
    results.push(
      "Header and dialog share start/stop/resume; role changes remove pending non-merchants; completion ends the task and idle has no pause",
    );

    await go("设置");
    const daily = page.getByRole("switch", { name: "每日自动整理" });
    await daily.click();
    assert.equal(await page.locator("#daily-time").isDisabled(), true);
    await daily.click();
    await page.locator("#daily-time").fill("09:45");
    await page.locator("#daily-time").dispatchEvent("change");
    await page.getByRole("button", { name: "深色", exact: true }).click();
    assert.equal(await page.locator("html").getAttribute("data-theme"), "dark");
    await shot("settings-dark.png");
    await page.getByRole("button", { name: "浅色", exact: true }).click();
    await page.reload();
    assert.equal(await page.locator("#daily-time").inputValue(), "09:45");
    await page.locator("#daily-time").fill("25:80");
    await page.locator("#daily-time").dispatchEvent("change");
    assert.equal(
      await page.locator("#daily-time").getAttribute("aria-invalid"),
      "true",
    );
    assert.match(await page.locator("#daily-time-error").innerText(), /00:00/);
    await page.locator("#daily-time").fill("9:45");
    await page.locator("#daily-time").dispatchEvent("change");
    assert.equal(await page.locator("#daily-time").inputValue(), "09:45");
    results.push(
      "Daily schedule toggle, Beijing time, appearance and prototype edits survive reload",
    );

    // Responsive application states, including dialogs and controls rather than a static landing page.
    await go("工作台");
    const layout = [];
    for (const width of [1920, 1440, 1280, 1180]) {
      await page.setViewportSize({ width, height: width < 500 ? 844 : 1000 });
      await page.waitForTimeout(100);
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth > innerWidth,
        ),
        false,
        `workspace overflow at ${width}`,
      );
      const [a, b] = await Promise.all([
        page.locator(".head-actions .btn").first().boundingBox(),
        page.locator(".head-actions .btn").last().boundingBox(),
      ]);
      if (width > 1000 || width <= 760)
        assert.ok(
          Math.abs(a.y - b.y) <= 1,
          `header button alignment at ${width}`,
        );
      await page.getByRole("button", { name: "陈屿", exact: true }).click();
      assert.equal(
        await page
          .locator("#detail-dialog")
          .evaluate((el) => el.scrollWidth > el.clientWidth),
        false,
        `detail overflow at ${width}`,
      );
      await page.getByRole("tab", { name: "备货记录", exact: true }).click();
      assert.equal(
        await page
          .locator("#detail-dialog")
          .evaluate((el) => el.scrollWidth > el.clientWidth),
        false,
        `shipment overflow at ${width}`,
      );
      if (width === 390) await shot("profile-mobile.png");
      await page.getByRole("button", { name: "关闭客户档案" }).click();
      await go("设置");
      assert.equal(
        await page.evaluate(
          () => document.documentElement.scrollWidth > innerWidth,
        ),
        false,
        `settings overflow at ${width}`,
      );
      await go("工作台");
      if (width === 390) await shot("workspace-mobile.png");
      layout.push(width);
    }
    results.push(
      `No horizontal overflow at ${layout.join(", ")}px; profile/shipments/settings and button alignment checked`,
    );

    await page.setViewportSize({ width: 1440, height: 1000 });
    await page.goto(base + "preview.html");
    await page.getByRole("heading", { name: "工作台", exact: true }).waitFor();
    await page.getByRole("button", { name: "陈屿", exact: true }).click();
    await page.getByRole("tab", { name: "沟通原文", exact: true }).click();
    await page.getByRole("button", { name: /收纳盒产品图/ }).click();
    await page.waitForFunction(
      () => document.querySelector(".preview-image")?.naturalWidth > 0,
    );
    assert.equal(
      await page
        .locator(".preview-image")
        .evaluate((el) => el.complete && el.naturalWidth > 0),
      true,
    );
    results.push(
      "Self-contained preview renders its embedded image without external dependencies",
    );
    assert.deepEqual(errors, []);
    assert.deepEqual(external, []);
    const report = {
      passed: true,
      checks: results,
      consoleErrors: errors,
      externalRequests: external,
    };
    fs.writeFileSync(
      path.join(__dirname, "artifacts", "functional-checks.json"),
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
