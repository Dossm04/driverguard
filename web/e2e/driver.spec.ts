import { expect, test, type Page } from "@playwright/test";

/* ШАГ 13 «Готово, когда»: PWA устанавливается (manifest + service worker), чек-лист с 7 фото
   доходит до backend и возвращает вердикт, SOS создаёт событие sos. Плюс рейс с перерывом,
   Score и обучение — на макете телефона 390px в обеих темах. */

test.use({
  viewport: { width: 390, height: 844 },
  geolocation: { latitude: 51.128, longitude: 71.43 },
  permissions: ["geolocation"],
});

const API = process.env.E2E_API_URL ?? "http://localhost:8000/api/v1";
const PNG = Buffer.from(
  "iVBORw0KGgoAAAANSUhEUgAAAAEAAAABCAYAAAAfFcSJAAAADUlEQVR42mNkYPhfDwAChwGA60e6kgAAAABJRU5ErkJggg==",
  "base64",
);
const SHOTS = "../docs/screens";

function collectErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    if (msg.text().includes("Failed to fetch RSC payload")) return;
    if (/ERR_TUNNEL_CONNECTION_FAILED|ERR_CERT_AUTHORITY_INVALID|ERR_NAME_NOT_RESOLVED/.test(msg.text())) return;
    errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(String(err)));
  return errors;
}

async function driverLogin(page: Page) {
  await page.goto("/driver/login");
  await page.getByLabel("Телефон").fill("+77012441832");
  await page.getByLabel("PIN").fill(process.env.E2E_DRIVER_PIN ?? "1234");
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page.getByText("Иванов А.С.").first()).toBeVisible();
  await expect(page.getByText(/Здравствуйте!/)).toBeVisible();
}

const tab = (page: Page, name: string) =>
  page.getByRole("navigation", { name: "Разделы приложения" }).getByRole("link", { name });

test("PWA: вход по PIN, manifest и SW, чек-лист 7 фото → вердикт, рейс с перерывом", async ({ page }) => {
  test.setTimeout(150_000); // реальный ИИ отвечает до 30–60 с на комплект
  const errors = collectErrors(page);
  await driverLogin(page);

  // Устанавливаемость: манифест с start_url /driver и зарегистрированный service worker
  const href = await page.locator('link[rel="manifest"]').getAttribute("href");
  expect(href).toBeTruthy();
  const manifest = await (await page.request.get(new URL(href!, page.url()).toString())).json();
  expect(manifest.start_url).toBe("/driver");
  expect(manifest.display).toBe("standalone");
  expect(manifest.icons.length).toBeGreaterThanOrEqual(2);
  // SW регистрируется только в production-сборке (в dev он мешал бы HMR): под `next dev`
  // проверяем, что /sw.js отдаётся как скрипт, под `next start` — что регистрация состоялась.
  const sw = await page.request.get("/sw.js");
  expect(sw.status()).toBe(200);
  expect(sw.headers()["content-type"] ?? "").toContain("javascript");
  const isDevServer = await page.evaluate(() =>
    Array.from(document.scripts).some((s) => /\/_next\/static\/chunks\/main-app\.js\?v=/.test(s.src)),
  );
  if (!isDevServer) {
    await expect
      .poll(() => page.evaluate(() => navigator.serviceWorker.getRegistration().then((r) => Boolean(r))), {
        timeout: 20_000,
      })
      .toBe(true);
  }

  // Рейс доступен только после сегодняшнего чек-листа (seed может уже содержать его)
  const gateOpen = await page.getByText("Чек-лист на сегодня пройден").isVisible();
  if (gateOpen) {
    await expect(page.getByRole("button", { name: "Начать рейс" })).toBeEnabled();
  } else {
    await expect(page.getByRole("button", { name: "Начать рейс" })).toBeDisabled();
    await expect(page.getByRole("link", { name: /Сначала пройдите чек-лист/ })).toBeVisible();
  }

  // Чек-лист: 7 фото только с камеры (capture), затем анкета
  await tab(page, "Чек-лист").click();
  const input = page.getByTestId("checklist-photo-input");
  await expect(input).toHaveAttribute("capture", "environment");
  await expect(input).not.toHaveAttribute("multiple", /.*/);
  for (let i = 0; i < 7; i++) {
    await expect(page.getByText(`${i + 1} / 7`)).toBeVisible();
    await input.setInputFiles({ name: `photo-${i}.png`, mimeType: "image/png", buffer: PNG });
    await page.getByRole("button", { name: i < 6 ? "Далее" : "К анкете" }).click();
  }
  await expect(page.getByText(/обязательных пунктов/)).toBeVisible();
  // только группы анкеты (в шапке PWA тоже radiogroup — переключатель языка)
  const groups = page.getByRole("radiogroup").filter({ has: page.getByRole("radio", { name: "да", exact: true }) });
  await expect.poll(() => groups.count()).toBeGreaterThan(20);
  const n = await groups.count();
  for (let i = 0; i < n; i++) {
    await groups.nth(i).getByRole("radio", { name: "да", exact: true }).click();
  }
  await page.getByLabel("Пробег (одометр), км").fill("184320");
  await page.getByRole("button", { name: "Отправить на проверку" }).click();
  const verdict = page.getByTestId("checklist-verdict");
  await expect(verdict).toBeVisible({ timeout: 60_000 });
  expect(["допущен", "требует_внимания", "не_допущен"]).toContain(await verdict.getAttribute("data-verdict"));

  // Смена: чек-лист засчитан → рейс → перерыв «еда» → продолжить → завершить
  const verdictValue = await verdict.getAttribute("data-verdict");
  await page.getByRole("link", { name: "К смене" }).click();
  if (verdictValue === "не_допущен") {
    await expect(page.getByText(/не допущена к рейсу/)).toBeVisible();
    await expect(page.getByRole("button", { name: "Начать рейс" })).toBeDisabled();
    return;
  }
  await expect(page.getByText("Чек-лист на сегодня пройден")).toBeVisible();
  const start = page.getByRole("button", { name: "Начать рейс" });
  await expect(start).toBeEnabled();
  await start.click();
  await expect(page.getByText("В пути")).toBeVisible();
  await page.getByRole("button", { name: "Перерыв" }).click();
  await page.getByRole("button", { name: "Еда" }).click();
  await expect(page.getByText(/Причина: еда/)).toBeVisible();
  await page.getByRole("button", { name: "Продолжить рейс" }).click();
  await expect(page.getByText("В пути")).toBeVisible();
  await page.getByRole("button", { name: "Завершить рейс" }).click();
  await page.getByRole("button", { name: "Да, завершить" }).click();
  await expect(page.getByRole("button", { name: "Начать рейс" })).toBeVisible();
  expect(errors).toEqual([]);
});

