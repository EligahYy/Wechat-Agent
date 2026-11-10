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
    viewport: { width: 1920, height: 1100 },
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
  await page.reload();
  const csrf = await page.locator("meta[name=csrf]").getAttribute("content");
  const headers = { "X-CSRF-Token": csrf };
  const post = async (path, data = {}) => {
    const r = await page.request.post(base + path, { headers, data });
    assert(r.ok(), await r.text());
    return r.json();
  };
  await post("/__test__/progress-fixture");
  await post("/api/workspace/jobs/command", {
    source_id: "progress-42",
    action: "start",
  });
  await page.reload();
  await page
    .locator('#followup-rows [data-board-source="progress-42"]')
    .waitFor();
  assert.equal(await page.locator("aside nav button").count(), 2);
  assert.equal(
    await page.locator('[data-board-source="progress-42"]').count(),
    1,
  );
  assert.equal(
    await page
      .locator('#dashboard-rows [data-board-source="progress-42"]')
      .count(),
    0,
  );
  assert.equal(await page.locator("#followup-rows .board-row").count(), 1);
  assert.equal(await page.locator("#dashboard-rows .board-row").count(), 20);
  const top = await page.locator("#followup-group").boundingBox(),
    bottom = await page.locator("#other-group").boundingBox();
  assert(
    top.y + top.height <= bottom.y,
    "task customers must be above all other states",
  );
  assert(
    Math.abs(top.x - bottom.x) < 1 && Math.abs(top.width - bottom.width) < 1,
    "groups must share width",
  );
  const geometry = await page.locator(".board-columns").evaluateAll((groups) =>
    groups.map((g) =>
      [...g.children].map((c) => {
        const r = c.getBoundingClientRect();
        return { x: r.x, w: r.width, text: c.textContent };
      }),
    ),
  );
  assert.equal(geometry.length, 2);
  assert.equal(geometry[0].length, 5);
  geometry[0].forEach((c, i) => {
    assert.equal(c.text, geometry[1][i].text);
    assert(Math.abs(c.x - geometry[1][i].x) < 1);
    assert(Math.abs(c.w - geometry[1][i].w) < 1);
  });
  const archive = (
    await (await page.request.get(base + "/api/workspace/settings")).json()
  ).archive.messages;
  const row = page.locator('[data-board-source="progress-42"]');
  await row.locator(".contact-menu > summary").click();
  await row.getByRole("button", { name: "加入白名单", exact: true }).click();
  await row.waitFor({ state: "detached" });
  const excluded = await (
    await page.request.get(base + "/api/workspace/dashboard")
  ).json();
  assert.equal(excluded.counts.contacts, 42);
  assert.equal(excluded.followups.total, 0);
  assert(!excluded.items.some((r) => r.source_id === "progress-42"));
  assert.equal(
    (await (await page.request.get(base + "/api/workspace/settings")).json())
      .archive.messages,
    archive,
  );
  await page.getByRole("button", { name: "设置", exact: true }).click();
  await page
    .locator('#white-rows [data-white-restore="progress-42"]')
    .waitFor();
  await page.locator('#white-rows [data-white-restore="progress-42"]').click();
  await page.getByRole("button", { name: "数据大屏", exact: true }).click();
  await page
    .locator('#followup-rows [data-board-source="progress-42"]')
    .waitFor();
  for (const colorScheme of ["light", "dark"]) {
    await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
    for (const width of [1920, 1440, 1024, 768, 390, 320]) {
      await page.setViewportSize({ width, height: 1000 });
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
        "overflow " + width,
      );
      const layout = await page
        .locator(".board-row")
        .first()
        .evaluate((row) =>
          [...row.children].map((c) => ({
            x: c.getBoundingClientRect().x,
            w: c.getBoundingClientRect().width,
          })),
        );
      assert.equal(layout.length, 5);
      if (width === 1920)
        await page.screenshot({
          path: "/tmp/wechat-dashboard-" + colorScheme + ".png",
        });
      if (width === 390 && colorScheme === "dark")
        await page.screenshot({ path: "/tmp/wechat-dashboard-mobile.png" });
    }
  }
  const repaired = await post("/__test__/legacy-group-whitelist");
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.getByRole("button", { name: "设置", exact: true }).click();
  await page
    .locator('#white-rows [data-white-restore="white-colleague"]')
    .waitFor();
  assert.equal(await page.locator("#white-rows .white-row").count(), 4);
  assert.equal(
    await page
      .locator("#white-rows strong")
      .getByText(/服务商对接群/)
      .count(),
    0,
  );
  await page.locator('[data-white-entity="groups"]').click();
  await page
    .locator('#white-rows [data-white-restore="' + repaired.groups[0] + '"]')
    .waitFor();
  assert.equal(await page.locator("#white-rows .white-row").count(), 3);
  assert.equal(
    await page
      .locator("#white-rows")
      .getByText("群聊会话 · 群成员一并免跟进", { exact: true })
      .count(),
    3,
  );
  await page
    .getByText("群聊尚未同步，排除配置已保留。", { exact: true })
    .waitFor();
  const known = page.locator("#white-rows .white-row").filter({
    has: page.locator('[data-white-restore="' + repaired.groups[0] + '"]'),
  });
  await known.getByText("微信 ID", { exact: true }).click();
  await known.getByText("legacy-0@chatroom", { exact: true }).waitFor();
  for (const colorScheme of ["light", "dark"]) {
    await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
    for (const width of [1440, 390, 320]) {
      await page.setViewportSize({ width, height: 1000 });
      assert(
        await page.evaluate(
          () => document.documentElement.scrollWidth <= innerWidth,
        ),
      );
      if (width === 1440) {
        await page.locator("#whitelist").scrollIntoViewIfNeeded();
        await page.screenshot({
          path: "/tmp/whitelist-groups-" + colorScheme + ".png",
        });
      }
    }
  }
  await known.getByRole("button", { name: "恢复跟进", exact: true }).click();
  await page.waitForFunction(
    () => document.querySelectorAll("#white-rows .white-row").length === 2,
  );
  const people = await (
    await page.request.get(base + "/api/workspace/whitelist?entity=people")
  ).json();
  assert.equal(people.total, 3);
  assert.deepEqual(
    new Set(people.items.map((p) => p.source_id)),
    new Set(["merchant", "white-colleague", "group-staff-1"]),
  );
  assert(
    people.items.find((p) => p.source_id === "group-staff-1").groups.length ===
      1,
  );
  assert.deepEqual(errors, []);
  await browser.close();
  console.log(
    "Two-entry navigation, identical vertical groups, whitelist hiding/restoration, repaired group/person separation, pending groups, and responsive layouts passed.",
  );
})().catch((e) => {
  console.error(e);
  process.exit(1);
});
