import { t } from "@/lib/i18n";
/* API-клиент: fetch к backend с Bearer-токеном.
   В localStorage — только токен (правило CLAUDE.md); имя/роль берём из JWT-claims. */

/** PWA водителя живёт под /driver и /driver/*; раздел панели /drivers — НЕ она. */
export function isDriverPath(path: string | null | undefined): boolean {
  return path === "/driver" || Boolean(path?.startsWith("/driver/"));
}

export const API_URL =
  process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000/api/v1";
export const WS_URL =
  process.env.NEXT_PUBLIC_WS_URL ?? "ws://localhost:8000/ws/live";

/* Панель (/…) и PWA (/driver/…) хранят токены под разными ключами: координатор и водитель
   могут быть залогинены в одном браузере одновременно (демо с одного ноутбука). */
export function isDriverArea(): boolean {
  return typeof window !== "undefined" && isDriverPath(window.location.pathname);
}
function tokenKey(): string {
  return isDriverArea() ? "dg-token-driver" : "dg-token";
}
function refreshKey(): string {
  return isDriverArea() ? "dg-refresh-driver" : "dg-refresh";
}

function read(key: string): string | null {
  if (typeof window === "undefined") return null;
  try {
    return localStorage.getItem(key);
  } catch {
    return null;
  }
}

export function getToken(): string | null {
  return read(tokenKey());
}

export function setTokens(access: string | null, refresh?: string | null) {
  try {
    if (access) localStorage.setItem(tokenKey(), access);
    else localStorage.removeItem(tokenKey());
    if (refresh !== undefined) {
      if (refresh) localStorage.setItem(refreshKey(), refresh);
      else localStorage.removeItem(refreshKey());
    }
  } catch {
    /* приватный режим — работаем без сохранения */
  }
}

export interface JwtUser {
  id: number;
  name: string;
  role: string;
}

/** Имя и роль — из payload access-токена (claims name/role кладёт backend). */
export function currentUser(): JwtUser | null {
  const token = getToken();
  if (!token) return null;
  try {
    const payload = JSON.parse(
      new TextDecoder().decode(
        Uint8Array.from(
          atob(token.split(".")[1].replace(/-/g, "+").replace(/_/g, "/")),
          (c) => c.charCodeAt(0),
        ),
      ),
    );
    return { id: Number(payload.sub), name: payload.name ?? "", role: payload.role ?? "" };
  } catch {
    return null;
  }
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

/** Текст ошибки backend: строка detail или список ошибок валидации pydantic (422). */
async function errorDetail(resp: Response): Promise<string> {
  let detail = t("Ошибка {0}", resp.status);
  try {
    const body = await resp.json();
    if (typeof body.detail === "string") detail = body.detail;
    else if (Array.isArray(body.detail)) {
      detail = body.detail
        .map((d: { loc?: (string | number)[]; msg?: string }) => {
          const field = (d.loc ?? []).filter((x) => x !== "body").join(".");
          return field ? `${field}: ${d.msg ?? ""}` : (d.msg ?? "");
        })
        .join("; ");
    }
  } catch {
    /* тело не JSON — оставляем код */
  }
  return detail;
}

function toLogin() {
  setTokens(null, null);
  if (typeof window === "undefined") return;
  const path = window.location.pathname;
  // PWA водителя живёт под /driver — у неё свой экран входа (телефон + PIN)
  const target = isDriverPath(path) ? "/driver/login" : "/login";
  if (!path.startsWith(target)) window.location.href = target;
}

/** Результат обновления токена: ok — новый access; invalid — refresh отвергнут (нужен вход);
   transient — сеть/5xx/429: токены оставляем, попробуем позже. */
export type RefreshResult = "ok" | "invalid" | "transient";

let refreshInFlight: Promise<RefreshResult> | null = null;

/** Просроченный access-токен обновляем refresh-токеном (общий путь для HTTP и WS).
   Один запрос на всех: параллельные 401 (профиль, heartbeat, очередь событий, WS) ждут
   общий промис, а не устраивают шторм /auth/refresh. */
export function refreshTokensDetailed(): Promise<RefreshResult> {
  if (refreshInFlight) return refreshInFlight;
  refreshInFlight = (async (): Promise<RefreshResult> => {
    const key = refreshKey();
    const refresh = read(key);
    try {
      if (!refresh) return "invalid";
      const resp = await fetch(`${API_URL}/auth/refresh`, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ refresh_token: refresh }),
        signal: AbortSignal.timeout(15_000),
      });
      if (refreshKey() !== key || read(key) !== refresh) return "transient";
      if (resp.status === 401 || resp.status === 403) return "invalid";
      if (!resp.ok) return "transient";
      const data = await resp.json();
      if (refreshKey() !== key || read(key) !== refresh) return "transient";
      setTokens(data.access_token, data.refresh_token ?? undefined);
      return "ok";
    } catch {
      return "transient";
    } finally {
      // следующий 401 после завершения — новый запрос
      setTimeout(() => {
        refreshInFlight = null;
      }, 0);
    }
  })();
  return refreshInFlight;
}

