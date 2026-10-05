import { readFileSync } from "node:fs";

import { expect, test, type Page } from "@playwright/test";

/* ШАГ 4 «Готово, когда»: логин работает с seed-админом; все маршруты открываются
   в обеих темах без ошибок консоли; тур показывается при первом входе;
   скриншоты складываются в docs/screens/. */

const ROUTES = [
  { title: "Обзор", name: "обзор" },
  { title: "Live-карта", name: "карта" },
  { title: "События", name: "события" },
  { title: "Лидерборд", name: "лидерборд" },
  { title: "Водители", name: "водители" },
  { title: "Чек-листы", name: "чек-листы" },
  { title: "Отчёты", name: "отчёты" },
  { title: "Настройки", name: "настройки" },
];

const SHOTS = "../docs/screens";

function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    // Обрыв prefetch при жёстком page.goto — артефакт теста, не ошибка приложения
    if (msg.text().includes("Failed to fetch RSC payload")) return;
    // CARTO-тайлы блокируются egress-прокси ЭТОЙ среды (docs/decisions.md);
    // в реальном окружении они загружаются
    // тайлы карты (OpenStreetMap) и внешние ресурсы могут быть недоступны в изолированной среде
    if (/openstreetmap|cartocdn/.test(msg.location()?.url ?? "")) return;
    if (/ERR_TUNNEL_CONNECTION_FAILED|ERR_CERT_AUTHORITY_INVALID|ERR_NAME_NOT_RESOLVED/.test(msg.text())) return;
    errors.push(msg.text());
  });
  page.on("pageerror", (err) => errors.push(String(err)));
  return errors;
}

async function login(page: Page, { skipTour = true } = {}) {
  await page.goto("/login");
  if (skipTour) {
    await page.evaluate(() => localStorage.setItem("dg-tour-v1", "done"));
  }
  await page.getByPlaceholder("admin@driverguard.kz").fill("admin@driverguard.kz");
  await page.getByPlaceholder("••••••••").fill(process.env.E2E_ADMIN_PASSWORD ?? "admin123");
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page.getByRole("heading", { name: "Обзор", level: 1 })).toBeVisible();
}

async function setTheme(page: Page, theme: "dark" | "light") {
  await page.evaluate((t) => localStorage.setItem("theme", t), theme);
  await page.reload();
  if (theme === "dark") {
    await expect(page.locator("html")).toHaveClass(/dark/);
  } else {
    await expect(page.locator("html")).not.toHaveClass(/dark/);
  }
}

test("логин отклоняет неверный пароль и пускает seed-админа", async ({ page }) => {
  await page.goto("/login");
  await page.evaluate(() => localStorage.setItem("dg-tour-v1", "done"));
  await page.getByPlaceholder("admin@driverguard.kz").fill("admin@driverguard.kz");
  await page.getByPlaceholder("••••••••").fill("wrong");
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page.getByText("Неверный email или пароль")).toBeVisible();

  await page.getByPlaceholder("••••••••").fill(process.env.E2E_ADMIN_PASSWORD ?? "admin123");
  await page.getByRole("button", { name: "Войти" }).click();
  await expect(page.getByRole("heading", { name: "Обзор", level: 1 })).toBeVisible();
});

test("без токена маршруты уводят на /login", async ({ page }) => {
  await page.goto("/events");
  await expect(page).toHaveURL(/\/login/);
});

test("мини-тур показывается при первом входе и запоминает прохождение", async ({ page }) => {
  await login(page, { skipTour: false });
  const dialog = page.getByRole("dialog", { name: "Обучающий тур" });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByText("Навигация")).toBeVisible();
  await dialog.getByRole("button", { name: "Далее" }).click();
  await expect(dialog.getByText("Период данных")).toBeVisible();
  await dialog.getByRole("button", { name: "Пропустить" }).click();
  await expect(dialog).toBeHidden();
  // после прохождения тур не всплывает
  await page.reload();
  await expect(page.getByRole("heading", { name: "Обзор", level: 1 })).toBeVisible();
  await expect(page.getByRole("dialog", { name: "Обучающий тур" })).toBeHidden();
  // но запускается по кнопке «?»
  await page.getByRole("button", { name: "Показать подсказки" }).click();
  await expect(page.getByRole("dialog", { name: "Обучающий тур" })).toBeVisible();
});