test("PWA: SOS с удержанием 3 с создаёт событие sos, Score и урок за 60 секунд", async ({ page }) => {
  const errors = collectErrors(page);
  await driverLogin(page);

  await tab(page, "SOS").click();
  const hold = page.getByTestId("sos-hold");
  await hold.hover();
  await page.mouse.down();
  await page.waitForTimeout(1000);
  await page.mouse.up(); // отпустили раньше 3 с — ничего не произошло
  await expect(page.getByText("Что случилось?")).toHaveCount(0);
  await hold.hover();
  await page.mouse.down();
  await page.waitForTimeout(3400);
  await page.mouse.up();
  await page.getByRole("button", { name: "Здоровье" }).click();
  await expect(page.getByTestId("sos-done")).toBeVisible({ timeout: 15_000 });
  await expect(page.getByText("Координаты отправлены: 51.1280, 71.4300")).toBeVisible();

  // Событие видно координатору как критическое «SOS» с координатами
  const admin = await (
    await page.request.post(`${API}/auth/login`, { data: { email: "admin@driverguard.kz", password: process.env.E2E_ADMIN_PASSWORD ?? "admin123" } })
  ).json();
  const events = await (
    await page.request.get(`${API}/events?type=sos&page_size=5`, {
      headers: { Authorization: `Bearer ${admin.access_token}` },
    })
  ).json();
  const sos = events.items[0];
  expect(sos.driver_name).toBe("Иванов А.С.");
  expect(sos.severity).toBe("critical");
  expect(sos.lat).toBeCloseTo(51.128, 3);

  // Мой Score: кольцо, серия, «я и соседи», что хранится
  await tab(page, "Score").click();
  await expect(page.getByRole("img", { name: /Score \d+/ })).toBeVisible();
  await expect(page.getByText(/без критических событий/).first()).toBeVisible();
  await expect(page.getByText("Вы", { exact: true })).toBeVisible();
  await expect(page.getByText("Что хранится обо мне")).toBeVisible();

  // Обучение: назначенный урок сверху, кнопка активна только после таймера
  await page.clock.install();
  await tab(page, "Обучение").click();
  // после сценариев панели урок может быть назначен несколько раз — берём первую карточку
  await page.getByRole("button", { name: "Начать: Управление усталостью" }).first().click();
  await expect(page.getByRole("button", { name: "Дочитайте до конца" })).toBeDisabled();
  await page.clock.runFor(61_000);
  const done = page.getByRole("button", { name: "Отметить пройденным" });
  await expect(done).toBeEnabled();
  await done.click();
  await expect(page.getByRole("status")).toContainText("Урок засчитан");
  await expect(page.getByText("Пройден", { exact: true })).toBeVisible();
  expect(errors).toEqual([]);
});

for (const theme of ["dark", "light"] as const) {
  test(`PWA: 6 экранов в теме ${theme} без ошибок консоли`, async ({ page }) => {
    const errors = collectErrors(page);
    await driverLogin(page);
    await page.evaluate((t) => localStorage.setItem("theme-driver", t), theme);
    await page.reload();
    const screens = [
      { path: "/driver", name: "смена", ready: "Здравствуйте" },
      { path: "/driver/checklist", name: "чек-лист", ready: "Перёд + фары" },
      { path: "/driver/score", name: "score", ready: "Что хранится обо мне" },
      { path: "/driver/sos", name: "sos", ready: "Удерживайте кнопку" },
      { path: "/driver/learn", name: "обучение", ready: "Уроки по 30 секунд" },
      { path: "/driver/camera", name: "камера", ready: "Включить камеру" },
    ];
    for (const s of screens) {
      await page.goto(s.path);
      await expect(page.getByText(s.ready).first()).toBeVisible();
      if (theme === "dark") await expect(page.locator("html")).toHaveClass(/dark/);
      else await expect(page.locator("html")).not.toHaveClass(/dark/);
      await page.screenshot({ path: `${SHOTS}/pwa_${theme}_${s.name}.png`, fullPage: true });
    }
    expect(errors).toEqual([]);
  });
}
