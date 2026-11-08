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
  await page.locator("#contact").selectOption("merchant");
  await page.getByRole("button", { name: "分析此联系人", exact: true }).click();
  await page
    .getByText("分析完成。可在客户或待确认中查看；无业务依据时不会创建客户。")
    .waitFor();
  await page.getByRole("button", { name: "今日", exact: true }).click();
  await page.getByRole("button", { name: "查看档案" }).click();
  await page.getByText("英国第一批 · 需求确认").waitFor();
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
  await browser.close();
  console.log(
    "Workspace authentication, real persistence, mocked model, evidence, completion, pause and mobile passed.",
  );
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