export async function refreshTokens(): Promise<boolean> {
  return (await refreshTokensDetailed()) === "ok";
}

export async function api<T>(path: string, init?: RequestInit, retried = false, expectedUserId?: number): Promise<T> {
  const assertOwner = () => {
    if (expectedUserId !== undefined && (currentUser()?.id !== expectedUserId || currentUser()?.role !== "driver")) {
      throw new ApiError(409, "Учётная запись изменилась. События сохранены для прежнего водителя.");
    }
  };
  assertOwner();
  // new Headers(...) корректно принимает все формы HeadersInit (объект/Headers/массив)
  const headers = new Headers(init?.headers);
  // multipart (чек-лист с фото): boundary выставляет браузер, Content-Type руками не ставим
  if (!headers.has("Content-Type") && !(init?.body instanceof FormData)) {
    headers.set("Content-Type", "application/json");
  }
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const resp = await fetch(`${API_URL}${path}`, { ...init, headers });

  if (resp.status === 401) {
    assertOwner();
    const outcome = retried ? "invalid" : await refreshTokensDetailed();
    assertOwner();
    if (outcome === "ok") return api<T>(path, init, true, expectedUserId);
    // Временный сбой обновления (туннель/сеть/429) — не разлогиниваем посреди показа,
    // запрос просто не удался; на экран входа — только если refresh-токен отвергнут
    if (outcome === "invalid") toLogin();
  }
  if (!resp.ok) {
    throw new ApiError(resp.status, await errorDetail(resp));
  }
  return resp.json() as Promise<T>;
}

/** Скачивание файла с авторизацией (CSV/PDF отчётов): имя — из Content-Disposition. */
export async function apiBlob(
  path: string,
  retried = false,
): Promise<{ blob: Blob; filename: string }> {
  const headers = new Headers();
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const resp = await fetch(`${API_URL}${path}`, { headers });
  if (resp.status === 401) {
    const outcome = retried ? "invalid" : await refreshTokensDetailed();
    if (outcome === "ok") return apiBlob(path, true);
    if (outcome === "invalid") toLogin();
  }
  if (!resp.ok) {
    throw new ApiError(resp.status, await errorDetail(resp));
  }
  const disposition = resp.headers.get("Content-Disposition") ?? "";
  const utf8 = /filename\*=UTF-8''([^;]+)/i.exec(disposition);
  const plain = /filename=([^;]+)/i.exec(disposition);
  const filename = utf8 ? decodeURIComponent(utf8[1]) : (plain?.[1] ?? "download").trim();
  return { blob: await resp.blob(), filename };
}

/** Сохранить Blob как файл через временную ссылку. */
export function saveBlob(blob: Blob, filename: string) {
  const a = document.createElement("a");
  a.href = URL.createObjectURL(blob);
  a.download = filename;
  a.click();
  // Отзываем URL после старта загрузки: синхронный revoke ломает скачивание в Firefox/Safari
  setTimeout(() => URL.revokeObjectURL(a.href), 1000);
}

/* ── Типы ответов backend (docs/api.md; истина — OpenAPI /docs) ── */

export interface SummaryOut {
  period: string;
  vehicles: { online: number; total: number };
  events: { value: number; prev: number; delta: number };
  critical_24h: { value: number };
  avg_score: { value: number; prev: number; delta: number; target: number; zone: string };
  km_week: { value: number; delta_pct: number };
  uptime: { value: number; active: number; total: number };
  badges: { new_events: number };
}

export type Period = "today" | "7d" | "30d";

/** Actual samples recorded on the device. Missing fields are not zero readings. */
export interface EventMeasurements {
  rule_version?: string | null;
  closed_ms?: number | null;
  ear?: number | null;
  ear_baseline?: number | null;
  blink_count_60s?: number | null;
  perclos_pct?: number | null;
  valid_observation_ms?: number | null;
  coverage_pct?: number | null;
  yawns_10min?: number | null;
  jaw_open_ms?: number | null;
  head_delta?: number | null;
  yaw_delta?: number | null;
  away_ms?: number | null;
  missing_ms?: number | null;
  speed_limit_kmh?: number | null;
  sample_latency_ms?: number | null;
}

