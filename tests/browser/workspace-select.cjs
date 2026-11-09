const { chromium } = require("playwright");
const fs = require("fs");
const assert = require("assert/strict");
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/chromium",
    headless: true,
    args: ["--no-sandbox"],
  });
  const page = await browser.newPage({
    viewport: { width: 1920, height: 970 },
  });
  const errors = [];
  page.on("pageerror", (e) => errors.push(e.message));
  const base = "http://127.0.0.1:8768";
  await page.goto(base + "/");
  await page.request.post(base + "/login", {
    data: {
      token: fs
        .readFileSync(
          process.env.WA_BROWSER_DATA_DIR + "/session-token",
          "utf8",
        )
        .trim(),
    },
  });
  await page.goto(base + "/workspace?view=customers");
  const phase = () =>
    page.getByRole("combobox", { name: "备货阶段", exact: true });
  await phase().waitFor();
  for (const colorScheme of ["light", "dark"]) {
    await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
    for (const [width, height] of [
      [1920, 970],
      [1440, 900],
      [1024, 768],
      [900, 600],
      [768, 600],
      [760, 600],
      [390, 844],
      [320, 568],
    ]) {
      await page.setViewportSize({ width, height });
      await phase().scrollIntoViewIfNeeded();
      const boxes = await page.locator("#customer-search").evaluate((form) => {
        const rect = (el) => {
          const r = el.getBoundingClientRect();
          return { x: r.x, y: r.y, w: r.width, h: r.height, b: r.bottom };
        };
        return {
          input: rect(form.querySelector("input")),
          select: rect(form.querySelector(".select-trigger")),
          button: rect(form.querySelector("button:not(.select-trigger)")),
        };
      });
      assert(
        Math.abs(boxes.input.h - boxes.select.h) < 1 &&
          Math.abs(boxes.input.h - boxes.button.h) < 1,
        "control heights " + width,
      );
      if (width > 1000)
        assert(
          Math.max(boxes.input.b, boxes.select.b, boxes.button.b) -
            Math.min(boxes.input.b, boxes.select.b, boxes.button.b) <
            1,
          "search row bottom alignment " + width,
        );
      else
        assert(
          boxes.button.y >= boxes.select.b,
          "compact search button must follow fields",
        );
      assert(
        !(await page.evaluate(
          () => document.documentElement.scrollWidth > innerWidth,
        )),
        "page overflow " + width,
      );
      await phase().click();
      const menu = page.getByRole("listbox", { name: "备货阶段", exact: true });
      await menu.waitFor();
      const rect = await menu.boundingBox();
      assert(
        rect.x >= 0 &&
          rect.y >= 0 &&
          rect.x + rect.width <= width + 1 &&
          rect.y + rect.height <= height + 1,
        "menu must fit viewport " + width,
      );
      assert.equal(await menu.getByRole("option").count(), 8);
      assert.equal(
        await menu.getByRole("option", { selected: true }).count(),
        1,
      );
      if (width === 1920)
        await page.screenshot({
          path: "/tmp/workspace-select-" + colorScheme + ".png",
        });
      if (width === 390 && colorScheme === "dark")
        await page.screenshot({ path: "/tmp/workspace-select-mobile.png" });
      await page.keyboard.press("Escape");
      assert.equal(await phase().getAttribute("aria-expanded"), "false");
    }
  }
  await page.setViewportSize({ width: 1440, height: 1000 });
  await phase().focus();
  await page.keyboard.press("ArrowDown");
  await page.keyboard.press("End");
  await page.keyboard.press("Enter");
  assert.equal(
    await page.locator("#customer-search select").inputValue(),
    "closed",
  );
  await phase().click();
  await page.getByRole("option", { name: "全部阶段", exact: true }).click();
  await page.getByRole("button", { name: "查找客户", exact: true }).click();
  await phase().click();
  await page.getByRole("textbox", { name: "搜索客户", exact: true }).click();
  assert.equal(await phase().getAttribute("aria-expanded"), "false");
  await phase().focus();
  await page.keyboard.press("Enter");
  await page.keyboard.press("Tab");
  assert.equal(await phase().getAttribute("aria-expanded"), "false");
  const csrf = await page.locator("meta[name=csrf]").getAttribute("content");
  const post = async (path, data = {}) => {
    const response = await page.request.post(base + path, {
      headers: { "X-CSRF-Token": csrf },
      data,
    });
    assert(response.ok(), await response.text());
    return response.json();
  };
  await post("/api/crm/configure", { enabled: true });
  await post("/__test__/review-fixture?role=true");
  await page.reload();
  await page.getByRole("button", { name: "查看档案", exact: true }).click();
  await page.locator("dialog[open]").waitFor();
  await page.getByRole("tab", { name: "人工跟进", exact: true }).click();
  const action = page.getByRole("combobox", {
      name: "关联待办（可选）",
      exact: true,
    }),
    state = page.getByRole("combobox", { name: "待办状态", exact: true });
  assert(await state.isDisabled());
  await action.click();
  await page.getByRole("option", { name: "确认英国报价", exact: true }).click();
  await state.waitFor({ state: "visible" });
  await page.waitForFunction(
    () => !document.querySelector("select[name=action_state]").disabled,
  );
  assert(!(await state.isDisabled()));
  await state.click();
  const stateMenu = page.getByRole("listbox", {
    name: "待办状态",
    exact: true,
  });
  await stateMenu.waitFor();
  assert(
    await stateMenu.evaluate((el) => !!el.closest("dialog")),
    "menu must remain inside modal context",
  );
  await page.keyboard.press("Escape");
  assert(
    await page.locator("dialog").isVisible(),
    "Escape closes dropdown before drawer",
  );
  await action.click();
  await page
    .getByRole("option", { name: "只记客户跟进，不改变待办", exact: true })
    .click();
  await page.waitForFunction(
    () => document.querySelector("select[name=action_state]").disabled,
  );
  assert(await state.isDisabled());
  await page.getByRole("combobox", { name: "沟通情况", exact: true }).click();
  await page.getByRole("option", { name: "已收到反馈", exact: true }).click();
  assert.equal(
    await page.locator("#customer-followup-form [name=outcome]").inputValue(),
    "replied",
  );
  await page
    .locator("#customer-followup-form")
    .evaluate((form) => form.reset());
  await page.waitForFunction(
    () =>
      document.querySelector("#customer-followup-form .select-value")
        .textContent === "已联系",
  );
  await page.getByRole("tab", { name: "批次与行动", exact: true }).click();
  await page.getByText("人工确认批次阶段", { exact: true }).click();
  const batch = page.getByRole("combobox", { name: "阶段", exact: true });
  await batch.click();
  await page.getByRole("option", { name: "备货中", exact: true }).click();
  await page
    .getByRole("textbox", { name: "判断依据", exact: true })
    .fill("已核对备货计划（虚构）");
  await page.getByRole("button", { name: "保存阶段判断", exact: true }).click();
  await page.locator("dialog").waitFor({ state: "hidden" });
  const doc = await (
    await page.request.get(base + "/api/workspace/customer?source_id=merchant")
  ).json();
  assert(
    Object.values(doc.body.batches).some(
      (b) => b.stage === "preparing" && b.stage_locked,
    ),
    "batch selection must submit native value",
  );
  await page.getByRole("button", { name: "查看档案", exact: true }).click();
  await page.locator("dialog[open]").waitFor();
  await page.getByRole("tab", { name: "批次与行动", exact: true }).click();
  await page.getByRole("combobox", { name: "你的判断", exact: true }).click();
  await page.getByRole("option", { name: "商家", exact: true }).click();
  await page.getByRole("button", { name: "保存判断", exact: true }).click();
  await page.locator("dialog").waitFor({ state: "hidden" });
  const confirmed = await (
    await page.request.get(base + "/api/workspace/customer?source_id=merchant")
  ).json();
  assert.equal(confirmed.body.manual_role, "merchant");
  assert.deepEqual(errors, []);
  await browser.close();
  console.log(
    "Shared dropdown menus, light/dark + 8 viewport layouts, keyboard/outside dismissal, modal Escape, disabled dependencies, reset, batch and role submissions passed.",
  );
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
