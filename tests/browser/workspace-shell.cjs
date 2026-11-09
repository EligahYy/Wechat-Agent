const { chromium } = require("playwright");
const fs = require("fs");
const assert = require("assert/strict");
(async () => {
  const browser = await chromium.launch({
    executablePath: "/usr/bin/chromium",
    args: ["--no-sandbox"],
    headless: true,
  });
  const page = await browser.newPage({
    viewport: { width: 1920, height: 970 },
  });
  const errors = [];
  page.on("pageerror", (error) => errors.push(error.message));
  const base = "http://127.0.0.1:8768";
  await page.goto(base + "/");
  const token = fs
    .readFileSync(process.env.WA_BROWSER_DATA_DIR + "/session-token", "utf8")
    .trim();
  await page.request.post(base + "/login", { data: { token } });
  await page.goto(base + "/workspace?view=settings");
  await page.locator("#settings-view").waitFor();
  await page.locator(".monitor-row").first().waitFor();
  const footer = page.locator(".sidebar-footer");
  for (const colorScheme of ["light", "dark"]) {
    await page.emulateMedia({ colorScheme, reducedMotion: "reduce" });
    for (const [width, height] of [
      [1920, 970],
      [1440, 900],
      [1024, 600],
      [900, 400],
      [768, 360],
    ]) {
      await page.setViewportSize({ width, height });
      await page.evaluate(() => scrollTo(0, 0));
      await page.locator("aside [data-view=settings]").scrollIntoViewIfNeeded();
      const before = await footer.boundingBox();
      assert(
        before.y + before.height >= height - 40 &&
          before.y + before.height <= height - 12,
        `footer must stay at bottom: ${width}x${height}`,
      );
      const settings = await page
        .locator("aside [data-view=settings]")
        .boundingBox();
      assert(
        settings.y + settings.height <= before.y + 1,
        "footer overlaps menu",
      );
      const shell = await page.locator("aside").boundingBox();
      assert(
        shell.y === 0 && Math.abs(shell.height - height) < 1,
        "sidebar must fill viewport",
      );
      const rows = await page
        .locator("aside nav button")
        .evaluateAll((buttons) =>
          buttons.map((button) => ({
            width: button.getBoundingClientRect().width,
            height: button.getBoundingClientRect().height,
          })),
        );
      assert(
        rows.every(
          (row) => row.height >= 44 && Math.abs(row.width - rows[0].width) < 1,
        ),
        "sidebar button size changed",
      );
      if (width === 1920 && colorScheme === "dark")
        await page.screenshot({ path: "/tmp/workspace-footer-desktop.png" });
      if (width === 900 && colorScheme === "dark")
        await page.screenshot({ path: "/tmp/workspace-footer-short.png" });
      await page.evaluate(() =>
        scrollTo(0, document.documentElement.scrollHeight),
      );
      const after = await footer.boundingBox();
      assert(
        Math.abs(after.y - before.y) < 1,
        "page scrolling moved sidebar footer",
      );
    }
    for (const [width, height] of [
      [760, 600],
      [390, 844],
      [320, 568],
    ]) {
      await page.setViewportSize({ width, height });
      assert(
        await footer.isHidden(),
        "desktop footer must not appear in mobile navigation",
      );
      await page.locator("aside [data-view=settings]").click();
      await page.locator("#settings-view").waitFor();
      await page.evaluate(() =>
        scrollTo(0, document.documentElement.scrollHeight),
      );
      const shell = await page.locator("aside").boundingBox();
      assert(
        shell.height <= 80 && Math.abs(shell.y) < 1,
        "mobile navigation height or sticky position changed",
      );
      assert(
        !(await page.evaluate(
          () => document.documentElement.scrollWidth > innerWidth,
        )),
        "horizontal overflow",
      );
    }
  }
  assert.deepEqual(errors, []);
  await browser.close();
  console.log(
    "Sidebar footer stays at viewport bottom through scrolling and short windows; menus remain accessible. Mobile navigation and light/dark layouts passed.",
  );
})().catch((error) => {
  console.error(error);
  process.exit(1);
});
