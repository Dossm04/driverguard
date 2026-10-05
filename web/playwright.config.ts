import { existsSync } from "node:fs";

import { defineConfig } from "@playwright/test";

// Предустановленный chromium облачной среды; на других машинах Playwright
// использует свой стандартный браузер (npx playwright install chromium).
const SANDBOX_CHROMIUM = "/opt/pw-browsers/chromium";

/* Smoke-тесты панели. Требуют запущенных backend (порт 8000) и web (3000);
   seed выполняется автоматически в globalSetup (E2E_SKIP_SEED=1 — пропустить).
   Chromium предустановлен в среде (PLAYWRIGHT_BROWSERS_PATH). */
export default defineConfig({
  testDir: "./e2e",
  globalSetup: "./e2e/global-setup.ts",
  timeout: 45_000,
  retries: 0,
  use: {
    baseURL: process.env.E2E_BASE_URL ?? "http://localhost:3000",
    viewport: { width: 1440, height: 900 },
    locale: "ru-RU",
    launchOptions: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE
      ? { executablePath: process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE }
      : existsSync(SANDBOX_CHROMIUM)
      ? { executablePath: SANDBOX_CHROMIUM }
      : {},
  },
  reporter: [["list"]],
  /* Порядок важен: панель проверяет точные цифры seed (Figma), а сценарии PWA создают
     чек-лист, SOS и рейс — поэтому PWA идёт после панели (dependencies), seed один на прогон. */
  projects: [
    { name: "панель", testMatch: /(smoke|responsive)\.spec\.ts/ },
    { name: "pwa", testMatch: /driver\.spec\.ts/, dependencies: ["панель"] },
  ],
});
