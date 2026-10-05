"use client";

/* Лидерборд (ШАГ 8, WEB-5): подиум топ-3, полная таблица, командный зачёт депо,
   бейджи, сноска с формулой. Данные — /leaderboard, переключение периода мгновенное. */

import { useQuery } from "@tanstack/react-query";
import { Flame, Moon, Shield } from "lucide-react";
import { useRouter } from "next/navigation";
import { useState } from "react";

import { StatusPill } from "@/components/ui/status-pill";
import { Avatar } from "@/components/ui/avatar";
import { DataTable, type Column } from "@/components/ui/data-table";
import { QueryError } from "@/components/ui/query-error";
import { SectionCard } from "@/components/ui/section-card";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type LeaderboardOut, type LeaderRow } from "@/lib/api";
import { t, localeTag, perLang } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";
import { cn, pluralRu } from "@/lib/utils";

const MEDALS = ["🥇", "🥈", "🥉"];

const zoneText: Record<LeaderRow["zone"], string> = {
  ok: "text-ok",
  warn: "text-warn",
  danger: "text-danger",
};
const zoneBg: Record<LeaderRow["zone"], string> = {
  ok: "bg-ok",
  warn: "bg-warn",
  danger: "bg-danger",
};

const BADGES = perLang(() => [
  {
    id: "week_no_risk",
    icon: Flame,
    title: t("Неделя без риска"),
    hint: t("7 дней серии без критических событий"),
  },
  {
    id: "iron_streak",
    icon: Shield,
    title: t("Железная выдержка"),
    hint: t("30 дней серии"),
  },
  {
    id: "night_guard",
    icon: Moon,
    title: t("Ночной страж"),
    hint: t("10 ночных рейсов без событий (появится с данными рейсов)"),
  },
]);

