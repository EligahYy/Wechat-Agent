import { test, expect } from "@playwright/test";
test.beforeEach(async ({ request, page }) => {
  await request.post("/api/__test__/reset");
  await page.goto("/");
});
test("20/8 pagination, cross-page selection, tab reset and preserved rows", async ({
  page,
}) => {
  await page.getByRole("tab", { name: /全部联系人/ }).click();
  const rows = page.locator("tbody tr[data-contact]");
  await expect(rows).toHaveCount(20);
  const first = rows.first();
  const marker = await first.getAttribute("data-contact");
  await first.evaluate((node) => node.setAttribute("data-same-node", "yes"));
  await first.getByRole("checkbox").check();
  await expect(
    page.getByText("已选 1 位联系人", { exact: true }),
  ).toBeVisible();
  await expect(page.locator(`[data-contact="${marker}"]`)).toHaveAttribute(
    "data-same-node",
    "yes",
  );
  await page.getByRole("button", { name: "下一页" }).click();
  await expect(rows).toHaveCount(8);
  await rows.first().getByRole("checkbox").check();
  await expect(
    page.getByText("已选 2 位联系人", { exact: true }),
  ).toBeVisible();
  await page.getByRole("tab", { name: /商家档案/ }).click();
  await expect(page.getByText(/已选 \d 位联系人/)).not.toBeVisible();
  await expect(rows).toHaveCount(6);
});
test("identity changes use real API, retain role filter and copy actual name", async ({
  page,
  context,
}) => {
  await context.grantPermissions(["clipboard-read", "clipboard-write"]);
  await page.getByRole("tab", { name: /全部联系人/ }).click();
  await page.getByRole("searchbox").fill("商家甲");
  const row = page.locator("tbody tr[data-contact]").first();
  await expect(row.getByText("商家甲", { exact: true })).toBeVisible();
  await row.getByRole("button", { name: "复制微信名称" }).click();
  expect(await page.evaluate(() => navigator.clipboard.readText())).toBe(
    "商家甲",
  );
  await row.getByRole("button", { name: "修改身份" }).click();
  const dialog = page.getByRole("dialog", { name: "设置身份" });
  await dialog.getByRole("radio", { name: "平台" }).click();
  await dialog.getByRole("button", { name: "保存身份" }).click();
  await expect(row.getByText("平台", { exact: true })).toBeVisible();
  await expect(dialog).not.toBeVisible();
  await page.reload();
  await page.getByRole("tab", { name: /全部联系人/ }).click();
  await page.getByRole("searchbox").fill("商家甲");
  await expect(row.getByText("平台", { exact: true })).toBeVisible();
});
test("settings time panel cancels drafts, persists input and themes the entire canvas", async ({
  page,
}) => {
  await page.getByRole("button", { name: "设置", exact: true }).click();
  await page.getByRole("switch", { name: "每日自动整理" }).click();
  const field = page.getByLabel("每天开始时间");
  await expect(field).toBeEnabled();
  await page.getByRole("button", { name: "选择开始时间" }).click();
  const panel = page.getByRole("dialog", { name: "选择开始时间" });
  await expect(panel.getByText("北京时间")).toBeVisible();
  await panel.getByRole("option", { name: "09 时" }).click();
  await panel.getByRole("button", { name: "取消" }).click();
  await expect(field).toHaveValue("08:30");
  await field.fill("9:05");
  await field.press("Tab");
  await expect(field).toHaveValue("09:05");
  await page.getByRole("tab", { name: "深色", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await expect
    .poll(() =>
      page
        .locator("body")
        .evaluate((node) => getComputedStyle(node).backgroundColor),
    )
    .toBe("rgb(22, 22, 24)");
  await page.reload();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.getByRole("button", { name: "设置", exact: true }).click();
  await expect(field).toHaveValue("09:05");
});
test("out-of-order searches keep only latest result without blanking the table", async ({
  page,
}) => {
  await page.getByRole("tab", { name: /全部联系人/ }).click();
  await expect(page.locator("tbody tr[data-contact]")).toHaveCount(20);
  await page.route("**/api/contacts?**", async (route) => {
    if (new URL(route.request().url()).searchParams.get("q") === "商")
      await new Promise((resolve) => setTimeout(resolve, 300));
    await route.continue();
  });
  const search = page.getByRole("searchbox");
  await search.fill("商");
  await page.waitForTimeout(200);
  await search.fill("商家甲");
  await expect(page.locator("tbody tr[data-contact]")).toHaveCount(1);
  await page.waitForTimeout(400);
  await expect(page.locator("tbody tr[data-contact]")).toHaveCount(1);
  await expect(page.getByRole("table")).toBeVisible();
  await expect(page.getByRole("button", { name: "查看 商家甲" })).toBeVisible();
});

test("partial version conflict keeps only failed contacts selected", async ({
  page,
  request,
}) => {
  await page.getByRole("tab", { name: /全部联系人/ }).click();
  const rows = page.locator("tbody tr[data-contact]");
  await expect(rows).toHaveCount(20);
  const people = (
    await (
      await request.get("/api/contacts?account_id=acct-1&page_size=20")
    ).json()
  ).items;
  await rows.nth(0).getByRole("checkbox").check();
  await rows.nth(1).getByRole("checkbox").check();
  await request.patch("/api/contacts/roles", {
    data: {
      account_id: "acct-1",
      role: people[0].role === "platform" ? "provider" : "platform",
      items: [{ key: people[0].key, expected_version: people[0].role_version }],
    },
  });
  await page.getByRole("button", { name: "设置身份", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "设置身份" });
  await dialog.getByRole("radio", { name: "服务商" }).click();
  await dialog.getByRole("button", { name: "保存身份" }).click();
  await expect(dialog.getByRole("alert")).toContainText(
    "已保存 1 位，1 位信息已变化",
  );
  await expect(
    page.getByText("已选 1 位联系人", { exact: true }),
  ).toBeVisible();
  const archived = (
    await (
      await request.get("/api/contacts?account_id=acct-1&page_size=20")
    ).json()
  ).items;
  expect(
    archived.find(
      (person: any) => person.key.contact_id === people[1].key.contact_id,
    ).role,
  ).toBe("provider");
});
test("selection bar reverses smoothly and filtering preserves matching rows", async ({
  page,
}) => {
  await page.getByRole("tab", { name: /全部联系人/ }).click();
  const rows = page.locator("tbody tr[data-contact]");
  await expect(rows).toHaveCount(20);
  const first = rows.first().getByRole("checkbox");
  await first.check();
  const bar = page.locator(".batch-collapse");
  await expect
    .poll(() => bar.evaluate((node) => node.getBoundingClientRect().height))
    .toBeGreaterThan(50);
  await page.waitForTimeout(260);
  const full = await bar.evaluate(
    (node) => node.getBoundingClientRect().height,
  );
  await first.uncheck();
  await page.waitForTimeout(80);
  const middle = await bar.evaluate(
    (node) => node.getBoundingClientRect().height,
  );
  expect(middle).toBeGreaterThan(0);
  expect(middle).toBeLessThan(full);
  await first.check();
  await expect(
    page.getByText("已选 1 位联系人", { exact: true }),
  ).toBeVisible();
  await page.getByRole("button", { name: "清空", exact: true }).click();
  await expect(
    page.getByRole("checkbox", { name: "选择本页联系人" }),
  ).toBeFocused();
  const merchant = rows.filter({ has: page.locator(".role-merchant") }).first();
  const id = await merchant.getAttribute("data-contact");
  await merchant.evaluate((node) => node.setAttribute("data-preserved", "yes"));
  await page
    .getByRole("tablist", { name: "联系人身份筛选" })
    .getByRole("tab", { name: /商家/ })
    .click();
  await expect(rows).toHaveCount(6);
  await expect(page.locator(`[data-contact="${id}"]`)).toHaveAttribute(
    "data-preserved",
    "yes",
  );
});
test("actual operation separates source success and unavailable analysis", async ({
  page,
}) => {
  await page.getByRole("button", { name: "同步并整理", exact: true }).click();
  await expect(
    page.getByText("原文已同步，档案整理尚未接入", { exact: true }).first(),
  ).toBeVisible();
  await page.getByRole("button", { name: "整理记录", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "整理记录" });
  await dialog.getByRole("button", { name: /原文已同步/ }).click();
  await expect(dialog.getByText(/来源阶段：已完成/)).toBeVisible();
  await expect(dialog.getByText(/分析能力尚未接入/)).toBeVisible();
});
test("source list errors retain archive rows and offer retry", async ({
  page,
}) => {
  await page.getByRole("tab", { name: /全部联系人/ }).click();
  await expect(page.locator("tbody tr[data-contact]")).toHaveCount(20);
  await page.route("**/api/contacts?**", (route) =>
    route.fulfill({
      status: 503,
      contentType: "application/json",
      body: JSON.stringify({ code: "database_unavailable", details: {} }),
    }),
  );
  await page.getByRole("searchbox").fill("临时查询");
  await expect(page.getByRole("alert")).toContainText("本地数据库不可用");
  await expect(page.locator("tbody tr[data-contact]")).toHaveCount(20);
  await expect(
    page.getByRole("button", { name: "重试", exact: true }),
  ).toBeEnabled();
});
test("desktop widths, shared styles, time keyboard and reduced motion", async ({
  page,
}) => {
  for (const width of [1180, 1280, 1440, 1920]) {
    await page.setViewportSize({ width, height: 900 });
    await expect(
      page.getByRole("heading", { name: "工作台", exact: true }),
    ).toBeVisible();
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBeTruthy();
  }
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.getByRole("tab", { name: /全部联系人/ }).click();
  await expect(page.locator("tbody tr[data-contact]")).toHaveCount(20);
  await page.screenshot({
    path: "../.local/artifacts/m1/workspace-light.png",
    fullPage: true,
  });
  expect(
    await page.getByRole("searchbox").evaluate((node) => {
      const s = getComputedStyle(node);
      return { radius: s.borderRadius, font: s.fontSize, height: s.height };
    }),
  ).toEqual({ radius: "12px", font: "14px", height: "48px" });
  await page.getByRole("button", { name: "设置", exact: true }).click();
  await page.getByRole("switch", { name: "每日自动整理" }).click();
  await expect(page.getByLabel("每天开始时间")).toBeEnabled();
  await page.getByRole("button", { name: "选择开始时间" }).click();
  const panel = page.getByRole("dialog", { name: "选择开始时间" });
  await panel.getByRole("option", { name: "08 时" }).press("ArrowDown");
  await panel.getByRole("option", { name: "09 时" }).press("Escape");
  await expect(page.getByLabel("每天开始时间")).toHaveValue("08:30");
  await expect(
    page.getByRole("button", { name: "选择开始时间" }),
  ).toBeFocused();
  await page.getByRole("tab", { name: "深色", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.waitForTimeout(350);
  await page.screenshot({
    path: "../.local/artifacts/m1/settings-dark.png",
    fullPage: true,
  });
  await page.emulateMedia({ reducedMotion: "reduce" });
  expect(
    await page
      .getByRole("button", { name: "工作台", exact: true })
      .evaluate((node) => getComputedStyle(node).transitionDuration),
  ).toBe("1e-06s");
});

test("navigation preserves the workspace search and active tab", async ({
  page,
}) => {
  await page.getByRole("tab", { name: /全部联系人/ }).click();
  await page.getByRole("searchbox").fill("商家甲");
  await expect(page.locator("tbody tr[data-contact]")).toHaveCount(1);
  await page.getByRole("button", { name: "设置", exact: true }).click();
  await page.getByRole("button", { name: "工作台", exact: true }).click();
  await expect(page.getByRole("tab", { name: /全部联系人/ })).toHaveAttribute(
    "aria-selected",
    "true",
  );
  await expect(page.getByRole("searchbox")).toHaveValue("商家甲");
});
test("role choices support arrow keys and focus follows selection", async ({
  page,
}) => {
  await page.getByRole("tab", { name: /全部联系人/ }).click();
  await page.getByRole("searchbox").fill("商家甲");
  await expect(page.locator("tbody tr[data-contact]")).toHaveCount(1);
  await page.getByRole("button", { name: "修改身份", exact: true }).click();
  const dialog = page.getByRole("dialog", { name: "设置身份" });
  await dialog
    .getByRole("radio", { name: "商家", exact: true })
    .press("ArrowRight");
  await expect(dialog.getByRole("radio", { name: "服务商" })).toHaveAttribute(
    "aria-checked",
    "true",
  );
  await expect(dialog.getByRole("radio", { name: "服务商" })).toBeFocused();
});

test("dark appearance is applied before delayed bootstrap after reload", async ({
  page,
}) => {
  await page.getByRole("button", { name: "设置", exact: true }).click();
  await page.getByRole("tab", { name: "深色", exact: true }).click();
  await expect(page.locator("html")).toHaveAttribute("data-theme", "dark");
  await page.route("**/api/settings", async (route) => {
    await new Promise((resolve) => setTimeout(resolve, 650));
    await route.continue();
  });
  await page.reload({ waitUntil: "domcontentloaded" });
  expect(await page.locator("html").getAttribute("data-theme")).toBe("dark");
});

test("customer sync belongs to header and incomplete history discloses reasons", async ({
  page,
  request,
}, testInfo) => {
  await page.getByRole("tab", { name: /全部联系人/ }).click();
  await page.getByRole("searchbox").fill("商家甲");
  await expect(page.locator("tbody tr[data-contact]")).toHaveCount(1);
  await page.getByRole("button", { name: "查看 商家甲", exact: true }).click();
  const customer = page
    .getByRole("dialog")
    .filter({ has: page.getByRole("heading", { name: /商家甲/ }) });
  await expect(
    customer
      .locator(".dialog-header")
      .getByRole("button", { name: "同步此客户", exact: true }),
  ).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("customer-header.png") });
  await customer.getByRole("button", { name: "关闭弹窗" }).click();
  const submitted = await (
    await request.post("/api/operations", {
      data: {
        action: "sync",
        scope: { account_id: "acct-1" },
        idempotency_key: "diagnostic",
      },
    })
  ).json();
  const detail = await (
    await request.get(`/api/operations/${submitted.id}?account_id=acct-1`)
  ).json();
  const record = {
    ...detail,
    state: "failed",
    source_state: "failed",
    error_code: "source_incomplete",
    counts: {
      ...detail.counts,
      conversations_total: 3,
      completed_conversations: 2,
      failed_conversations: 1,
    },
    items: [
      {
        phase: "source",
        state: "failed",
        error_code: "source_incomplete",
        gaps: ["message_sender_invalid"],
      },
    ],
  };
  const { items, ...summary } = record;
  await page.route("**/api/operations?**", (route) =>
    route.fulfill({
      json: { items: [summary], total: 1, page: 1, page_size: 20 },
    }),
  );
  await page.route(`**/api/operations/${submitted.id}?**`, (route) =>
    route.fulfill({ json: record }),
  );
  await page.reload();
  await page.getByRole("button", { name: "整理记录", exact: true }).click();
  const history = page.getByRole("dialog", { name: "整理记录" });
  await history.getByRole("button", { name: /来源同步不完整/ }).click();
  await expect(history.getByText("目标会话 3")).toBeVisible();
  await expect(history.getByText("已完成 2")).toBeVisible();
  await expect(history.getByText("未完成 1")).toBeVisible();
  await expect(history.getByText(/发送人标识异常/)).toBeVisible();
  await page.screenshot({ path: testInfo.outputPath("source-gaps.png") });
});
test("top metadata refresh is a durable operation and does not synchronize messages", async ({ page, request }) => {
  const sent: string[] = [];
  page.on("request", req => { if (req.method() === "POST" && req.url().endsWith("/api/operations")) sent.push(req.postDataJSON().action); });
  await page.getByRole("button", {name:"刷新联系人",exact:true}).click();
  await expect(page.getByText("联系人资料已刷新",{exact:true})).toBeVisible();
  expect(sent).toEqual(["refresh_contacts"]);
  await page.getByRole("button", {name:"整理记录",exact:true}).click();
  const dialog = page.getByRole("dialog",{name:"整理记录"});
  await dialog.getByRole("button", {name:/联系人资料已刷新/}).click();
  const history = await (await request.get("/api/operations?account_id=acct-1")).json();
  expect(history.items[0].counts.pages_processed).toBe(0);
  expect(history.items[0].counts.analysis_required).toBe(0);
  await expect(dialog.getByText(`联系人资料 ${history.items[0].counts.metadata_people}`, {exact:true})).toBeVisible();
  await expect(dialog.getByText(/目标会话/)).toHaveCount(0);
});
