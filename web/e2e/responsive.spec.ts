import { expect, test } from "@playwright/test";

/* ШАГ 15: адаптивность панели — 1024px без горизонтальной прокрутки, мобильная версия
   (390px) с сайдбаром в drawer: открывается кнопкой меню, закрывается по ссылке и Esc. */

const PAGES = ["/", "/events", "/leaderboard", "/drivers", "/checklists", "/reports", "/settings"];

async function login(page: import("@playwright/test").Page) {
  await page.goto("/login");
  await page.evaluate(() => localStorage.setItem("dg-tour-v1", "done"));
  await page.getByPlaceholder("admin@driverguard.kz").fill("admin@driverguard.kz");
  await page.getByPlaceholder("••••••••").fill(process.env.E2E_ADMIN_PASSWORD ?? "admin123");
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page.getByRole("heading", { name: "Обзор", level: 1 })).toBeVisible();
}

test.describe("планшет 1024px", () => {
  test.use({ viewport: { width: 1024, height: 768 } });
  test("все страницы без горизонтальной прокрутки, сайдбар виден", async ({ page }) => {
    await login(page);
    for (const path of PAGES) {
      await page.goto(path);
      await expect(page.getByTestId("sidebar")).toBeInViewport();
      const overflow = await page.evaluate(
        () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
      );
      expect(overflow, `${path}: горизонтальная прокрутка`).toBeLessThanOrEqual(0);
    }
  });
});

test.describe("телефон 390px", () => {
  test.use({ viewport: { width: 390, height: 844 } });
  test("сайдбар в drawer: кнопка меню, переход по ссылке, Esc", async ({ page }) => {
    await login(page);
    const sidebar = page.getByTestId("sidebar");
    await expect(sidebar).not.toBeInViewport();
    await page.getByRole("button", { name: "Открыть меню" }).click();
    await expect(sidebar).toBeInViewport();
    await sidebar.getByRole("link", { name: "Лидерборд" }).click();
    await expect(page.getByRole("heading", { name: "Лидерборд", level: 1 })).toBeVisible();
    await expect(sidebar).not.toBeInViewport();
    await page.getByRole("button", { name: "Открыть меню" }).click();
    await expect(sidebar).toBeInViewport();
    await page.keyboard.press("Escape");
    await expect(sidebar).not.toBeInViewport();
    // период на узком экране — select
    await page.getByRole("combobox", { name: "Период" }).selectOption("7d");
    const overflow = await page.evaluate(
      () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
    );
    expect(overflow).toBeLessThanOrEqual(0);
  });
});