test("живые данные каркаса: бейдж событий и виджет устройств из API", async ({ page }) => {
  await login(page);
  await expect(page.locator('[data-tour="nav"]').getByText("3", { exact: true })).toBeVisible();
  await expect(page.locator('[data-tour="devices"]')).toContainText("5");
  await expect(page.locator('[data-tour="devices"]')).toContainText("1 устройство офлайн");
});

for (const theme of ["dark", "light"] as const) {
  test(`все маршруты в теме ${theme} — без ошибок консоли`, async ({ page }) => {
    const errors = collectConsoleErrors(page);
    await login(page);
    await setTheme(page, theme);
    for (const route of ROUTES) {
      // навигация кликами по сайдбару — как у реального пользователя
      await page.locator('[data-tour="nav"]').getByRole("link", { name: route.title }).click();
      await expect(page.getByRole("heading", { name: route.title, level: 1 })).toBeVisible();
      await page.waitForLoadState("networkidle");
      if (route.name === "карта") {
        // карта грузится динамическим чанком — дожидаемся маркеров перед скриншотом
        await expect(page.locator(".dg-mk")).toHaveCount(6);
      }
      if (route.name === "лидерборд") {
        await expect(page.getByLabel("Место 1")).toBeVisible();
      }
      if (route.name === "события") {
        await expect(page.locator("tbody tr").first()).toBeVisible();
      }
      if (route.name === "водители") {
        await expect(page.getByTestId("driver-card")).toHaveCount(6);
      }
      if (route.name === "чек-листы") {
        await expect(page.getByTestId("checklist-card")).toHaveCount(4);
      }
      if (route.name === "отчёты") {
        await expect(page.locator('[data-kpi="Средний Score"]')).toContainText("78");
      }
      if (route.name === "настройки") {
        await expect(page.getByLabel("Засыпание за рулём")).toHaveValue("15");
      }
      await page.screenshot({
        path: `${SHOTS}/панель_${theme}_${route.name}.png`,
        fullPage: false,
      });
    }
    expect(errors, `console-ошибки в теме ${theme}: ${errors.join(" | ")}`).toEqual([]);
  });
}

test("переключатель темы работает и выбор переживает перезагрузку", async ({ page }) => {
  await login(page);
  await expect(page.locator("html")).toHaveClass(/dark/); // тёмная по умолчанию
  await page.getByRole("button", { name: "Переключить тему" }).click();
  await expect(page.locator("html")).not.toHaveClass(/dark/);
  await page.reload();
  await expect(page.locator("html")).not.toHaveClass(/dark/);
});

test("Обзор: KPI-карточки и списки показывают цифры Figma", async ({ page }) => {
  await login(page);
  const kpi = (title: string) => page.locator(`[data-kpi="${title}"]`);
  await expect(kpi("Машин на линии")).toContainText("5");
  await expect(kpi("Машин на линии")).toContainText("1 офлайн");
  await expect(kpi("Событий сегодня")).toContainText("14");
  await expect(kpi("Событий сегодня")).toContainText("vs. вчера 11");
  await expect(kpi("Критических за 24ч")).toContainText("3");
  await expect(kpi("Средний Score парка")).toContainText("78");
  await expect(kpi("Средний Score парка")).toContainText("цель: ≥80");
  await expect(kpi("Пробег за неделю")).toContainText(/12\s?480/);
  // ровно 98.2 сторожит pytest сразу после seed; между сеансами окно 7 дней
  // медленно вымывает биты офлайн-устройства — e2e принимает 98.x
  await expect(kpi("Аптайм устройств")).toContainText(/98(\.\d)?%/);

  // Последние критические — ровно герои Figma, свежие сверху
  const critical = page.getByText("Последние критические").locator("..").locator("..");
  await expect(critical.getByText("3 события")).toBeVisible();
  await expect(page.getByText(/Отвлечение >\d+ сек/).first()).toBeVisible();
  await expect(page.getByText(/Превышение скорости \+42 км\/ч/).first()).toBeVisible();
  await expect(page.getByText("Засыпание за рулём").first()).toBeVisible();

  // Красная зона: тройка с Score и поездками
  await expect(page.getByText("Иванов А.С.", { exact: true })).toBeVisible();
  await expect(page.getByText("41", { exact: true })).toBeVisible();
  await expect(page.getByText("12 поездок")).toBeVisible();
  await expect(page.getByText("56", { exact: true })).toBeVisible();
});

