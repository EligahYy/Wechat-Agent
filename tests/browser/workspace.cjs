const { chromium } = require("playwright");
const fs = require("fs");
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
  await page.goto("http://127.0.0.1:8768/");
  const token = fs
    .readFileSync(process.env.WA_BROWSER_DATA_DIR + "/session-token", "utf8")
    .trim();
  await page.request.post("http://127.0.0.1:8768/login", { data: { token } });
  await page.goto("http://127.0.0.1:8768/workspace");
  await page.getByRole("button", { name: "试点与进度", exact: true }).click();
  await page.locator('[data-candidate="merchant"]').click();
  await page.getByText(/尚未开启文本分析授权/).waitFor();
  if (!(await page.locator("#analyze").isDisabled()))
    throw Error("authorization bypass");
  const csrf = await page.locator('meta[name="csrf"]').getAttribute("content");
  await page
    .getByRole("link", { name: "模型与分析授权设置 →", exact: true })
    .click();
  await page.locator("#page-settings").waitFor({ state: "visible" });
  const authorized = await page.request.post(
    "http://127.0.0.1:8768/api/crm/configure",
    {
      headers: { "X-CSRF-Token": csrf },
      data: { enabled: true },
    },
  );
  if (!authorized.ok()) throw Error("fixture authorization failed");
  await page.goto("http://127.0.0.1:8768/workspace");
  await page.getByRole("button", { name: "试点与进度", exact: true }).click();
  await page.getByRole("textbox", { name: "搜索联系人" }).fill("not-a-contact");
  await page.getByRole("textbox", { name: "搜索联系人" }).press("Enter");
  await page.getByText("没有匹配的联系人", { exact: true }).waitFor();
  await page.getByRole("button", { name: "清空搜索", exact: true }).click();
  await page.getByRole("button", { name: "刷新联系人", exact: true }).click();
  await page.locator('[data-candidate="merchant"]').click();

  await page.getByRole("button", { name: "分析此联系人", exact: true }).click();
  await page
    .getByText("分析完成。可在客户或待确认中查看；无业务依据时不会创建客户。")
    .waitFor();
  await page
    .getByText("分册 1 / 1 · 已整理 1 / 1 条 · 价值过滤 0 条")
    .waitFor();
  await page.screenshot({
    path: "/tmp/workspace-corpus-progress.png",
    fullPage: true,
  });
  await page.getByRole("button", { name: "今日", exact: true }).click();
  await page.getByRole("button", { name: "查看档案" }).click();
  await page
    .locator(".insight-card")
    .filter({ hasText: "英国第一批" })
    .waitFor();
  await page
    .getByRole("button", { name: "查看全部聊天记录", exact: true })
    .click();
  await page.getByText("全部相关会话共 1 条 · 第 1 页 · 每页 50 条").waitFor();
  await page
    .getByRole("button", { name: "查看已保存资料分册", exact: true })
    .click();
  await page
    .locator("#packet-ledger")
    .getByText("原始资料整理", { exact: true })
    .waitFor();
  await page.getByText("查看来源", { exact: true }).first().click();
  await page
    .getByText("下周英国3方货，请确认报价。", { exact: true })
    .first()
    .waitFor();
  await page.getByRole("button", { name: "标记已处理" }).click();
  await page.getByText("当前没有可展示的结果").waitFor();
  await page.getByRole("button", { name: "客户", exact: true }).click();
  await page.getByRole("button", { name: "查看档案" }).click();
  await page.getByRole("button", { name: "暂停联系建议" }).click();
  await page.getByText(/已暂停联系/).waitFor();
  await page.reload();
  await page.getByRole("button", { name: "客户", exact: true }).click();
  await page.getByText(/已暂停联系/).waitFor();
  await page.screenshot({
    path: "/tmp/workspace-live-desktop.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.getByRole("button", { name: "查看档案" }).click();
  await page.keyboard.press("Escape");
  if (
    await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
  )
    throw Error("overflow");
  if (errors.length) throw Error(errors.join("\n"));
  await page.route("**/api/workspace/candidates?*", (route) =>
    route.fulfill({
      json: {
        items: [],
        total: 0,
        page: 1,
        has_more: false,
        diagnostics: {
          archived_messages: 12,
          scope_conversations: 0,
          contacts: 0,
          analysis_enabled: true,
          key_configured: true,
          empty_reason: "scope_excluded",
        },
      },
    }),
  );
  await page.getByRole("button", { name: "试点与进度", exact: true }).click();
  await page.getByText("暂无正常跟进会话", { exact: true }).waitFor();
  if (await page.locator("#contact").count())
    throw Error("empty select still shown");
  await page
    .getByRole("link", { name: "检查会话范围与人物白名单 →", exact: true })
    .click();
  await page.locator("#page-scope").waitFor({ state: "visible" });
  await browser.close();
  console.log(
    "Workspace authentication, real persistence, mocked model, evidence, completion, pause, candidate authorization, search, empty state, settings links and mobile passed.",
  );
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
