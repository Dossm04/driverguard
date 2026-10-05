"use client";

/* Ряд из 6 KPI-карточек по Figma; данные /dashboard/summary, реагирует на период. */

import { Activity, CircleX, Route, TriangleAlert, Truck, Wifi } from "lucide-react";

import { QueryError } from "@/components/ui/query-error";
import { t, localeTag, perLang } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";
import { useSummary } from "@/lib/queries";
import { KpiCard } from "@/components/ui/kpi-card";
import { Skeleton } from "@/components/ui/skeleton";
import type { Period } from "@/lib/api";

const EVENT_TITLES: Record<Period, string> = perLang(() => ({
  today: t("Событий сегодня"),
  "7d": t("Событий за 7 дней"),
  "30d": t("Событий за 30 дней"),
}));
const EVENT_SUBS: Record<Period, string> = perLang(() => ({
  today: t("vs. вчера"),
  "7d": t("vs. прошлые 7 дней"),
  "30d": t("vs. прошлые 30 дней"),
}));

export function KpiRow({ period }: { period: Period }) {
  useLangVersion();
  const { data: s, isLoading, isError, error, refetch } = useSummary(period);

  if (isError) {
    return <QueryError error={error} onRetry={() => refetch()} />;
  }

  if (isLoading || !s) {
    return (
      <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
        {Array.from({ length: 6 }, (_, i) => (
          <Skeleton key={i} className="h-[118px] rounded-card" />
        ))}
      </div>
    );
  }

  const offline = s.vehicles.total - s.vehicles.online;
  // Зону считает backend (одни пороги для Обзора, Лидерборда, Отчётов и карты)
  const scorePill =
    s.avg_score.zone === "danger"
      ? { label: t("Критично"), tone: "danger" as const }
      : s.avg_score.zone === "warn"
        ? { label: t("Внимание"), tone: "warn" as const }
        : { label: t("Норма"), tone: "ok" as const };

  return (
    <div className="grid grid-cols-2 gap-3 lg:grid-cols-3 xl:grid-cols-6">
      <KpiCard
        title={t("Машин на линии")}
        icon={Truck}
        iconTone="accent"
        value={
          <>
            {s.vehicles.online}
            <span className="text-lg text-mut">/{s.vehicles.total}</span>
          </>
        }
        sub={offline > 0 ? t("{0} офлайн", offline) : t("все на связи")}
        pill={
          offline > 0
            ? { label: t("Внимание"), tone: "warn" }
            : { label: t("Норма"), tone: "ok" }
        }
      />
      <KpiCard
        title={EVENT_TITLES[period]}
        icon={TriangleAlert}
        iconTone="warn"
        value={s.events.value}
        trend={
          s.events.delta !== 0
            ? {
                value: `${s.events.delta > 0 ? "+" : "−"}${Math.abs(s.events.delta)}`,
                tone: s.events.delta > 0 ? "warn" : "ok",
              }
            : undefined
        }
        sub={`${EVENT_SUBS[period]} ${s.events.prev}`}
        pill={
          s.events.value > 0
            ? { label: t("Внимание"), tone: "warn" }
            : { label: t("Норма"), tone: "ok" }
        }
      />
      <KpiCard
        title={t("Критических за 24ч")}
        icon={CircleX}
        iconTone="danger"
        value={s.critical_24h.value}
        sub={s.critical_24h.value > 0 ? t("требуют реакции") : t("нет за сутки")}
        pill={
          s.critical_24h.value > 0
            ? { label: t("Критично"), tone: "danger" }
            : { label: t("Норма"), tone: "ok" }
        }
      />
      <KpiCard
        title={t("Средний Score парка")}
        icon={Activity}
        iconTone="ok"
        value={s.avg_score.value}
        trend={
          s.avg_score.delta !== 0
            ? {
                value: `${s.avg_score.delta > 0 ? "+" : "−"}${Math.abs(s.avg_score.delta)}`,
                tone: s.avg_score.delta > 0 ? "ok" : "danger",
              }
            : undefined
        }
        sub={t("цель: ≥{0}", s.avg_score.target)}
        pill={scorePill}
      />
      <KpiCard
        title={t("Пробег за неделю")}
        icon={Route}
        iconTone="accent"
        value={s.km_week.value.toLocaleString(localeTag())}
        trend={
          s.km_week.delta_pct !== 0
            ? {
                value: `${s.km_week.delta_pct > 0 ? "+" : "−"}${Math.abs(s.km_week.delta_pct)}%`,
                tone: s.km_week.delta_pct >= 0 ? "ok" : "warn",
              }
            : undefined
        }
        sub={t("км")}
        pill={{ label: t("Норма"), tone: "ok" }}
      />
      <KpiCard
        title={t("Аптайм устройств")}
        icon={Wifi}
        iconTone="ok"
        value={`${s.uptime.value}%`}
        sub={t("{0} из {1} активны", s.uptime.active, s.uptime.total)}
        pill={
          s.uptime.value >= 95
            ? { label: t("Норма"), tone: "ok" }
            : { label: t("Внимание"), tone: "warn" }
        }
      />
    </div>
  );
}