test("Обзор: период меняет KPI, модалка события открывается", async ({ page }) => {
  await login(page);
  await page.getByRole("tab", { name: "7 дней" }).click();
  await expect(page.locator('[data-kpi="Событий за 7 дней"]')).toContainText("33");
  await page.getByRole("tab", { name: "Сегодня" }).click();
  await expect(page.locator('[data-kpi="Событий сегодня"]')).toContainText("14");

  await page.getByRole("button", { name: "Открыть" }).first().click();
  const dialog = page.getByRole("dialog", { name: /Событие:/ });
  await expect(dialog).toBeVisible();
  await expect(dialog).toContainText("Confidence");
  await expect(dialog).toContainText("KZ");
  await dialog.getByRole("button", { name: "Закрыть" }).click();
  await expect(dialog).toBeHidden();
});

test("Live-карта: маркеры движутся по WS, клик панели центрирует, тема меняет подложку", async ({ page }) => {
  // слушаем WS-кадры позиций до открытия страницы
  const frames: { vehicles: { vehicle_id: number; lat: number; lon: number; status: string }[] }[] = [];
  page.on("websocket", (ws) =>
    ws.on("framereceived", (f) => {
      try {
        const d = JSON.parse(String(f.payload));
        if (d.type === "positions") frames.push(d);
      } catch {
        /* не-JSON кадр */
      }
    }),
  );

  await login(page);
  await page.locator('[data-tour="nav"]').getByRole("link", { name: "Live-карта" }).click();
  await expect(page.locator(".leaflet-container")).toBeVisible();

  // 6 маркеров, один — офлайн (серый), критичные пульсируют
  await expect(page.locator(".dg-mk")).toHaveCount(6);
  await expect(page.locator(".dg-mk-offline")).toHaveCount(1);
  await expect(page.getByText("LIVE", { exact: true })).toBeVisible();

  // панель: 6 машин; клик открывает попап с водителем и действиями
  const rows = page.locator("[data-veh-row]");
  await expect(rows).toHaveCount(6);
  await rows.first().click();
  await expect(page.locator(".leaflet-popup")).toContainText("Иванов А.С.");
  await expect(page.locator(".leaflet-popup").getByRole("link", { name: /Позвонить/ })).toBeVisible();
  await expect(page.locator(".leaflet-popup").getByRole("link", { name: /Профиль/ })).toBeVisible();

  // движение без перезагрузки: ждём, пока координаты онлайн-машины изменятся
  // (снапшот подключения и первый broadcast совпадают — сдвиг на следующем тике)
  await expect
    .poll(
      () => {
        if (frames.length < 2) return false;
        const a = frames[0].vehicles.find((v) => v.status !== "offline");
        const b = frames[frames.length - 1].vehicles.find(
          (v) => v.vehicle_id === a?.vehicle_id,
        );
        return !!a && !!b && (a.lat !== b.lat || a.lon !== b.lon);
      },
      { timeout: 15_000, message: "машина не движется по WS" },
    )
    .toBeTruthy();

  // офлайн-машина стоит на месте
  const offFirst = frames[0].vehicles.find((v) => v.status === "offline")!;
  const offLast = frames[frames.length - 1].vehicles.find((v) => v.vehicle_id === offFirst.vehicle_id)!;
  expect(offFirst.lat === offLast.lat && offFirst.lon === offLast.lon).toBeTruthy();

  // переключение темы меняет подложку карты без перезагрузки (TC-13): OpenStreetMap без ключа,
  // тёмная тема — слой с CSS-фильтром .tiles-dark, светлая — без него
  await expect(page.locator(".leaflet-layer.tiles-dark").first()).toBeAttached();
  await page.getByRole("button", { name: "Переключить тему" }).click();
  await expect(page.locator(".leaflet-layer:not(.tiles-dark)").first()).toBeAttached();
  await expect(page.locator(".leaflet-layer.tiles-dark")).toHaveCount(0);
});

