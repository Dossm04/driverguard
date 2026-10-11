import type { EventMeasurements } from "@/lib/api";
import { t } from "@/lib/i18n";

/** Only observed values are shown; zero is a real sample, null is unavailable. */
export function measurementRows(measurements: EventMeasurements | null | undefined) {
  if (!measurements) return [];
  const definitions: [keyof EventMeasurements, string, (value: number) => string][] = [
    ["closed_ms", "Глаза закрыты", seconds],
    ["ear", "Раскрытие глаз (EAR)", ratio],
    ["ear_baseline", "Личная база EAR", ratio],
    ["blink_count_60s", "Моргания за 60 секунд", count],
    ["perclos_pct", "Доля закрытых глаз (PERCLOS)", percent],
    ["valid_observation_ms", "Время достоверного наблюдения", seconds],
    ["coverage_pct", "Покрытие окна наблюдения", percent],
    ["yawns_10min", "Возможные зевки за 10 минут", count],
    ["jaw_open_ms", "Рот открыт", seconds],
    ["head_delta", "Относительный наклон головы", ratio],
    ["yaw_delta", "Относительный поворот головы", ratio],
    ["away_ms", "Голова повёрнута", seconds],
    ["missing_ms", "Лицо не видно", seconds],
    ["speed_limit_kmh", "Выбранный лимит скорости", speed],
    ["sample_latency_ms", "Задержка обработки кадра", milliseconds],
  ];
  return definitions.flatMap(([key, label, format]) => {
    const value = measurements[key];
    return typeof value === "number" && Number.isFinite(value)
      ? [{ key, label: t(label), value: format(value) }]
      : [];
  });
}

function seconds(value: number) { return t("{0} с", (value / 1000).toFixed(1)); }
function ratio(value: number) { return value.toFixed(3); }
function count(value: number) { return String(value); }
function percent(value: number) { return `${value.toFixed(1)}%`; }
function speed(value: number) { return t("{0} км/ч", value.toFixed(1)); }
function milliseconds(value: number) { return t("{0} мс", value); }
