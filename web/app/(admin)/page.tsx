"use client";

/* Страница «Обзор» (ШАГ 5, WEB-2): композиция по Figma — 6 KPI, два графика,
   «Последние критические» и «Водители в красной зоне». Период — из топбара. */

import { CriticalLatest } from "@/components/overview/critical-latest";
import { EventsByDayChart } from "@/components/overview/events-by-day-chart";
import { EventsByTypeDonut } from "@/components/overview/events-by-type-donut";
import { KpiRow } from "@/components/overview/kpi-row";
import { RedZone } from "@/components/overview/red-zone";
import { usePeriod } from "@/lib/period";

export default function OverviewPage() {
  const { period } = usePeriod();

  return (
    <div className="flex flex-col gap-3">
      <KpiRow period={period} />
      <div className="grid gap-3 xl:grid-cols-[2fr_1fr]">
        <EventsByDayChart />
        <EventsByTypeDonut />
      </div>
      <div className="grid gap-3 xl:grid-cols-[2fr_1fr]">
        <CriticalLatest />
        <RedZone />
      </div>
    </div>
  );
}