test("События: фильтры комбинируются, review без перезагрузки, CSV с кириллицей", async ({ page }) => {
  await login(page);
  await page.locator('[data-tour="nav"]').getByRole("link", { name: "События" }).click();
  await expect(page.getByRole("heading", { name: "События", level: 1 })).toBeVisible();

  // период «Сегодня» из топбара: 14 событий
  await expect(page.getByText("из 14")).toBeVisible();

  // фильтр по типу
  await page.getByLabel("Фильтр по типу").selectOption("speeding");
  await expect(page.getByText("из 7")).toBeVisible();

  // + чип статуса: новых превышений сегодня ровно одно (герой +42)
  await page.getByRole("tab", { name: "Новые" }).click();
  await expect(page.getByText("из 1")).toBeVisible();
  await expect(page.getByText("Превышение скорости +42 км/ч")).toBeVisible();

  // сброс фильтров
  await page.getByRole("tab", { name: "Все" }).click();
  await page.getByLabel("Фильтр по типу").selectOption("");
  await expect(page.getByText("из 14")).toBeVisible();

  // review без перезагрузки: единственный сегодня «Ремень не пристёгнут»
  const row = page.locator("tbody tr").filter({ hasText: "Ремень не пристёгнут" });
  await expect(row).toContainText("Подтверждено");
  await row.getByLabel("Ложное").click();
  await expect(page.getByRole("status")).toContainText("баллы возвращены");
  await expect(row).toContainText("Ложное");
  // возвращаем как было (данные seed восстановлены)
  await row.getByLabel("Подтвердить").click();
  await expect(row).toContainText("Подтверждено");

  // модалка с review-кнопками и сноской
  await page.locator("tbody tr").first().getByRole("button", { name: "Клип" }).click();
  const dialog = page.getByRole("dialog", { name: /Событие:/ });
  await expect(dialog).toBeVisible();
  await expect(dialog.getByRole("button", { name: "Ложное срабатывание" })).toBeVisible();
  await expect(dialog).toContainText("датасет дообучения");
  await dialog.getByRole("button", { name: "Закрыть" }).click();

  // CSV: BOM + кириллица + разделитель «;»
  const downloadPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "Экспорт CSV" }).click();
  const download = await downloadPromise;
  const text = readFileSync((await download.path())!, "utf-8");
  expect(text.startsWith("﻿")).toBeTruthy();
  expect(text).toContain("Засыпание за рулём");
  expect(text).toContain(";");
  expect(text.trim().split("\n")).toHaveLength(15); // заголовок + 14 событий
});

test("Лидерборд: подиум, мгновенный период, клик открывает профиль", async ({ page }) => {
  await login(page);
  await page.locator('[data-tour="nav"]').getByRole("link", { name: "Лидерборд" }).click();
  await expect(page.getByRole("heading", { name: "Лидерборд", level: 1 })).toBeVisible();

  // подиум недели: Ким С.В. 95 на первом месте
  const podium = page.getByLabel("Место 1").locator("..");
  await expect(podium).toContainText("Ким С.В.");
  await expect(podium).toContainText("95");
  await expect(page.locator("tbody tr")).toHaveCount(6);

  // мгновенное переключение на месяц: лучшие выходят в 100
  await page.getByRole("tab", { name: "Месяц" }).click();
  await expect(page.getByLabel("Место 1").locator("..")).toContainText("100");
  await page.getByRole("tab", { name: "Неделя" }).click();
  await expect(page.getByLabel("Место 1").locator("..")).toContainText("95");

  // командный зачёт и бейджи
  await expect(page.locator("b").filter({ hasText: "Депо Караганда" })).toBeVisible();
  await expect(page.locator("b").filter({ hasText: "Депо Астана" })).toBeVisible();
  await expect(page.getByText("Неделя без риска")).toBeVisible();
  await expect(page.getByText("× 2")).toBeVisible(); // Сапаров (9) и Ким (14)

  // сноска с формулой и клик в профиль
  await expect(page.getByText(/clamp\(40\.\.100/)).toBeVisible();
  await page.locator("tbody tr").filter({ hasText: "Иванов А.С." }).click();
  await expect(page).toHaveURL(/\/drivers\/\d+/);
  await expect(page.getByRole("heading", { name: "Иванов А.С." })).toBeVisible();
});

test("Отчёты: сводка по seed, CSV с BOM и PDF с кириллическим шрифтом", async ({ page }) => {
  await login(page);
  await page.locator('[data-tour="nav"]').getByRole("link", { name: "Отчёты" }).click();
  await expect(page.locator('[data-kpi="События"]')).toContainText("14");
  await expect(page.locator('[data-kpi="Критические"]')).toContainText("3");
  await expect(page.locator('[data-kpi="Средний Score"]')).toContainText("78");
  await expect(page.getByText("Динамика Score парка")).toBeVisible();
  await expect(page.locator("tbody tr").filter({ hasText: "Иванов А.С." }).first()).toBeVisible();

  // фильтр по депо сужает список водителей
  await page.getByLabel("Депо").selectOption({ label: "Астана" });
  await expect(page.locator('[data-kpi="Критические"]')).toContainText("3 водителя");
  await page.getByLabel("Депо").selectOption({ label: "Все депо" });

  const csvPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "CSV" }).click();
  const csv = readFileSync((await (await csvPromise).path())!, "utf-8");
  expect(csv.startsWith("\ufeff")).toBeTruthy();
  expect(csv).toContain("Иванов А.С.");
  expect(csv).toContain("динамика_score");

  const pdfPromise = page.waitForEvent("download");
  await page.getByRole("button", { name: "PDF" }).click();
  const pdf = readFileSync((await (await pdfPromise).path())!);
  expect(pdf.subarray(0, 5).toString()).toBe("%PDF-");
  expect(pdf.includes("DejaVuSans")).toBeTruthy(); // кириллический шрифт встроен
  await expect(page.getByRole("status")).toContainText("PDF-отчёт сформирован");
});