export interface EventItem {
  uuid: string;
  type: string;
  severity: "critical" | "warning" | "info";
  confidence: number;
  ts: string;
  lat: number | null;
  lon: number | null;
  gps_valid: boolean;
  speed_kmh: number | null;
  value: number | null;
  clip_key: string | null;
  status: "new" | "confirmed" | "false_positive";
  is_demo: boolean;
  driver_id: number | null;
  driver_name: string | null;
  vehicle_plate: string | null;
  driver_phone: string | null;
  context?: Record<string, unknown> | null; // причина SOS, источник (pwa_camera)
  measurements?: EventMeasurements | null;
}

export interface DayPoint {
  date: string;
  critical: number;
  warning: number;
  info: number;
}

export interface TypeShare {
  type: string;
  count: number;
  share_pct: number;
}

export interface RedZoneRow {
  driver_id: number;
  name: string;
  score: number;
  trips_30d: number;
}

export type ScoreZone = "ok" | "warn" | "danger";

export interface LeaderRow {
  rank: number;
  driver_id: number;
  name: string;
  depot: string;
  score: number;
  zone: ScoreZone;
  delta: number;
  streak: number;
  is_new?: boolean;
  km: number;
  events: number;
  badges: string[];
}

export interface LeaderboardOut {
  period_days: number;
  rows: LeaderRow[];
  depots: { name: string; avg_score: number; zone: ScoreZone; drivers: number }[];
}

export interface DriverOut {
  id: number;
  name: string;
  depot_id: number | null;
  phone: string | null;
  depot_name: string | null;
  vehicle_plate: string | null;
  vehicle_id: number | null;
  photo_url: string | null;
}

export interface VehicleOut {
  id: number;
  plate: string;
  model: string;
  depot_id: number | null;
  driver_id: number | null;
}

export interface DepotOut {
  id: number;
  name: string;
}

/* Ответ GET /drivers/{id}/profile (BE-9) */
export interface DriverProfileOut {
  driver: {
    id: number;
    name: string;
    photo_url?: string | null;
    phone: string | null;
    depot: string | null;
    depot_id?: number | null;
    vehicle: { id?: number; plate: string; model: string } | null;
  };
  score: { value: number; zone: ScoreZone; streak: number; is_new?: boolean };
  score_by_week: { weeks_ago: number; score: number }[];
  breakdown_30d: { type: string; count: number }[];
  recent_events: EventItem[];
  trips: {
    id: number;
    started_at: string;
    ended_at: string | null;
    distance_km: number;
    status: "active" | "finished";
  }[];
  trainings: { id: number; title: string; status: string; assigned_at: string }[];
}

/* Чек-листы (BE-10, WEB-7) — ответы GET /checklists, /checklists/{id}, POST approve */
export type ChecklistVerdict = "допущен" | "требует_внимания" | "не_допущен";
export type ChecklistStatus = "pending" | "approved" | "approved_with_note" | "sent_to_repair";
export type AiTag = "ok" | "warn" | "fail" | "not_visible" | "none";

export interface ChecklistPhoto {
  slot: string;
  label: string;
  key: string | null;
  url: string | null;
  ai: AiTag;
}

export interface ChecklistAiItem {
  key: string;
  title: string;
  critical: boolean;
  status: AiTag;
  confidence: number;
  comment: string;
}

export interface ChecklistOut {
  id: number;
  driver_id: number;
  driver_name: string | null;
  vehicle_plate: string | null;
  vehicle_model: string | null;
  created_at: string;
  verdict: ChecklistVerdict;
  status: ChecklistStatus;
  note: string | null;
  reviewed_at: string | null;
  reviewed_by_name: string | null;
  photos: ChecklistPhoto[];
  ai_items: ChecklistAiItem[];
  body_damage: { описание: string; зона: string }[];
  ai_meta: {
    provider?: string;
    host?: string;
    model?: string | null;
    latency_ms?: number;
    attempts?: number;
    tokens?: number | null;
    model_verdict?: string;
    error?: string;
  };
  answers: Record<string, string> | null;
  answered: number;
  answer_issues: { id: string; text: string; criticality: string | null }[];
  discrepancies: string[];
}

export interface ChecklistListOut {
  items: ChecklistOut[];
  total: number;
  page: number;
  page_size: number;
}

/* Отчёты (BE-14) — GET /reports/summary */
export interface ReportSummary {
  period: Period;
  depot: string | null;
  generated_at: string;
  totals: {
    events: number;
    critical: number;
    warning: number;
    km: number;
    trips: number;
    avg_score: number;
    avg_zone: ScoreZone;
    drivers: number;
  };
  by_type: TypeShare[];
  by_driver: {
    driver_id: number;
    name: string;
    depot: string | null;
    vehicle_plate: string | null;
    events: number;
    critical: number;
    score: number;
    zone: ScoreZone;
    km: number;
  }[];
  score_trend: { weeks_ago: number; avg_score: number | null }[]; // null — неделя без событий
  risky_segments: { lat: number; lon: number; events: number; critical: number; top_type: string }[];
  trips: {
    id: number;
    driver_id: number;
    driver_name: string;
    vehicle_plate: string;
    started_at: string;
    ended_at: string | null;
    km: number;
    events: number;
    status: "active" | "finished";
  }[];
}

