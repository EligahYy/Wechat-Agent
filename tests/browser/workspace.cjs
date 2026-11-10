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
  await page.goto("http://127.0.0.1:8768/");
  await page.locator('[data-board-source="merchant"]').waitFor();
  if (
    !(await page
      .locator('[data-board-source="merchant"] [data-progress-action]')
      .isDisabled())
  )
    throw Error("authorization bypass");
  if ((await page.locator("aside nav button").count()) !== 2)
    throw Error("navigation not consolidated");
  const csrf = await page.locator('meta[name="csrf"]').getAttribute("content");
  await page.getByRole("button", { name: "设置", exact: true }).click();
  await page.locator("#whitelist-manager").waitFor();
  await page.request.post("http://127.0.0.1:8768/api/crm/configure", {
    headers: { "X-CSRF-Token": csrf },
    data: { enabled: true },
  });
  await page.getByRole("button", { name: "数据大屏", exact: true }).click();
  await page
    .getByRole("textbox", { name: "搜索联系人", exact: true })
    .fill("not-a-contact");
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  await page.getByText("没有匹配联系人", { exact: true }).waitFor();
  await page.getByRole("textbox", { name: "搜索联系人", exact: true }).fill("");
  await page.getByRole("button", { name: "搜索", exact: true }).click();
  await page
    .locator('[data-board-source="merchant"] [data-progress-action]')
    .click();
  await page
    .getByText("分析完成，档案与跟进已更新。", { exact: true })
    .waitFor();
  await page
    .locator(
      '#followup-rows [data-open-source="merchant"][data-open-tab="work"]',
    )
    .waitFor();
  await page
    .locator(
      '#followup-rows [data-open-source="merchant"][data-open-tab="work"]',
    )
    .click();
  await page.locator("dialog[open]").waitFor();
  await page
    .locator(".insight-card")
    .filter({ hasText: "英国第一批" })
    .waitFor();
  await page.getByRole("tab", { name: "完整时间线", exact: true }).click();
  await page
    .getByRole("button", { name: "查看全部聊天记录", exact: true })
    .click();
  await page.getByText("全部相关会话共 1 条 · 第 1 页 · 每页 50 条").waitFor();
  await page.getByRole("tab", { name: "资料概览", exact: true }).click();
  await page.locator("#packet-disclosure > summary").click();
  await page
    .locator("#packet-ledger")
    .getByText("原始资料整理", { exact: true })
    .waitFor();
  await page.getByText("查看来源", { exact: true }).first().click();
  await page
    .getByText("下周英国3方货，请确认报价。", { exact: true })
    .first()
    .waitFor();
  await page.getByRole("tab", { name: /批次与行动/ }).click();
  await page.getByRole("button", { name: "生成跟进草稿", exact: true }).click();
  await page
    .getByText("尚未发送，也不会自动标记已联系。确认发送后可到人工跟进中记录。")
    .waitFor();
  await page.getByRole("tab", { name: "人工跟进", exact: true }).click();
  await page
    .locator("#customer-followup-form [name=note]")
    .fill("已在微信联系，等待报价反馈（虚构）");
  await page
    .getByRole("combobox", { name: "关联待办（可选）", exact: true })
    .click();
  await page.getByRole("option", { name: "确认英国报价", exact: true }).click();
  await page.getByRole("combobox", { name: "待办状态", exact: true }).click();
  await page.getByRole("option", { name: "已处理", exact: true }).click();
  await page.getByRole("button", { name: "保存人工跟进", exact: true }).click();
  await page.getByText("人工跟进已保存。", { exact: true }).waitFor();
  await page
    .locator("#customer-journal")
    .getByText("已在微信联系，等待报价反馈（虚构）", { exact: true })
    .waitFor();
  await page.getByRole("button", { name: "关闭详情", exact: true }).click();
  await page.getByText("当前没有需要跟进的客户", { exact: true }).waitFor();
  await page.getByRole("button", { name: "数据大屏", exact: true }).click();
  await page.locator('[data-open-source="merchant"]').first().click();
  await page.getByRole("button", { name: "暂停联系建议" }).click();
  await page.getByText(/已暂停联系/).waitFor();
  await page.reload();
  await page.getByRole("button", { name: "数据大屏", exact: true }).click();
  await page.getByText(/已暂停联系/).waitFor();
  await page.screenshot({
    path: "/tmp/workspace-live-desktop.png",
    fullPage: true,
    animations: "disabled",
  });
  await page.getByRole("button", { name: "数据大屏", exact: true }).click();
  await page.getByRole("button", { name: "开启自动整理", exact: true }).click();
  await page
    .getByRole("button", { name: "暂停自动整理", exact: true })
    .waitFor();
  await page.getByRole("button", { name: "刷新", exact: true }).click();
  const advanced = await page.request.post(
    "http://127.0.0.1:8768/__test__/advance-queue",
    { headers: { "X-CSRF-Token": csrf }, data: {} },
  );
  if (!(await advanced.json()).worked)
    throw Error("automatic queue did not work");
  const docs = await (
    await page.request.get("http://127.0.0.1:8768/api/workspace/documents")
  ).json();
  if (
    docs.items[0].body.coverage.processed_messages !== 2 ||
    !docs.items[0].body.paused
  )
    throw Error("incremental update or manual pause lost");
  await page.getByRole("button", { name: "暂停自动整理", exact: true }).click();
  await page
    .getByRole("button", { name: "开启自动整理", exact: true })
    .waitFor();
  await page.request.post("http://127.0.0.1:8768/__test__/add-image", {
    headers: { "X-CSRF-Token": csrf },
    data: {},
  });
  await page.getByRole("button", { name: "数据大屏", exact: true }).click();
  await page.locator('[data-open-source="merchant"]').first().click();
  await page.getByRole("tab", { name: "完整时间线", exact: true }).click();
  await page
    .getByRole("button", { name: "查看全部聊天记录", exact: true })
    .click();
  await page
    .getByRole("button", { name: "查看图片与识别文字", exact: true })
    .click();
  await page.locator(".source-image").waitFor();
  await page.getByRole("button", { name: "重新读取原图", exact: true }).click();
  await page.locator(".source-image").waitFor();
  await page
    .getByRole("button", { name: "在本机识别文字", exact: true })
    .click();
  await page
    .locator("#image-text-form textarea")
    .fill("已人工核对：海运报价需确认有效期");
  await page
    .getByRole("button", { name: "确认文字并用于后续分析", exact: true })
    .click();
  await page
    .getByText("核对文本已保存，自动队列将重新整理相关客户；原图未修改。", {
      exact: true,
    })
    .waitFor();
  await page.screenshot({
    path: "/tmp/workspace-image-verification.png",
    fullPage: true,
  });
  await page.locator("dialog[open]").waitFor();
  await page.keyboard.press("Escape");
  await page.locator("dialog").waitFor({ state: "hidden" });
  await page.emulateMedia({ colorScheme: "dark", reducedMotion: "reduce" });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.locator('[data-open-source="merchant"]').first().click();
  await page.locator("dialog[open]").waitFor();
  await page.keyboard.press("Escape");
  await page.locator("dialog").waitFor({ state: "hidden" });
  if (
    await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
  )
    throw Error("overflow");
  if (errors.length) throw Error(errors.join("\n"));
  await page.getByRole("button", { name: "设置", exact: true }).click();
  await page.locator("#whitelist-manager").waitFor();
  await page.locator('[data-white-entity="groups"]').click();
  await page.locator("#white-add-toggle").click();
  await page.locator("#white-candidates [data-white-add]").first().click();
  await page.locator("#white-rows [data-white-restore]").waitFor();
  await page.locator("#white-rows [data-white-restore]").click();
  await page.getByText("当前白名单为空。", { exact: true }).waitFor();
  await page.getByText("工作台", { exact: true }).waitFor();
  await page.getByText("补充导入聊天记录", { exact: true }).click();
  const fileRow = {
    source: "manual",
    account_id: "work",
    conversation_id: "manual-peer",
    conversation_type: "private",
    source_id: "manual-m1",
    sender_id: "manual-peer",
    direction: "incoming",
    event_time: "2026-11-09T09:00:00+08:00",
    message_type: "text",
    text: "虚构文件导入记录",
  };
  await page.locator("#workspace-import-file").setInputFiles({
    name: "messages.json",
    mimeType: "application/json",
    buffer: Buffer.from(JSON.stringify([fileRow])),
  });
  await page.getByRole("button", { name: "确认导入记录", exact: true }).click();
  await page
    .getByText("已导入 1 条，重复 0 条；后续按当前自动整理开关运行。", {
      exact: true,
    })
    .waitFor();
  await page.evaluate(() => scrollTo(0, 0));
  await page.screenshot({
    path: "/tmp/workspace-settings-mobile.png",
    fullPage: true,
  });
  if (
    await page.evaluate(() => document.documentElement.scrollWidth > innerWidth)
  )
    throw Error("settings overflow");
  if (errors.length) throw Error(errors.join("\n"));
  await browser.close();
  console.log(
    "Workspace analysis, evidence, draft, manual follow-up, completion, pause, automatic queue, image verification, scope tabs, settings, file import and mobile passed.",
  );
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
