"use client";

/* Страница «Отчёты» (ШАГ 11, WEB-8, US-8): период из топбара + депо, KPI, динамика
   Score парка, события по типам и по водителям, рискованные участки, рейсы,
   экспорт CSV/PDF (серверная генерация). */

import { useQuery } from "@tanstack/react-query";
import {
  Activity,
  AlertTriangle,
  Download,
  FileText,
  Gauge,
  MapPinned,
  Route,
  Users,
} from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";
import {
  CartesianGrid,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { formatEventTime } from "@/components/event-modal";
import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { DataTable, type Column } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { KpiCard } from "@/components/ui/kpi-card";
import { QueryError } from "@/components/ui/query-error";
import { SectionCard } from "@/components/ui/section-card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";
import { useToast } from "@/components/ui/toast";
import { api, apiBlob, saveBlob, type DepotOut, type ReportSummary } from "@/lib/api";
import { EVENT_LABELS, eventTypeColorVar } from "@/lib/events";
import { t, localeTag, perLang } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";
import { usePeriod } from "@/lib/period";
import { useTokenColors } from "@/lib/use-token-colors";
import { cn, pluralRu } from "@/lib/utils";

const CHART_VARS = [
  "--accent",
  "--line",
  "--mut",
  "--card",
  "--txt",
  "--cat-1",
  "--cat-2",
  "--cat-3",
  "--cat-4",
  "--cat-5",
  "--cat-6",
  "--cat-7",
  "--cat-8",
  "--offline",
];

const ZONE_TEXT = { ok: "text-ok", warn: "text-warn", danger: "text-danger" } as const;
const ZONE_PILL: Record<string, { label: string; tone: PillTone }> = perLang(() => ({
  ok: { label: t("норма"), tone: "ok" },
  warn: { label: t("внимание"), tone: "warn" },
  danger: { label: t("красная зона"), tone: "danger" },
}));
const TRIP_PILLS: Record<string, { label: string; tone: PillTone }> = perLang(() => ({
  active: { label: t("В рейсе"), tone: "ok" },
  finished: { label: t("Завершён"), tone: "offline" },
}));

export default function ReportsPage() {
  useLangVersion();
  const { period } = usePeriod();
  const router = useRouter();
  const toast = useToast();
  const colors = useTokenColors(CHART_VARS);
  const [depotId, setDepotId] = useState("");
  const [exporting, setExporting] = useState<"csv" | "pdf" | null>(null);

  const depots = useQuery({
    queryKey: ["depots"],
    queryFn: () => api<DepotOut[]>("/depots"),
    staleTime: 60_000,
  });
  const query = `period=${period}${depotId ? `&depot_id=${depotId}` : ""}`;
  const report = useQuery({
    queryKey: ["report", period, depotId],
    queryFn: () => api<ReportSummary>(`/reports/summary?${query}`),
    staleTime: 30_000,
  });

  const exportFile = async (kind: "csv" | "pdf") => {
    setExporting(kind);
    try {
      const { blob, filename } = await apiBlob(`/reports/export.${kind}?${query}`);
      saveBlob(blob, filename);
      toast(kind === "pdf" ? t("PDF-отчёт сформирован") : t("CSV-отчёт сформирован"));
    } catch (e) {
      toast(e instanceof Error ? e.message : t("Не удалось сформировать отчёт"));
    } finally {
      setExporting(null);
    }
  };

  const driverColumns: Column<ReportSummary["by_driver"][number]>[] = [
    {
      key: "driver",
      header: t("Водитель"),
      render: (d) => (
        <span className="flex items-center gap-2.5">
          <Avatar name={d.name} />
          <span>
            <b className="block whitespace-nowrap">{d.name}</b>
            <span className="num block text-xs text-mut">{d.vehicle_plate ?? t("без машины")}</span>
          </span>
        </span>
      ),
    },
    { key: "depot", header: t("Депо"), render: (d) => <span className="text-mut">{d.depot ?? "—"}</span> },
    { key: "events", header: t("Событий"), render: (d) => <span className="num">{d.events}</span> },
    {
      key: "critical",
      header: t("Критич."),
      render: (d) => (
        <span className={cn("num font-bold", d.critical > 0 ? "text-danger" : "text-mut")}>
          {d.critical}
        </span>
      ),
    },
    {
      key: "score",
      header: "Score",
      render: (d) => <b className={cn("num text-lg", ZONE_TEXT[d.zone])}>{d.score}</b>,
    },
    { key: "km", header: t("Км"), render: (d) => <span className="num">{d.km.toLocaleString(localeTag())}</span> },
  ];

  const segmentColumns: Column<ReportSummary["risky_segments"][number] & { n: number }>[] = [
    { key: "n", header: "#", render: (s) => <b className="num">{s.n}</b> },
    {
      key: "coords",
      header: t("Координаты"),
      render: (s) => (
        <a
          className="num text-accent hover:underline"
          target="_blank"
          rel="noreferrer"
          href={`https://www.openstreetmap.org/?mlat=${s.lat}&mlon=${s.lon}#map=12/${s.lat}/${s.lon}`}
        >
          {s.lat.toFixed(3)}, {s.lon.toFixed(3)}
        </a>
      ),
    },
    { key: "events", header: t("Событий"), render: (s) => <span className="num">{s.events}</span> },
    {
      key: "critical",
      header: t("Критич."),
      render: (s) => (
        <span className={cn("num font-bold", s.critical > 0 ? "text-danger" : "text-mut")}>
          {s.critical}
        </span>
      ),
    },
    { key: "type", header: t("Основной тип"), render: (s) => EVENT_LABELS[s.top_type] ?? s.top_type },
  ];

  const tripColumns: Column<ReportSummary["trips"][number]>[] = [
    { key: "id", header: "№", render: (t) => <b className="num">{t.id}</b> },
    { key: "driver", header: t("Водитель"), render: (t) => <b className="whitespace-nowrap">{t.driver_name}</b> },
    { key: "plate", header: t("Машина"), render: (t) => <span className="num">{t.vehicle_plate}</span> },
    {
      key: "start",
      header: t("Начало"),
      render: (t) => <span className="num whitespace-nowrap">{formatEventTime(t.started_at)}</span>,
    },
    {
      key: "end",
      header: t("Завершение"),
      render: (t) => (
        <span className="num whitespace-nowrap">{t.ended_at ? formatEventTime(t.ended_at) : "—"}</span>
      ),
    },
    { key: "km", header: t("Км"), render: (t) => <span className="num">{t.km.toLocaleString(localeTag())}</span> },
    { key: "events", header: t("Событий"), render: (t) => <span className="num">{t.events}</span> },
    {
      key: "status",
      header: t("Статус"),
      render: (t) => {
        const pill = TRIP_PILLS[t.status] ?? { label: t.status, tone: "offline" as PillTone };
        return <StatusPill tone={pill.tone}>{pill.label}</StatusPill>;
      },
    },
  ];

  const r = report.data;
  const trend = (r?.score_trend ?? []).map((p) => ({
    label: p.weeks_ago === 0 ? t("эта") : t("−{0} нед", p.weeks_ago),
    Score: p.avg_score,
  }));

  return (
    <div className="flex flex-col gap-3">
      {/* Тулбар: депо + экспорт (период — в топбаре) */}
      <div className="flex flex-wrap items-center gap-2.5 rounded-card border border-line bg-card p-3">
        <select
          aria-label={t("Депо")}
          className="h-9 rounded-btn border border-line bg-cardh px-3 text-sm font-semibold disabled:opacity-60"
          disabled={depots.isError}
          title={depots.isError ? t("Список депо недоступен") : undefined}
          value={depotId}
          onChange={(e) => setDepotId(e.target.value)}
        >
          <option value="">{t("Все депо")}</option>
          {(depots.data ?? []).map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
        <span className="text-xs text-mut">{t("Период выбирается в верхней панели")}</span>
        <span className="ml-auto flex gap-2">
          <Button variant="outline" disabled={exporting !== null || !r} onClick={() => exportFile("csv")}>
            <Download size={16} /> {exporting === "csv" ? t("Формируем…") : "CSV"}
          </Button>
          <Button disabled={exporting !== null || !r} onClick={() => exportFile("pdf")}>
            <FileText size={16} /> {exporting === "pdf" ? t("Формируем…") : "PDF"}
          </Button>
        </span>
      </div>

      {report.isError ? (
        <QueryError error={report.error} onRetry={() => report.refetch()} />
      ) : report.isLoading || !r || !colors ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
          {Array.from({ length: 4 }, (_, i) => (
            <Skeleton key={i} className="h-[112px] rounded-card" />
          ))}
        </div>
      ) : r.totals.drivers === 0 ? (
        <EmptyState icon={Users} title={t("Водителей нет")} description={t("В выбранном депо нет водителей.")} />
      ) : (
        <>
          <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-4">
            <KpiCard
              title={t("События")}
              icon={Activity}
              iconTone="accent"
              value={r.totals.events}
              sub={`${r.totals.warning} ${pluralRu(r.totals.warning, t("предупреждение"), t("предупреждения"), t("предупреждений"))}`}
            />
            <KpiCard
              title={t("Критические")}
              icon={AlertTriangle}
              iconTone={r.totals.critical > 0 ? "danger" : "ok"}
              value={r.totals.critical}
              sub={`${r.totals.drivers} ${pluralRu(r.totals.drivers, t("водитель"), t("водителя"), t("водителей"))}`}
            />
            <KpiCard
              title={t("Пробег")}
              icon={Route}
              iconTone="ok"
              value={r.totals.km.toLocaleString(localeTag())}
              sub={t("км · {0} {1}", r.totals.trips, pluralRu(r.totals.trips, "рейс", "рейса", "рейсов"))}
            />
            <KpiCard
              title={t("Средний Score")}
              icon={Gauge}
              iconTone={r.totals.avg_zone}
              value={r.totals.avg_score}
              pill={ZONE_PILL[r.totals.avg_zone]}
            />
          </div>

          <div className="grid gap-3 xl:grid-cols-[2fr_1fr]">
            <SectionCard title={t("Динамика Score парка")} subtitle={t("средний Score по неделям")}>
              <div className="h-[220px]">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={trend} margin={{ top: 6, right: 8, left: -22, bottom: 0 }}>
                    <CartesianGrid vertical={false} stroke={colors["--line"]} strokeOpacity={0.6} />
                    <XAxis dataKey="label" tickLine={false} axisLine={false} tick={{ fill: colors["--mut"], fontSize: 11 }} />
                    <YAxis
                      domain={[40, 100]}
                      ticks={[40, 60, 80, 100]}
                      tickLine={false}
                      axisLine={false}
                      tick={{ fill: colors["--mut"], fontSize: 11 }}
                    />
                    <Tooltip
                      cursor={{ stroke: colors["--line"] }}
                      contentStyle={{
                        background: colors["--card"],
                        border: `1px solid ${colors["--line"]}`,
                        borderRadius: 12,
                        color: colors["--txt"],
                        fontSize: 12,
                      }}
                      labelStyle={{ color: colors["--mut"], fontWeight: 700 }}
                    />
                    <Line
                      type="monotone"
                      dataKey="Score"
                      stroke={colors["--accent"]}
                      strokeWidth={2}
                      dot={{ r: 3, fill: colors["--accent"], strokeWidth: 0 }}
                      isAnimationActive={false}
                    />
                  </LineChart>
                </ResponsiveContainer>
              </div>
            </SectionCard>

            <SectionCard title={t("События по типам")} subtitle={t("доля за период")}>
              {r.by_type.length === 0 ? (
                <EmptyState icon={Activity} title={t("Событий нет")} description={t("За период ничего не зафиксировано.")} />
              ) : (
                <ul className="flex flex-col gap-2">
                  {r.by_type.map((t) => (
                    <li key={t.type} className="text-xs">
                      <span className="flex items-center gap-2">
                        <span
                          className="h-2 w-2 flex-none rounded-full"
                          style={{ background: colors[eventTypeColorVar(t.type)] }}
                        />
                        <span className="truncate font-semibold text-mut">{EVENT_LABELS[t.type] ?? t.type}</span>
                        <span className="num ml-auto font-bold">
                          {t.count} · {t.share_pct}%
                        </span>
                      </span>
                      <span className="mt-1 block h-1.5 overflow-hidden rounded-full bg-cardh">
                        <span
                          className="block h-full rounded-full"
                          style={{ width: `${t.share_pct}%`, background: colors[eventTypeColorVar(t.type)] }}
                        />
                      </span>
                    </li>
                  ))}
                </ul>
              )}
            </SectionCard>
          </div>

          <SectionCard title={t("По водителям")} subtitle={t("события, Score и пробег за период")}>
            <DataTable
              columns={driverColumns}
              rows={r.by_driver}
              rowKey={(d) => d.driver_id}
              onRowClick={(d) => router.push(`/drivers/${d.driver_id}`)}
            />
          </SectionCard>

          <div className="grid gap-3 xl:grid-cols-[1fr_2fr]">
            <SectionCard title={t("Рискованные участки трассы")} subtitle={t("кластеры координат событий, топ-5")}>
              {r.risky_segments.length === 0 ? (
                <EmptyState icon={MapPinned} title={t("Нет данных")} description={t("События без координат.")} />
              ) : (
                <DataTable
                  columns={segmentColumns}
                  rows={r.risky_segments.map((s, i) => ({ ...s, n: i + 1 }))}
                  rowKey={(s) => s.n}
                />
              )}
            </SectionCard>
            <SectionCard
              title={t("Рейсы за период")}
              subtitle={`${r.totals.trips} ${pluralRu(r.totals.trips, t("рейс"), t("рейса"), t("рейсов"))}${r.totals.trips > r.trips.length ? t(" · показаны последние {0}", r.trips.length) : ""}`}
            >
              {r.trips.length === 0 ? (
                <EmptyState icon={Route} title={t("Рейсов нет")} description={t("За период выездов не было.")} />
              ) : (
                <DataTable columns={tripColumns} rows={r.trips} rowKey={(t) => t.id} />
              )}
            </SectionCard>
          </div>
        </>
      )}
    </div>
  );
}
