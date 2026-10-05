const path = require('path');
const { chromium } = require(require.resolve('@playwright/test', { paths: [process.cwd(), path.join(__dirname, '..', '..', 'web')] }));
require('fs').mkdirSync(require('path').resolve(__dirname, '..', 'screens', 'demo'), { recursive: true });
const OUT = require('path').resolve(__dirname, '..', 'screens', 'demo');
const BASE = 'http://localhost:3000';
const sleep = (ms) => new Promise((r) => setTimeout(r, ms));

async function shot(page, name, ms = 1800) {
  await sleep(ms);
  await page.screenshot({ path: `${OUT}/${name}.png`, fullPage: false });
  console.log('shot', name);
}

(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  // ── панель, тёмная тема ──
  const ctx = await browser.newContext({ viewport: { width: 1440, height: 900 }, locale: 'ru-RU', colorScheme: 'dark' });
  await ctx.addInitScript(() => { try { localStorage.setItem('dg-tour-v1', 'done'); } catch (e) {} });
  const page = await ctx.newPage();
  await page.goto(`${BASE}/login`);
  await shot(page, 'login', 1200);
  await page.fill('input[type=email]', 'admin@driverguard.kz');
  await page.fill('input[type=password]', 'admin123');
  await page.click('button[type=submit]');
  await page.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 20000 });
  await page.evaluate(() => localStorage.setItem('dg-tour-v1', 'done'));
  await page.goto(`${BASE}/`);
  await page.getByText('Средний Score парка').first().waitFor({ timeout: 20000 });
  // закрыть мини-тур, если он показался
  for (const t of ['Пропустить', 'Закрыть', 'Понятно']) {
    const b = page.getByRole('button', { name: t });
    if (await b.count()) { await b.first().click().catch(() => {}); }
  }
  await shot(page, 'overview', 2500);
  await page.goto(`${BASE}/live-map`);
  await shot(page, 'map', 4000);
  await page.goto(`${BASE}/events`);
  await page.getByText('Экспорт CSV').first().waitFor({ timeout: 20000 });
  await shot(page, 'events', 2000);
  const row = page.locator('table tbody tr').first();
  if (await row.count()) {
    await row.click().catch(() => {});
    await shot(page, 'events_modal', 2000);
    await page.keyboard.press('Escape');
  }
  await page.goto(`${BASE}/leaderboard`);
  await shot(page, 'leaderboard', 2500);
  await page.goto(`${BASE}/drivers`);
  await shot(page, 'drivers', 2500);
  const card = page.locator('[data-testid="driver-card"]').first();
  if (await card.count()) {
    await card.click();
    await page.waitForURL(/\/drivers\/\d+/, { timeout: 15000 });
    await shot(page, 'driver_profile', 3000);
  }
  await page.goto(`${BASE}/checklists`);
  await shot(page, 'checklists', 2500);
  const first = page.locator('[data-testid="checklist-row"], table tbody tr, [role="button"]').first();
  if (await first.count()) { await first.click().catch(() => {}); await shot(page, 'checklist_detail', 2000); }
  await page.goto(`${BASE}/reports`);
  await shot(page, 'reports', 3500);
  await page.goto(`${BASE}/settings`);
  await shot(page, 'settings_scoring', 2500);
  for (const [tab, name] of [['Пороги устройства', 'settings_thresholds'], ['Чек-лист', 'settings_checklist'], ['Уведомления', 'settings_notifications'], ['Устройства', 'settings_devices'], ['Пользователи', 'settings_users']]) {
    const b = page.getByRole('tab', { name: tab }).first(); // вкладки настроек, а не колокольчик «Уведомления» в топбаре
    if (await b.count()) { await b.click(); await shot(page, name, 1500); }
    else { const t = page.getByText(tab, { exact: true }).first(); if (await t.count()) { await t.click(); await shot(page, name, 1500); } }
  }
  // редактирование водителя
  await page.goto(`${BASE}/drivers`);
  const card2 = page.locator('[data-testid="driver-card"]').first();
  if (await card2.count()) {
    await card2.click();
    await page.waitForURL(/\/drivers\/\d+/, { timeout: 15000 });
    const edit = page.getByTestId('driver-edit');
    if (await edit.count()) { await edit.click(); await shot(page, 'driver_edit', 1500); await page.keyboard.press('Escape'); }
  }
  // языки — Обзор на казахском и английском
  for (const lang of ['kk', 'en']) {
    await page.evaluate((l) => localStorage.setItem('dg-lang', l), lang);
    await page.goto(`${BASE}/`);
    await shot(page, `overview_${lang}`, 3000);
  }
  await page.evaluate(() => localStorage.setItem('dg-lang', 'ru'));
  // светлая тема — Обзор
  await page.evaluate(() => localStorage.setItem('theme', 'light'));
  await page.goto(`${BASE}/`);
  await page.getByText('Средний Score парка').first().waitFor({ timeout: 20000 });
  await shot(page, 'overview_light', 2500);
  await page.evaluate(() => localStorage.setItem('theme', 'dark'));
  await ctx.close();

  // ── панель на телефоне (drawer) ──
  const mctx = await browser.newContext({ viewport: { width: 390, height: 844 }, locale: 'ru-RU', colorScheme: 'dark', isMobile: true, hasTouch: true });
  await mctx.addInitScript(() => { try { localStorage.setItem('dg-tour-v1', 'done'); } catch (e) {} });
  const mp = await mctx.newPage();
  await mp.goto(`${BASE}/login`);
  await mp.fill('input[type=email]', 'admin@driverguard.kz');
  await mp.fill('input[type=password]', 'admin123');
  await mp.click('button[type=submit]');
  await mp.waitForURL((u) => !u.pathname.startsWith('/login'), { timeout: 20000 });
  await mp.evaluate(() => localStorage.setItem('dg-tour-v1', 'done'));
  await mp.goto(`${BASE}/`);
  await shot(mp, 'overview_mobile', 3000);
  await mctx.close();

  // ── PWA водителя ──
  const pctx = await browser.newContext({ viewport: { width: 390, height: 844 }, locale: 'ru-RU', colorScheme: 'dark', isMobile: true, hasTouch: true, geolocation: { latitude: 51.1, longitude: 71.4 }, permissions: ['geolocation'] });
  const pp = await pctx.newPage();
  await pp.goto(`${BASE}/driver/login`);
  await shot(pp, 'pwa_login', 1500);
  await pp.fill('input[type=tel]', '+77012441832');
  await pp.fill('input[type=password]', '1234');
  await pp.click('button[type=submit]');
  await pp.waitForURL((u) => u.pathname === '/driver' || u.pathname === '/driver/', { timeout: 20000 });
  await shot(pp, 'pwa_shift', 3000);
  for (const [path, name] of [['/driver/checklist', 'pwa_checklist'], ['/driver/camera', 'pwa_camera'], ['/driver/score', 'pwa_score'], ['/driver/sos', 'pwa_sos'], ['/driver/learn', 'pwa_learn']]) {
    await pp.goto(`${BASE}${path}`);
    await shot(pp, name, 3000);
  }
  await pp.evaluate(() => localStorage.setItem('dg-lang-driver', 'kk'));
  await pp.goto(`${BASE}/driver`);
  await shot(pp, 'pwa_shift_kk', 3000);
  await pp.evaluate(() => localStorage.setItem('dg-lang-driver', 'ru'));
  await pctx.close();
  await browser.close();
})().catch((e) => { console.error(e); process.exit(1); });