test("Водители: поиск и сортировка карточек, профиль с графиком, обучением и модалкой", async ({
  page,
}) => {
  await login(page);
  await page.locator('[data-tour="nav"]').getByRole("link", { name: "Водители" }).click();
  await expect(page.getByTestId("driver-card")).toHaveCount(6);

  // сортировка по Score: лучший (Ким, 95) первым; поиск сужает до одного
  await expect(page.getByTestId("driver-card").first()).toContainText("Ким С.В.");
  await page.getByLabel("Поиск водителя").fill("Иванов");
  await expect(page.getByTestId("driver-card")).toHaveCount(1);

  // профиль Иванова: шапка, кольцо 55, графики, рейсы, обучение из seed
  await page.getByTestId("driver-card").click();
  await expect(page).toHaveURL(/\/drivers\/\d+/);
  await expect(page.getByRole("heading", { name: "Иванов А.С." })).toBeVisible();
  await expect(page.getByRole("img", { name: "Score 55" })).toBeVisible();
  await expect(page.getByText("Score · 8 недель")).toBeVisible();
  await expect(page.getByText("События · 30 дней")).toBeVisible();
  await expect(page.getByText("Последние рейсы")).toBeVisible();
  const lessons = page.getByTestId("training-list").getByText("Управление усталостью");
  await expect(lessons.first()).toBeVisible();
  const lessonsBefore = await lessons.count();

  // модалка события из ленты — без кнопок review (разбор с Обзора/профиля)
  await page.getByRole("button", { name: "Разбор" }).first().click();
  const modal = page.getByRole("dialog");
  await expect(modal).toBeVisible();
  await expect(modal.getByRole("button", { name: "Подтвердить" })).toHaveCount(0);
  await page.keyboard.press("Escape");
  await expect(modal).toBeHidden();

  // назначение обучения из профиля добавляет запись в список
  await page.getByRole("button", { name: "Назначить обучение" }).click();
  await expect(page.getByRole("status")).toContainText("назначено");
  await expect(lessons).toHaveCount(lessonsBefore + 1);
});

