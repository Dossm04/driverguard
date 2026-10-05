"use client";

/* Страница «Водители» (ШАГ 9, WEB-6): сетка карточек с кольцом Score,
   поиск, сортировка, «Добавить водителя». Score/серия — из /leaderboard
   (единая формула, без дублирования расчётов на фронте). */

import { useQuery } from "@tanstack/react-query";
import { Flame, Search, UserPlus, Users } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useState } from "react";

import { DriverForm } from "@/components/driver-form";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { QueryError } from "@/components/ui/query-error";
import { Avatar } from "@/components/ui/avatar";
import { ScoreRing } from "@/components/ui/score-ring";
import { Skeleton } from "@/components/ui/skeleton";
import {
  api,
  currentUser,
  type DriverOut,
  type LeaderboardOut,
  type LeaderRow,
} from "@/lib/api";
import { t, perLang } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";
import { pluralRu } from "@/lib/utils";
import { matches } from "@/lib/text";

const SORTS = perLang(() => [
  { value: "score", label: t("По Score") },
  { value: "name", label: t("По имени") },
  { value: "events", label: t("По событиям") },
  { value: "streak", label: t("По серии") },
] as const);
type SortKey = (typeof SORTS)[number]["value"];

interface CardRow {
  driver: DriverOut;
  stats: LeaderRow | undefined;
}

export default function DriversPage() {
  useLangVersion();
  const [search, setSearch] = useState("");
  useEffect(() => {
    // Переход из поиска в топбаре: /drivers?q=… (без useSearchParams — страница статическая)
    const q = new URLSearchParams(window.location.search).get("q");
    if (q) setSearch(q);
  }, []);
  const [sort, setSort] = useState<SortKey>("score");
  const [formOpen, setFormOpen] = useState(false);
  // Роль — в эффекте: при SSR localStorage нет (без расхождения гидрации)
  const [canManage, setCanManage] = useState(false);
  useEffect(() => {
    const role = currentUser()?.role;
    setCanManage(role === "admin" || role === "coordinator");
  }, []);

  const drivers = useQuery({
    queryKey: ["drivers"],
    queryFn: () => api<DriverOut[]>("/drivers"),
  });
  const leaderboard = useQuery({
    queryKey: ["leaderboard", "7"],
    queryFn: () => api<LeaderboardOut>("/leaderboard?period=7"),
    staleTime: 30_000,
  });

  const rows = useMemo<CardRow[]>(() => {
    const stats = new Map((leaderboard.data?.rows ?? []).map((r) => [r.driver_id, r]));
    const filtered = (drivers.data ?? []).filter((d) =>
      matches([d.name, d.vehicle_plate ?? "", d.depot_name ?? ""].join(" "), search),
    );
    const list = filtered.map((d) => ({ driver: d, stats: stats.get(d.id) }));
    const val = (r: CardRow) => ({
      score: r.stats?.score ?? 100,
      events: r.stats?.events ?? 0,
      streak: r.stats?.streak ?? 0,
    });
    list.sort((a, b) => {
      if (sort === "name") return a.driver.name.localeCompare(b.driver.name, "ru");
      if (sort === "events") return val(b).events - val(a).events;
      if (sort === "streak") return val(b).streak - val(a).streak;
      return val(b).score - val(a).score;
    });
    return list;
  }, [drivers.data, leaderboard.data, search, sort]);

  const isLoading = drivers.isLoading || leaderboard.isLoading;
  const queryError = drivers.isError ? drivers : leaderboard.isError ? leaderboard : null;

  return (
    <div className="flex flex-col gap-3">
      {/* Тулбар: поиск, сортировка, добавление */}
      <div className="flex flex-wrap items-center gap-2.5 rounded-card border border-line bg-card p-3">
        <div className="relative">
          <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-mut" />
          <input
            aria-label={t("Поиск водителя")}
            className="h-9 w-64 rounded-btn border border-line bg-cardh pl-9 pr-3 text-sm font-semibold placeholder:font-normal"
            placeholder={t("Водитель, номер машины, депо…")}
            value={search}
            onChange={(e) => setSearch(e.target.value)}
          />
        </div>
        <select
          aria-label={t("Сортировка")}
          className="h-9 rounded-btn border border-line bg-cardh px-3 text-sm font-semibold"
          value={sort}
          onChange={(e) => setSort(e.target.value as SortKey)}
        >
          {SORTS.map((s) => (
            <option key={s.value} value={s.value}>
              {s.label}
            </option>
          ))}
        </select>
        {canManage && (
          <Button className="ml-auto" onClick={() => setFormOpen(true)}>
            <UserPlus size={16} /> {t("Добавить водителя")}
          </Button>
        )}
      </div>

      {queryError ? (
        <QueryError error={queryError.error} onRetry={() => queryError.refetch()} />
      ) : isLoading ? (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {Array.from({ length: 6 }, (_, i) => (
            <Skeleton key={i} className="h-[104px] rounded-card" />
          ))}
        </div>
      ) : rows.length === 0 ? (
        <EmptyState
          icon={Users}
          title={t("Никого не нашли")}
          description={t("Попробуйте изменить запрос поиска.")}
        />
      ) : (
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {rows.map(({ driver, stats }) => {
            const streak = stats?.streak ?? 0;
            return (
              <Link
                key={driver.id}
                href={`/drivers/${driver.id}`}
                data-testid="driver-card"
                className="block rounded-card border border-line bg-card p-4 transition-transform hover:-translate-y-0.5 hover:border-accent"
              >
                <div className="flex items-center gap-3.5">
                  {stats?.is_new ? (
                    <div className="grid h-16 w-16 flex-none place-items-center rounded-full border-2 border-dashed border-line text-[11px] font-bold text-mut">{t("новичок")}</div>
                  ) : (
                    <ScoreRing value={stats?.score ?? 100} zone={stats?.zone ?? "ok"} />
                  )}
                  {driver.photo_url && <Avatar name={driver.name} size={40} src={driver.photo_url} />}
                  <div className="min-w-0">
                    <b className="block truncate text-[15px]">{driver.name}</b>
                    <span className="block truncate text-xs text-mut">
                      {driver.depot_name ?? t("Без депо")} · {driver.vehicle_plate ?? t("без машины")}
                    </span>
                    <span className="mt-1 flex items-center gap-1 text-xs">
                      {streak > 0 ? (
                        <span className="num flex items-center gap-1 font-bold text-warn">
                          <Flame size={13} /> {streak} {pluralRu(streak, t("день"), t("дня"), t("дней"))}
                        </span>
                      ) : (
                        <span className="text-mut">{t("серия прервана")}</span>
                      )}
                      <span className="text-mut">·</span>
                      <span className="num text-mut">{stats?.events ?? 0} {t("соб./нед.")}</span>
                    </span>
                  </div>
                </div>
              </Link>
            );
          })}
        </div>
      )}

      <DriverForm open={formOpen} onClose={() => setFormOpen(false)} />
    </div>
  );
}
