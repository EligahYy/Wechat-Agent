const { chromium } = require("playwright");
const fs = require("fs");
const path = require("path");
const base = process.env.WA_BROWSER_URL || "http://127.0.0.1:8767";
const directory = process.env.WA_BROWSER_DATA_DIR;
const screenshots =
  process.env.WA_BROWSER_SCREENSHOTS || "/tmp/wechat-agent-browser";
if (!directory || !["127.0.0.1", "localhost"].includes(new URL(base).hostname))
  throw Error("Use an isolated local test service");
fs.mkdirSync(screenshots, { recursive: true });
(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.CHROMIUM_PATH || "/usr/bin/chromium",
    headless: true,
    args: ["--no-sandbox", "--disable-dev-shm-usage"],
  });
  try {
    const page = await browser.newPage({
        viewport: { width: 1440, height: 1050 },
      }),
      errors = [];
    page.on("pageerror", (e) => errors.push(e.message));
    await page.goto(base);
    await page
      .locator("#token")
      .fill(
        fs.readFileSync(path.join(directory, "session-token"), "utf8").trim(),
      );
    await page.getByRole("button", { name: "进入工作台" }).click();
    await page.getByRole("heading", { name: "今天，联系谁？" }).waitFor();
    await page.locator(".action-card").waitFor();
    const badge = await page.locator('.action-card .tag').first().boundingBox();
    if (badge.height > 30 || badge.width > 200) throw Error('badge stretched');
    await page.screenshot({
      animations: "disabled",
      path: path.join(screenshots, "crm-today.png"),
      fullPage: true,
    });
    await page
      .getByRole("button", { name: "查看依据", exact: true })
      .first()
      .click();
    await page.locator("#detail[open] .message").waitFor();
    if (!(await page.locator("#detail-body").innerText()).includes("3方"))
      throw Error("evidence missing");
    await page.locator("#close-detail").click();
    await page.locator("nav [data-page=customers]").click();
    await page.locator(".customer-card").click();
    await page.locator("#message-items").waitFor();
    if ((await page.locator("#message-items").innerText()).includes("收到"))
      throw Error("noise not collapsed");
    await page.locator("#message-filter").click();
    if (!(await page.locator("#message-items").innerText()).includes("收到"))
      throw Error("original message not retained");
    await page.locator("#detail [data-image]").click();
    await page.locator("#detail img").waitFor();
    if (
      !(await page
        .locator("#detail img")
        .evaluate((i) => i.complete && i.naturalWidth > 0))
    )
      throw Error("image invalid");
    await page.screenshot({
      animations: "disabled",
      path: path.join(screenshots, "crm-customer.png"),
      fullPage: true,
    });
    await page.locator("#close-detail").click();
    await page.locator("nav [data-page=today]").click();
    await page
      .getByRole("button", { name: "改期", exact: true })
      .first()
      .click();
    await page.locator("#result-form input[type=date]").fill("2030-01-01");
    await page.locator("#result-form .primary").click();
    await page.getByRole("heading", { name: "今天暂无到期行动" }).waitFor();
    await page.locator("nav [data-page=reviews]").click();
    await page
      .getByRole("heading", { name: "暂时没有需要你确认的事" })
      .waitFor();
    await page.locator("nav [data-page=settings]").click();
    if ((await page.locator("input[type=file]").count()) !== 1)
      throw Error("more than one manual entry");
    await page.locator("#probe").click();
    await page.locator("#bind-account").waitFor();
    if (
      !(await page.locator("#source-result").innerText()).includes("工作小号")
    )
      throw Error("source nickname missing");
    if (
      !(await page.locator(".brand").innerText()).includes(
        "半托管欧区备货用户助手",
      )
    )
      throw Error("project display name missing");
    await page.locator("nav [data-page=analysis]").click();
    await page.locator("#analysis-metrics .analysis-metric").nth(3).waitFor();
    await page.locator("#analysis-jobs .queue-item").waitFor();
    if (
      !(await page.locator("#analysis-scopes").innerText()).includes("近 15 天")
    )
      throw Error("recent analysis scope missing");
    await page.locator("#analysis-scope").selectOption("recent");
    await page.locator("#analysis-filter").selectOption("complete");
    await page.locator("#analysis-jobs .queue-item").waitFor();
    await page.locator("#analysis-trend .usage-day").nth(6).waitFor();
    if ((await page.locator("#analysis-trend .usage-day").count()) !== 7)
      throw Error("usage chart must show seven days");
    if (
      !(
        await page.locator("#analysis-trend .usage-legend").innerText()
      ).includes("非实际扣费")
    )
      throw Error("uncertain usage legend missing");
    await page.locator("#analysis-trend .usage-day").nth(0).click();
    if (
      !(await page
        .locator("#analysis-trend .usage-day")
        .nth(0)
        .evaluate(
          (el) =>
            el.getAttribute("aria-pressed") === "true" &&
            el === document.activeElement,
        ))
    )
      throw Error("day selection/focus not retained");
    if (
      !(
        await page.locator("#analysis-trend .usage-detail").innerText()
      ).includes("2,300 Token")
    )
      throw Error("day detail values incorrect");
    await page.locator("#analysis-trend .usage-day").nth(6).click();
    if (
      !(
        await page.locator("#analysis-trend .usage-detail").innerText()
      ).includes("98,680 Token")
    )
      throw Error("pending reservation not distinguished");
    await page.evaluate(() => window.scrollTo(0, 0));
    await page.screenshot({
      animations: "disabled",
      path: path.join(screenshots, "analysis-overview.png"),
      fullPage: true,
    });

    await page.locator("nav [data-page=scope]").click();
    await page.locator("#source-list .source-option").waitFor();
    await page.locator("#source-select-page").click();
    await page.locator("#source-add").click();
    await page.waitForFunction(() => document.querySelector("#source-counts").textContent.includes("白名单免跟进 1 个"));
    await page.locator('#scope-exempt').click();
    await page.locator('#source-list .source-option').waitFor();
    if(await page.locator('#source-add').isVisible()) throw Error('exempt tab exposes add action');
    if(!(await page.locator('#source-selection').innerText()).includes('0')) throw Error('selection leaked across tabs');
    await page.locator("#source-select-page").click();
    await page.locator("#source-remove").click();
    await page.waitForFunction(() => document.querySelector("#source-counts").textContent.includes("白名单免跟进 0 个"));
    await page.locator('#scope-normal').click();
    await page.locator('#source-list .source-option').waitFor();
    if(await page.locator('#source-remove').isVisible()) throw Error('normal tab exposes removal action');
    await page.locator('[data-scope-entity=people]').click();
    await page.locator('#people-list .location-row').waitFor();
    if(!(await page.locator('#people-page').innerText()).includes('50')) throw Error('people pagination missing');
    await page.locator('[data-scope-entity=conversations]').click();
    await page.locator("nav [data-page=settings]").click();
    await page.locator("#refresh-monitor").click();
    await page.locator("#monitor-checks .monitor-item").nth(3).waitFor();
    await page.locator("nav [data-page=scope]").click();
    await page.locator('#source-search .select-trigger').first().click();
    await page.getByRole('option', {name: '群聊', exact: true}).click();
    await page.locator('#source-search [name=kind]').selectOption('all');
    const picker = page.locator('#source-search .select-trigger').first();
    await picker.focus();
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('ArrowDown');
    await page.keyboard.press('Enter');
    if (await page.locator('#source-search [name=kind]').inputValue() !== 'private') throw Error('keyboard selection failed');
    await picker.click();
    await page.keyboard.press('Escape');
    if (await picker.getAttribute('aria-expanded') !== 'false') throw Error('picker escape failed');
    await page.locator('#source-search [name=kind]').selectOption('all');

    await page.locator("nav [data-page=reviews]").click();
    await page.locator("#clear-reviews").click();
    await page.locator("#review-list .review-card").waitFor({state: "detached"});
    await page.locator("nav [data-page=settings]").click();
    await page.screenshot({
      animations: "disabled",
      path: path.join(screenshots, "crm-settings.png"),
      fullPage: true,
    });
    await page.setViewportSize({ width: 390, height: 844 });
    await page.locator("nav [data-page=today]").click();
    await page.screenshot({
      animations: "disabled",
      path: path.join(screenshots, "crm-mobile.png"),
      fullPage: true,
    });
    if (
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth + 1,
      )
    )
      throw Error("mobile overflow");
    await page.locator("nav [data-page=analysis]").click();
    await page.locator("#analysis-metrics .analysis-metric").nth(3).waitFor();
    await page.screenshot({
      animations: "disabled",
      path: path.join(screenshots, "analysis-mobile.png"),
      fullPage: true,
    });
    if (
      await page.evaluate(
        () => document.documentElement.scrollWidth > innerWidth + 1,
      )
    )
      throw Error("analysis mobile overflow");
    await page.locator("nav [data-page=scope]").click();
    await page.locator("#source-list .source-option").waitFor();
    if (await page.evaluate(() => document.documentElement.scrollWidth > innerWidth + 1))
      throw Error("whitelist settings mobile overflow");
    await page.locator("nav [data-page=analysis]").click();
    await page.emulateMedia({ reducedMotion: "reduce" });
    if (
      await page
        .locator("#page-analysis")
        .evaluate((el) => getComputedStyle(el).animationName !== "none")
    )
      throw Error("reduced motion ignored");
    if (errors.length) throw Error(errors.join("\n"));
    console.log(
      "Browser passed: login, auto-created action, evidence, profile, value filter, image, reschedule, reviews, single import entry, source probe, follow-up whitelist, mobile",
    );
  } finally {
    await browser.close();
  }
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
