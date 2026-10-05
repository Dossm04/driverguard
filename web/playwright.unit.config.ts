import { defineConfig } from "@playwright/test";

/* Юнит-тесты чистых модулей (lib/dms) в раннере Playwright — без браузера, backend и seed. */
export default defineConfig({
  testDir: "./e2e/unit",
  timeout: 20_000,
  reporter: [["list"]],
});
