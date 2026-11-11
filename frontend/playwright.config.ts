import { defineConfig } from "@playwright/test";
import path from "node:path";
export default defineConfig({
  testDir: "./e2e",
  workers: 1,
  timeout: 30000,
  fullyParallel: false,
  use: {
    baseURL: "http://127.0.0.1:18002",
    viewport: { width: 1440, height: 960 },
    trace: "retain-on-failure",
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE_PATH }
      : undefined,
  },
  webServer: [
    {
      command:
        ".venv/bin/python -m uvicorn tests.webserver:app_factory --factory --host 127.0.0.1 --port 18001",
      cwd: path.resolve(".."),
      url: "http://127.0.0.1:18001/api/health",
      reuseExistingServer: false,
    },
    {
      command: "npm run dev -- --port 18002 --strictPort",
      url: "http://127.0.0.1:18002",
      env: { WECHAT_API_URL: "http://127.0.0.1:18001" },
      reuseExistingServer: false,
    },
  ],
});
