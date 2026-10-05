/* Перед прогоном e2e демо-база приводится к эталонному seed (цифры Figma, 6 водителей):
   тесты создают водителя и назначают обучения, повторный прогон без seed не сошёлся бы.
   Пропустить: E2E_SKIP_SEED=1 (например, если seed уже сделан вручную). */

import { spawnSync } from "node:child_process";
import { existsSync } from "node:fs";
import path from "node:path";

/* Прогрев dev-сервера: Next компилирует маршруты при первом запросе (5–10 с на холодном
   старте), из-за чего первый тест ловил таймаут на переходе после логина. Ошибки прогрева
   не роняют прогон — тесты сами покажут, что не так. */
const WARM_ROUTES = [
  "/login",
  "/",
  "/live",
  "/events",
  "/leaderboard",
  "/drivers",
  "/checklists",
  "/reports",
  "/settings",
  "/design-system",
  "/driver/login",
  "/driver",
  "/driver/checklist",
  "/driver/camera",
];

async function warmUp(baseURL: string) {
  const started = Date.now();
  await Promise.all(
    WARM_ROUTES.map(async (route) => {
      try {
        await fetch(baseURL + route, { signal: AbortSignal.timeout(60_000) });
      } catch {
        /* не критично */
      }
    }),
  );
  console.log(`[e2e] прогрев ${WARM_ROUTES.length} маршрутов: ${Date.now() - started} мс`);
}

export default async function globalSetup() {
  const baseURL = process.env.E2E_BASE_URL ?? "http://localhost:3000";
  await warmUp(baseURL);
  if (process.env.E2E_SKIP_SEED) return;
  // Seed стирает базу (TRUNCATE): на демо-ноутбуке это удалит учётки жюри и их события.
  // Прогон против не-localhost адреса требует явного E2E_ALLOW_SEED=1.
  if (!/^https?:\/\/(localhost|127\.0\.0\.1)(:\d+)?/.test(baseURL) && !process.env.E2E_ALLOW_SEED) {
    throw new Error(
      `E2E_BASE_URL=${baseURL} — не localhost: seed перед e2e стёр бы живую базу. ` +
        "Задайте E2E_SKIP_SEED=1 (без seed) или E2E_ALLOW_SEED=1 (осознанно пересеять).",
    );
  }
  const backend = path.resolve(__dirname, "../../backend");
  const venvPython = path.join(backend, process.platform === "win32" ? ".venv/Scripts/python.exe" : ".venv/bin/python");
  const python = process.env.E2E_PYTHON ?? (existsSync(venvPython) ? venvPython : process.platform === "win32" ? "python" : "python3");
  // seed не выписывает токены — слабый/отсутствующий JWT_SECRET в окружении e2e не помеха
  const res = spawnSync(python, ["-m", "app.seed"], {
    cwd: backend,
    encoding: "utf-8",
    env: { ...process.env, DG_ALLOW_WEAK_SECRET: "1" },
  });
  if (res.status !== 0) {
    throw new Error(
      `Seed перед e2e не удался (${python} -m app.seed, cwd ${backend}):\n` +
        `${res.stderr || res.stdout || res.error}\nПропустить seed: E2E_SKIP_SEED=1`,
    );
  }
  const lastLine = (res.stdout || "").trim().split("\n").pop();
  console.log(`[e2e] ${lastLine}`);
}