/* PWA водителя (APP-1…APP-6) — GET /drivers/me, POST /drivers/{id}/sos, /trainings */
export type SosReason = "Поломка" | "ДТП" | "Здоровье" | "Другое";
export type BreakReason = "устал" | "туалет" | "еда" | "заправка";

export interface DriverMe extends DriverProfileOut {
  driver: DriverProfileOut["driver"] & {
    vehicle: { id: number; plate: string; model: string } | null;
  };
  trainings: {
    id: number;
    training_id: number;
    title: string;
    duration_s: number;
    status: string;
    assigned_at: string;
  }[];
  device: {
    id: number;
    serial: string;
    status: string;
    online: boolean;
    last_seen: string | null;
  } | null;
  active_trip: {
    id: number;
    vehicle_id: number;
    started_at: string;
    distance_km: number;
    break: { id: number; reason: string; started_at: string } | null;
    last_break_end: string | null;
  } | null;
  last_checklist: {
    id: number;
    created_at: string;
    verdict: ChecklistVerdict;
    status: ChecklistStatus;
  } | null;
  retention: RetentionSettingsValue;
}

export interface ChecklistItemCatalog {
  id: string;
  section: string;
  section_title: string;
  text: string;
  base: boolean;
  criticality: string | null;
  method: "auto" | "answer" | "photo_ai" | "input";
  ai_key: string | null;
  na_allowed: boolean;
  enabled?: boolean;
  custom?: boolean;
  default_text?: string | null;
  default_base?: boolean | null;
  default_criticality?: string | null;
}

export interface ChecklistSlot {
  slot: string;
  label: string;
  hint: string;
  enabled?: boolean;
  custom?: boolean;
}

export interface AiStatusOut {
  provider: "mock" | "openai_compat" | "gemini" | string;
  configured: boolean;
  model: string | null;
  host: string | null;
  hint: string | null;
}

export interface AiTestOut {
  ok: boolean;
  provider?: string;
  model?: string | null;
  latency_ms: number;
  verdict?: string;
  demo?: boolean;
  error?: string;
}

export interface ChecklistTemplateOut {
  slots: ChecklistSlot[];
  items: ChecklistItemCatalog[];
  version: number;
}

/** Настройки → Чек-лист: компактный формат правок поверх каталога (PUT /settings/checklist) */
export interface ChecklistSettingsValue {
  hidden_slots: string[];
  custom_slots: { slot: string; label: string; hint: string }[];
  hidden_items: string[];
  item_overrides: Record<string, { text?: string | null; base?: boolean | null; criticality?: "critical" | "attention" | "none" | null }>;
  custom_items: { id: string; text: string; base: boolean; criticality: "critical" | "attention" | null; na_allowed: boolean }[];
}

export interface TrainingOut {
  id: number;
  title: string;
  duration_s: number;
  url: string | null;
}

/* Настройки (BE-15) — GET/PUT /settings/{key} */
export interface ScoringSettingsValue {
  weights: Record<string, number>;
  modifiers: { fast_kmh: number; fast_mult: number; slow_kmh: number; slow_mult: number };
}
export interface ThresholdSettingsValue {
  MICROSLEEP_MS: number;
  PERCLOS_WARN: number;
  YAWN_MS: number;
  NOD_MS: number;
  NOFACE_MS: number;
  speed_limit_highway: number;
  speed_limit_city: number;
}
export interface NotificationSettingsValue {
  telegram_chat_id: string;
  critical_types: string[];
}
export interface RetentionSettingsValue {
  events_months: number;
  clips_days: number;
  photos_days: number;
  audit_years: number;
}
export interface SettingOut<T = Record<string, unknown>> {
  key: string;
  value: T;
  version: number;
  updated_at: string | null;
  updated_by_name: string | null;
}
export interface ScoringPreviewRow {
  driver_id: number;
  name: string;
  score_now: number;
  score_new: number;
  delta: number;
}
export interface UserRow {
  id: number;
  name: string;
  role: "admin" | "coordinator" | "viewer" | "driver";
  email: string | null;
  phone: string | null;
  created_at: string | null;
  last_seen: string | null;
  online: boolean;
}
export interface DeviceRow {
  id: number;
  serial: string;
  vehicle_id: number | null;
  fw_version: string | null;
  model_version: string | null;
  last_seen: string | null;
  status: string;
  online: boolean;
  vehicle_plate: string | null;
}
