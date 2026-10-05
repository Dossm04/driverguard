"use client";

/* Профиль водителя (ШАГ 9, WEB-6): шапка с кольцом Score и действиями,
   график Score за 8 недель, donut событий за 30 дней, рейсы, лента событий
   с модалкой, назначенные микрообучения. Данные — GET /drivers/{id}/profile (BE-9). */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  ArrowLeft,
  ChartPie,
  Flame,
  GraduationCap,
  Pencil,
  Phone,
  Play,
  Route,
  ShieldCheck,
} from "lucide-react";
import Link from "next/link";
import { useParams } from "next/navigation";
import { useEffect, useState } from "react";
import {
  CartesianGrid,
  Cell,
  Line,
  LineChart,
  Pie,
  PieChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { DriverForm } from "@/components/driver-form";
import { EventModal, formatEventTime } from "@/components/event-modal";
import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { DataTable, type Column } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { QueryError } from "@/components/ui/query-error";
import { ScoreRing } from "@/components/ui/score-ring";
import { SectionCard } from "@/components/ui/section-card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";
import { useToast } from "@/components/ui/toast";
import { api, currentUser, type DriverOut, type DriverProfileOut, type EventItem } from "@/lib/api";
import { EVENT_ICONS, EVENT_LABELS, eventTitle, eventTypeColorVar } from "@/lib/events";
import { t, localeTag, perLang } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";
import { useTokenColors } from "@/lib/use-token-colors";
import { fleetDayMonth, fleetTime } from "@/lib/time";
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

const TRAINING_PILLS: Record<string, { label: string; tone: PillTone }> = perLang(() => ({
  assigned: { label: t("Назначено"), tone: "accent" },
  in_progress: { label: t("В процессе"), tone: "warn" },
  completed: { label: t("Пройдено"), tone: "ok" },
}));

const TRIP_PILLS: Record<string, { label: string; tone: PillTone }> = perLang(() => ({
  active: { label: t("В рейсе"), tone: "ok" },
  finished: { label: t("Завершён"), tone: "offline" },
}));

function formatDateTime(ts: string): string {
  return `${fleetDayMonth(ts)} ${fleetTime(ts)}`;
}

export default function DriverProfilePage() {
  useLangVersion();
  const params = useParams<{ id: string }>();
  const id = params.id;
  const toast = useToast();
  const queryClient = useQueryClient();
  const colors = useTokenColors(CHART_VARS);
  const [selected, setSelected] = useState<EventItem | null>(null);
  const [canManage, setCanManage] = useState(false);
  useEffect(() => {
    const role = currentUser()?.role;
    setCanManage(role === "admin" || role === "coordinator");
  }, []);

  const profile = useQuery({
    queryKey: ["driver-profile", id],
    queryFn: () => api<DriverProfileOut>(`/drivers/${id}/profile`),
  });
  const [editOpen, setEditOpen] = useState(false);
  // Объект для формы редактирования — из ответа профиля
  const editable: DriverOut | null = profile.data
    ? {
        id: profile.data.driver.id,
        name: profile.data.driver.name,
        depot_id: profile.data.driver.depot_id ?? null,
        phone: profile.data.driver.phone,
        depot_name: profile.data.driver.depot,
        vehicle_plate: profile.data.driver.vehicle?.plate ?? null,
        vehicle_id: profile.data.driver.vehicle?.id ?? null,
        photo_url: profile.data.driver.photo_url ?? null,
      }
    : null;

  const assign = useMutation({
    mutationFn: () =>
      api<{ training: string }>(`/drivers/${id}/trainings`, {
        method: "POST",
        body: JSON.stringify({}),
      }),
    onSuccess: (result) => {
      toast(t("Микрообучение «{0}» назначено", result.training));
      queryClient.invalidateQueries({ queryKey: ["driver-profile", id] });
      queryClient.invalidateQueries({ queryKey: ["red-zone"] });
    },
    onError: (e) => toast(e instanceof Error ? e.message : t("Не удалось назначить обучение")),
  });

  if (profile.isError) {
    return (
      <div className="flex flex-col gap-3">
        <BackLink />
        <QueryError error={profile.error} onRetry={() => profile.refetch()} />
      </div>
    );
  }
  if (profile.isLoading || !profile.data) {
    return (
      <div className="flex flex-col gap-3">
        <BackLink />
        <Skeleton className="h-[104px] rounded-card" />
        <div className="grid gap-3 xl:grid-cols-[2fr_1fr]">
          <Skeleton className="h-[280px] rounded-card" />
          <Skeleton className="h-[280px] rounded-card" />
        </div>
      </div>
    );
  }

  const p = profile.data;
  const weekPoints = p.score_by_week.map((w) => ({
    label: w.weeks_ago === 0 ? t("эта") : t("−{0} нед", w.weeks_ago),
    Score: w.score,
  }));
  const breakdownTotal = p.breakdown_30d.reduce((sum, b) => sum + b.count, 0);
  const breakdown = p.breakdown_30d.map((b) => ({
    ...b,
    label: EVENT_LABELS[b.type] ?? b.type,
    color: colors?.[eventTypeColorVar(b.type)] ?? "",
    pct: breakdownTotal ? Math.round((b.count / breakdownTotal) * 100) : 0,
  }));

  const tripColumns: Column<DriverProfileOut["trips"][number]>[] = [
    { key: "id", header: "№", render: (t) => <b className="num">{t.id}</b> },
    {
      key: "start",
      header: t("Начало"),
      render: (t) => <span className="num whitespace-nowrap">{formatDateTime(t.started_at)}</span>,
    },
    {
      key: "end",
      header: t("Завершение"),
      render: (t) => (
        <span className="num whitespace-nowrap">
          {t.ended_at ? formatDateTime(t.ended_at) : "—"}
        </span>
      ),
    },
    {
      key: "km",
      header: t("Км"),
      render: (t) => <span className="num">{Math.round(t.distance_km).toLocaleString(localeTag())}</span>,
    },
    {
      key: "status",
      header: t("Статус"),
      render: (t) => {
        const pill = TRIP_PILLS[t.status] ?? { label: t.status, tone: "offline" as PillTone };
        return <StatusPill tone={pill.tone}>{pill.label}</StatusPill>;
      },
    },
  ];

  return (
    <div className="flex flex-col gap-3">
      <BackLink />

      {/* Шапка профиля */}
      <div className="flex flex-wrap items-center gap-4 rounded-card border border-line bg-card p-4">
        <Avatar name={p.driver.name} size={56} ring={p.score.zone} src={p.driver.photo_url} />
        <div className="min-w-0">
          <h2 className="truncate text-lg font-extrabold">{p.driver.name}</h2>
          <div className="truncate text-[13px] text-mut">
            {p.driver.depot ?? t("Без депо")}
            {p.driver.vehicle ? ` · ${p.driver.vehicle.model} ${p.driver.vehicle.plate}` : t(" · без машины")}
            {p.driver.phone ? ` · ${p.driver.phone}` : ""}
          </div>
          <div className="mt-1 flex items-center gap-1 text-xs">
            {p.score.streak > 0 ? (
              <span className="num flex items-center gap-1 font-bold text-warn">
                <Flame size={13} /> {p.score.streak}{" "}
                {pluralRu(p.score.streak, t("день"), t("дня"), t("дней"))} {t("без критических")}
              </span>
            ) : (
              <span className="text-mut">{t("серия прервана")}</span>
            )}
          </div>
        </div>
        <ScoreRing value={p.score.value} zone={p.score.zone} size={72} className="ml-auto" />
        <div className="flex flex-wrap gap-2">
          {p.driver.phone ? (
            <Button asChild>
              <a href={`tel:${p.driver.phone}`}>
                <Phone size={16} /> {t("Позвонить")}
              </a>
            </Button>
          ) : (
            <Button disabled title={t("Телефон не указан")}>
              <Phone size={16} /> {t("Позвонить")}
            </Button>
          )}
          {canManage && (
            <Button variant="outline" disabled={assign.isPending} onClick={() => assign.mutate()}>
              <GraduationCap size={16} />
              {assign.isPending ? t("Назначаем…") : t("Назначить обучение")}
            </Button>
          )}
          {canManage && (
            <Button variant="outline" onClick={() => setEditOpen(true)} data-testid="driver-edit">
              <Pencil size={16} /> {t("Редактировать")}
            </Button>
          )}
        </div>
      </div>
      <DriverForm
        open={editOpen}
        onClose={() => setEditOpen(false)}
        driver={editable}
        onSaved={() => profile.refetch()}
      />

      {/* Графики */}
      <div className="grid gap-3 xl:grid-cols-[2fr_1fr]">
        <SectionCard title={t("Score · 8 недель")} subtitle={t("динамика по неделям")}>
          {!colors ? (
            <Skeleton className="h-[220px]" />
          ) : (
            <div className="h-[220px]">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={weekPoints} margin={{ top: 6, right: 8, left: -22, bottom: 0 }}>
                  <CartesianGrid vertical={false} stroke={colors["--line"]} strokeOpacity={0.6} />
                  <XAxis
                    dataKey="label"
                    tickLine={false}
                    axisLine={false}
                    tick={{ fill: colors["--mut"], fontSize: 11 }}
                  />
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
          )}
        </SectionCard>

        <SectionCard title={t("События · 30 дней")} subtitle={t("разбивка по типам")}>
          {!colors ? (
            <Skeleton className="h-[220px]" />
          ) : breakdown.length === 0 ? (
            <EmptyState
              icon={ChartPie}
              title={t("Событий нет")}
              description={t("За 30 дней ничего не зафиксировано.")}
            />
          ) : (
            <div className="flex flex-col items-center gap-3">
              <PieChart width={180} height={180} className="flex-none">
                <Pie
                  data={breakdown}
                  dataKey="count"
                  nameKey="label"
                  innerRadius={54}
                  outerRadius={84}
                  paddingAngle={2}
                  stroke={colors["--card"]}
                  strokeWidth={2}
                  isAnimationActive={false}
                >
                  {breakdown.map((b) => (
                    <Cell key={b.type} fill={b.color} />
                  ))}
                </Pie>
                <Tooltip
                  formatter={(value, name, item) => [
                    `${value} · ${(item.payload as { pct: number }).pct}%`,
                    name,
                  ]}
                  contentStyle={{
                    background: colors["--card"],
                    border: `1px solid ${colors["--line"]}`,
                    borderRadius: 12,
                    color: colors["--txt"],
                    fontSize: 12,
                  }}
                />
              </PieChart>
              <ul className="flex w-full flex-col gap-1.5">
                {breakdown.map((b) => (
                  <li key={b.type} className="flex items-center gap-2 text-xs">
                    <span className="h-2 w-2 flex-none rounded-full" style={{ background: b.color }} />
                    <span className="truncate font-semibold text-mut">{b.label}</span>
                    <span className="num ml-auto font-bold">{b.count}</span>
                  </li>
                ))}
              </ul>
            </div>
          )}
        </SectionCard>
      </div>

      {/* Рейсы и обучения */}
      <div className="grid gap-3 xl:grid-cols-[2fr_1fr]">
        <SectionCard title={t("Последние рейсы")} subtitle={t("до 10 записей")}>
          {p.trips.length === 0 ? (
            <EmptyState icon={Route} title={t("Рейсов нет")} description={t("Водитель ещё не выезжал.")} />
          ) : (
            <DataTable columns={tripColumns} rows={p.trips} rowKey={(t) => t.id} />
          )}
        </SectionCard>

        <SectionCard title={t("Микрообучения")} subtitle={t("назначенные уроки")}>
          {p.trainings.length === 0 ? (
            <EmptyState
              icon={GraduationCap}
              title={t("Не назначено")}
              description={t("Уроки появятся после назначения координатором.")}
            />
          ) : (
            <ul className="flex flex-col" data-testid="training-list">
              {p.trainings.map((tr) => {
                const pill =
                  TRAINING_PILLS[tr.status] ?? { label: tr.status, tone: "offline" as PillTone };
                return (
                  <li
                    key={tr.id}
                    className="flex items-center gap-3 border-b border-line/60 py-2.5 last:border-b-0"
                  >
                    <span className="grid h-9 w-9 flex-none place-items-center rounded-btn bg-accent/15 text-accent">
                      <GraduationCap size={17} />
                    </span>
                    <span className="min-w-0">
                      <b className="block truncate text-sm">{t(tr.title)}</b>
                      <span className="num block text-xs text-mut">
                        {formatDateTime(tr.assigned_at)}
                      </span>
                    </span>
                    <span className="ml-auto">
                      <StatusPill tone={pill.tone}>{pill.label}</StatusPill>
                    </span>
                  </li>
                );
              })}
            </ul>
          )}
        </SectionCard>
      </div>

      {/* Лента последних событий */}
      <SectionCard title={t("Последние события")} subtitle={t("до 10 записей · клик открывает разбор")}>
        {p.recent_events.length === 0 ? (
          <EmptyState
            icon={ShieldCheck}
            title={t("Событий нет")}
            description={t("Идеальная история — так держать.")}
          />
        ) : (
          <ul className="flex flex-col">
            {p.recent_events.map((e) => {
              const Icon = EVENT_ICONS[e.type] ?? ShieldCheck;
              return (
                <li
                  key={e.uuid}
                  className="flex items-center gap-3 border-b border-line/60 py-2.5 last:border-b-0"
                >
                  <span
                    className={cn(
                      "grid h-9 w-9 flex-none place-items-center rounded-btn",
                      e.severity === "critical"
                        ? "bg-danger/15 text-danger"
                        : e.severity === "warning"
                          ? "bg-warn/15 text-warn"
                          : "bg-offline/15 text-offline",
                    )}
                  >
                    <Icon size={17} />
                  </span>
                  <span className="min-w-0">
                    <b className="block truncate text-sm">{eventTitle(e.type, e.value)}</b>
                    <span className="num block text-xs text-mut">
                      {e.speed_kmh != null ? t("{0} км/ч · ", Math.round(e.speed_kmh)) : ""}
                      {formatEventTime(e.ts)}
                    </span>
                  </span>
                  <Button
                    variant="outline"
                    size="sm"
                    className="ml-auto"
                    onClick={() => setSelected(e)}
                  >
                    <Play size={14} className="text-accent" /> {t("Разбор")}
                  </Button>
                </li>
              );
            })}
          </ul>
        )}
      </SectionCard>

      <EventModal event={selected} onClose={() => setSelected(null)} />
    </div>
  );
}

function BackLink() {
  useLangVersion();
  return (
    <Link
      href="/drivers"
      className="flex w-fit items-center gap-1.5 text-sm font-semibold text-mut transition-colors hover:text-txt"
    >
      <ArrowLeft size={16} /> {t("Все водители")}
    </Link>
  );
}