test("Водители: новый водитель через форму появляется в списке и лидерборде", async ({
  page,
}) => {
  await login(page);
  await page.locator('[data-tour="nav"]').getByRole("link", { name: "Водители" }).click();
  await page.getByRole("button", { name: "Добавить водителя" }).click();

  const dialog = page.getByRole("dialog", { name: "Добавить водителя" });
  // валидация: пустое ФИО не проходит
  await dialog.getByRole("button", { name: "Добавить", exact: true }).click();
  await expect(dialog.getByText(/Введите ФИО/)).toBeVisible();

  await dialog.getByLabel("ФИО").fill("Тестов Т.Т.");
  await dialog.getByLabel("Депо").selectOption({ label: "Астана" });
  await dialog.getByLabel(/PIN/).fill("4321");
  // честный 409: телефон Иванова из seed уже занят — ошибка показывается в форме
  await dialog.getByLabel("Телефон", { exact: true }).fill("+77012441832");
  await dialog.getByRole("button", { name: "Добавить", exact: true }).click();
  await expect(dialog.getByText("Водитель с таким телефоном уже существует")).toBeVisible();
  // уникальный телефон на прогон — без 409 при повторе даже без reseed
  await dialog.getByLabel("Телефон", { exact: true }).fill(`+7777${String(Date.now()).slice(-7)}`);
  await dialog.getByRole("button", { name: "Добавить", exact: true }).click();
  await expect(page.getByRole("status")).toContainText("Водитель добавлен: Тестов Т.Т.");

  // «Готово, когда» ШАГ 9: в списке и в лидерборде без перезагрузки backend
  await page.getByLabel("Поиск водителя").fill("Тестов");
  const card = page.getByTestId("driver-card");
  await expect(card).toHaveCount(1);
  await expect(card).toContainText("Астана");
  await expect(card.getByText("новичок")).toBeVisible(); // новичок без рейсов — без кольца Score (пакет 1)

  await page.locator('[data-tour="nav"]').getByRole("link", { name: "Лидерборд" }).click();
  await expect(page.locator("tbody tr").filter({ hasText: "Тестов Т.Т." })).toBeVisible();
});

test("Чек-листы: seed-вердикты, теги ИИ, расхождения, действия координатора и фильтр", async ({
  page,
}) => {
  await login(page);
  await page.locator('[data-tour="nav"]').getByRole("link", { name: "Чек-листы" }).click();
  const cards = page.getByTestId("checklist-card");
  await expect(cards).toHaveCount(4);

  // seed по плану ШАГ 10: 2 «допущен», 1 «требует внимания» (трещина), 1 «не допущен» (фара)
  const verdicts = await page.getByTestId("verdict").allTextContents();
  expect(verdicts.filter((v) => v.includes("НЕ ДОПУЩЕН"))).toHaveLength(1);
  expect(verdicts.filter((v) => v.includes("ТРЕБУЕТ ВНИМАНИЯ"))).toHaveLength(1);
  expect(verdicts.filter((v) => v.startsWith("✓ ДОПУЩЕН"))).toHaveLength(2);

  // теги ИИ на фото и расхождение анкеты с ИИ
  const lamp = cards.filter({ hasText: "Сапаров Д.Н." });
  await expect(lamp.getByText("левая фара не горит").first()).toBeVisible();
  await expect(lamp.getByText("✕ ИИ")).toHaveCount(2); // перёд и зад — обе плитки «фары»
  await expect(lamp.getByText(/Г3 · Передние фары/)).toBeVisible();
  const crack = cards.filter({ hasText: "Абилов Е.Т." });
  await expect(crack.getByText(/Е4: водитель ответил «да», ИИ видит неисправность/)).toBeVisible();
  await expect(crack.getByText("⚠ ИИ")).toHaveCount(1); // только правый борт

  // действия: устранение, согласование, согласование с отметкой
  await lamp.getByRole("button", { name: "Отправить на устранение" }).click();
  await expect(page.getByRole("status").filter({ hasText: "Заявка на устранение создана" })).toBeVisible();
  await expect(lamp.getByText("На устранении")).toBeVisible();

  const ok = cards.filter({ hasText: "Иванов А.С." });
  await ok.getByRole("button", { name: "Согласовать выезд" }).click();
  await expect(ok.getByText("Выезд согласован")).toBeVisible();

  await crack.getByRole("button", { name: "Согласовать с отметкой" }).click();
  await crack.getByLabel("Отметка координатора").fill("Трещина вне зоны обзора, замена на ТО");
  await crack.getByRole("button", { name: "Подтвердить" }).click();
  await expect(crack.getByText("Согласован с отметкой")).toBeVisible();
  await expect(crack.getByText(/замена на ТО/)).toBeVisible();

  // фильтр по статусу
  await page.getByRole("tab", { name: "На устранении" }).click();
  await expect(cards).toHaveCount(1);
  await expect(cards.first()).toContainText("Сапаров Д.Н.");
  await page.getByRole("tab", { name: "Ожидают" }).click();
  await expect(cards).toHaveCount(1);
  await expect(cards.first()).toContainText("Петров Д.В.");
});

