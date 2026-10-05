import { localeTag } from "@/lib/i18n";
/* Время парка: панель считает «сегодня» и показывает часы по поясу автопарка (Asia/Almaty,
   как APP_TZ на backend), а не по поясу браузера — координатор в другом городе видит те же
   цифры, что и backend. Казахстан без перевода часов, но смещение всё равно берём из Intl. */

export const FLEET_TZ = process.env.NEXT_PUBLIC_FLEET_TZ ?? "Asia/Almaty";

function tzOffsetMinutes(date: Date, tz: string): number {
  const parts = new Intl.DateTimeFormat("en-US", {
    timeZone: tz,
    hour12: false,
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    second: "2-digit",
  }).formatToParts(date);
  const get = (t: Intl.DateTimeFormatPartTypes) => Number(parts.find((p) => p.type === t)?.value ?? 0);
  const asUtc = Date.UTC(get("year"), get("month") - 1, get("day"), get("hour") % 24, get("minute"), get("second"));
  return Math.round((asUtc - date.getTime()) / 60_000);
}

/** Календарная дата в поясе парка (YYYY-MM-DD). */
export function fleetDate(date: Date = new Date()): string {
  return new Intl.DateTimeFormat("en-CA", { timeZone: FLEET_TZ }).format(date);
}

/** Полночь дня парка (daysAgo дней назад) как момент UTC. */
export function fleetDayStart(now: Date = new Date(), daysAgo = 0): Date {
  const off = tzOffsetMinutes(now, FLEET_TZ);
  const local = new Date(now.getTime() + off * 60_000);
  const startLocal = Date.UTC(local.getUTCFullYear(), local.getUTCMonth(), local.getUTCDate() - daysAgo);
  return new Date(startLocal - off * 60_000);
}

export function fleetTime(ts: string | Date, withSeconds = false): string {
  return new Date(ts).toLocaleTimeString(localeTag(), {
    timeZone: FLEET_TZ,
    hour: "2-digit",
    minute: "2-digit",
    ...(withSeconds ? { second: "2-digit" } : {}),
  });
}

export function fleetDayMonth(ts: string | Date): string {
  return new Date(ts).toLocaleDateString(localeTag(), { timeZone: FLEET_TZ, day: "2-digit", month: "2-digit" });
}