export default function LeaderboardPage() {
  useLangVersion();
  const router = useRouter();
  const [period, setPeriod] = useState<"7" | "30">("7");
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["leaderboard", period],
    queryFn: () => api<LeaderboardOut>(`/leaderboard?period=${period}`),
    staleTime: 30_000,
  });

  const columns: Column<LeaderRow>[] = [
    { key: "rank", header: "#", render: (r) => <b className="num">{r.rank}</b> },
    {
      key: "driver",
      header: t("Водитель"),
      render: (r) => (
        <span className="flex items-center gap-2.5">
          <Avatar name={r.name} />
          <b className="whitespace-nowrap">{r.name}</b>
        </span>
      ),
    },
    { key: "depot", header: t("Депо"), render: (r) => <span className="text-mut">{r.depot}</span> },
    {
      key: "score",
      header: "Score",
      render: (r) => (
        r.is_new ? <StatusPill tone="offline">{t("Новичок")}</StatusPill> : <b className={cn("num text-lg", zoneText[r.zone])}>{r.score}</b>
      ),
    },
    {
      key: "delta",
      header: t("Δ период"),
      render: (r) =>
        r.delta === 0 ? (
          <span className="text-mut">—</span>
        ) : (
          <span className={cn("num font-bold", r.delta > 0 ? "text-ok" : "text-danger")}>
            {r.delta > 0 ? "▲" : "▼"} {Math.abs(r.delta)}
          </span>
        ),
    },
    {
      key: "streak",
      header: t("Серия"),
      render: (r) =>
        r.streak > 0 ? (
          <span className="num flex items-center gap-1 font-bold text-warn">
            <Flame size={14} /> {r.streak}
          </span>
        ) : (
          <span className="text-mut">—</span>
        ),
    },
    {
      key: "km",
      header: t("Км"),
      render: (r) => <span className="num">{r.km.toLocaleString(localeTag())}</span>,
    },
    { key: "events", header: t("Событий"), render: (r) => <span className="num">{r.events}</span> },
  ];

  return (
    <div className="flex flex-col gap-3">
      <div className="flex gap-1.5" role="tablist" aria-label={t("Период лидерборда")}>
        {(
          [
            { value: "7", label: t("Неделя") },
            { value: "30", label: t("Месяц") },
          ] as const
        ).map((tab) => (
          <button
            key={tab.value}
            role="tab"
            aria-selected={period === tab.value}
            onClick={() => setPeriod(tab.value)}
            className={cn(
              "rounded-btn border border-line px-4 py-1.5 text-sm font-bold text-mut transition-colors hover:text-txt",
              period === tab.value && "border-accent bg-accent/10 text-accent",
            )}
          >
            {tab.label}
          </button>
        ))}
      </div>

      {isError ? (
        <QueryError error={error} onRetry={() => refetch()} />
      ) : isLoading || !data ? (
        <div className="grid gap-3 md:grid-cols-3">
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-[190px] rounded-card" />
          ))}
        </div>
      ) : (
        <>
          {/* Подиум топ-3 */}
          <div className="grid gap-3 md:grid-cols-3">
            {data.rows.slice(0, 3).map((r, i) => (
              <button
                key={r.driver_id}
                onClick={() => router.push(`/drivers/${r.driver_id}`)}
                className="relative rounded-card border border-line bg-card p-4 text-center transition-transform hover:-translate-y-0.5 hover:border-accent"
              >
                <span className="absolute left-3 top-2.5 text-2xl" aria-label={t("Место {0}", i + 1)}>
                  {MEDALS[i]}
                </span>
                <div className="flex justify-center">
                  <Avatar name={r.name} size={56} />
                </div>
                <div className="mt-2 text-[15px] font-extrabold">{r.name}</div>
                <div className="text-xs text-mut">{t("Депо")}{" "}{r.depot}</div>
                <div className={cn("num mt-1 text-4xl font-extrabold", zoneText[r.zone])}>
                  {r.is_new ? "—" : r.score}
                </div>
                <div className="num mt-1 flex items-center justify-center gap-1 text-sm font-bold text-warn">
                  {r.streak > 0 ? (
                    <>
                      <Flame size={15} /> {r.streak}{" "}
                      {pluralRu(r.streak, t("день"), t("дня"), t("дней"))} {t("без событий")}
                    </>
                  ) : (
                    <span className="text-mut">{t("серия прервана")}</span>
                  )}
                </div>
              </button>
            ))}
          </div>

          <div className="grid gap-3 xl:grid-cols-[2fr_1fr]">
            {/* Полная таблица */}
            <div className="rounded-card border border-line bg-card p-2">
              <DataTable
                columns={columns}
                rows={data.rows}
                rowKey={(r) => r.driver_id}
                onRowClick={(r) => router.push(`/drivers/${r.driver_id}`)}
              />
              <p className="px-2.5 pb-1.5 pt-3 text-xs leading-relaxed text-mut">
                {t("Формула: Score = clamp(40..100, 100 − Σ(вес × модификатор скорости) × 7/дней × 0.8 + бонус серии ≤10). Учитываются только подтверждённые и неоспоренные события; «ложное срабатывание» возвращает баллы водителю.")}
              </p>
            </div>

            <div className="flex flex-col gap-3">
              {/* Командный зачёт депо */}
              <SectionCard title={t("Командный зачёт депо")} subtitle={t("средний Score водителей")}>
                <div className="flex flex-col gap-3">
                  {/* Зону считает backend по общим порогам скоринга — фронт не дублирует */}
                  {data.depots.map((d) => (
                    <div key={d.name}>
                      <div className="flex items-baseline justify-between text-sm">
                        <b>{t("Депо")}{" "}{d.name}</b>
                        <span className={cn("num font-extrabold", zoneText[d.zone])}>
                          {d.avg_score}
                        </span>
                      </div>
                      <div className="mt-1 h-2 overflow-hidden rounded-full bg-cardh">
                        <div
                          className={cn("h-full rounded-full", zoneBg[d.zone])}
                          style={{ width: `${d.avg_score}%` }}
                        />
                      </div>
                      <div className="num mt-0.5 text-[11px] text-mut">
                        {d.drivers} {pluralRu(d.drivers, t("водитель"), t("водителя"), t("водителей"))}
                      </div>
                    </div>
                  ))}
                </div>
              </SectionCard>

              {/* Бейджи */}
              <SectionCard title={t("Бейджи")} subtitle={t("достижения серии")}>
                <ul className="flex flex-col">
                  {BADGES.map((b) => {
                    const holders = data.rows.filter((r) => r.badges.includes(b.id));
                    return (
                      <li
                        key={b.id}
                        className="flex items-center gap-3 border-b border-line/60 py-2.5 last:border-b-0"
                      >
                        <span className="grid h-9 w-9 flex-none place-items-center rounded-btn bg-warn/15 text-warn">
                          <b.icon size={17} />
                        </span>
                        <span className="min-w-0">
                          <b className="block text-sm">{b.title}</b>
                          <span className="block truncate text-xs text-mut">{b.hint}</span>
                        </span>
                        <span className="num ml-auto text-sm font-bold text-mut">
                          {holders.length > 0
                            ? `× ${holders.length}`
                            : "—"}
                        </span>
                      </li>
                    );
                  })}
                </ul>
              </SectionCard>
            </div>
          </div>
        </>
      )}
    </div>
  );
}