test("Настройки: вес события меняет Score в лидерборде, тема системная, устройства, пользователи", async ({
  page,
}) => {
  await login(page);
  await page.locator('[data-tour="nav"]').getByRole("link", { name: "Настройки" }).click();

  // Скоринг: предпросмотр без сохранения, затем сохранение
  const microsleep = page.getByLabel("Засыпание за рулём");
  await expect(microsleep).toHaveValue("15");
  await microsleep.fill("30");
  await page.getByRole("button", { name: "Предпросмотр пересчёта" }).click();
  const ivanovPreview = page.locator("tbody tr").filter({ hasText: "Иванов А.С." });
  await expect(ivanovPreview).toContainText("55");
  await expect(ivanovPreview).toContainText("▼");
  await page.getByRole("button", { name: "Сохранить" }).click();
  await expect(page.getByRole("status")).toContainText("Сохранено · версия 2");

  // «Готово, когда»: лидерборд пересчитан без перезагрузки backend
  await page.locator('[data-tour="nav"]').getByRole("link", { name: "Лидерборд" }).click();
  await expect(page.getByRole("heading", { name: "Лидерборд", level: 1 })).toBeVisible();
  await expect(page.getByLabel("Место 1")).toBeVisible();
  const ivanovRow = page.locator("tbody tr").filter({ hasText: "Иванов А.С." });
  await expect(ivanovRow).toBeVisible();
  const scoreText = await ivanovRow.locator("td").nth(3).locator("b").innerText();
  expect(Number(scoreText)).toBeLessThan(55);

  // Внешний вид: системная тема сохраняется, явный выбор возвращает тёмную
  await page.locator('[data-tour="nav"]').getByRole("link", { name: "Настройки" }).click();
  await page.getByRole("tab", { name: "Внешний вид" }).click();
  await page.getByRole("radio", { name: "Системная" }).check();
  await expect.poll(() => page.evaluate(() => localStorage.getItem("theme"))).toBe("system");
  await page.getByRole("radio", { name: "Тёмная" }).check();
  await expect(page.locator("html")).toHaveClass(/dark/);

  // Устройства: команда перезагрузки
  await page.getByRole("tab", { name: "Устройства", exact: true }).click();
  await page.getByRole("button", { name: "Перезагрузить DG-0001" }).click();
  await expect(page.getByRole("status")).toContainText("Перезагрузка запрошена: DG-0001");
  await expect(page.locator("tbody tr").filter({ hasText: "DG-0001" })).toContainText("Перезагрузка запрошена");

  // Пользователи: добавление наблюдателя
  await page.getByRole("tab", { name: "Пользователи" }).click();
  const userForm = page.locator("form"); // единственная форма на странице; в таблице — свои селекты ролей
  await userForm.getByLabel("Имя").fill("Тестова Т.Т.");
  await userForm.getByLabel("Email").fill("viewer.test@driverguard.kz");
  await userForm.locator("select").selectOption("viewer"); // «Роль» подстрочно совпадает с «Пароль»
  await userForm.getByLabel("Пароль").fill("viewer123");
  await userForm.getByRole("button", { name: "Добавить пользователя" }).click();
  await expect(page.getByRole("status")).toContainText("Пользователь добавлен: Тестова Т.Т.");
  await expect(page.locator("tbody tr").filter({ hasText: "Тестова Т.Т." })).toBeVisible();
});

test("Обзор: назначение обучения показывает toast", async ({ page }) => {
  await login(page);
  await page.getByRole("button", { name: "Назначить обучение" }).first().click();
  await expect(page.getByRole("status")).toContainText("Микрообучение");
  await expect(page.getByRole("status")).toContainText("Иванов А.С.");
});

test("витрина /design-system показывает обе темы", async ({ page }) => {
  const errors = collectConsoleErrors(page);
  await login(page);
  await page.goto("/design-system");
  await expect(page.getByRole("heading", { name: "Светлая тема" })).toBeVisible();
  await expect(page.getByRole("heading", { name: "Тёмная тема" })).toBeVisible();
  await page.screenshot({ path: `${SHOTS}/панель_design-system.png`, fullPage: true });
  expect(errors).toEqual([]);
});
