"use client";

/* «События по типам · Доля от общего»: donut с зазорами между сегментами
   и подписанной легендой (цвет закреплён за типом — lib/events.ts). */

import { useQuery } from "@tanstack/react-query";
import { Cell, Pie, PieChart, Tooltip } from "recharts";

import { EmptyState } from "@/components/ui/empty-state";
import { SectionCard } from "@/components/ui/section-card";
import { Skeleton } from "@/components/ui/skeleton";
import { QueryError } from "@/components/ui/query-error";
import { api, type TypeShare } from "@/lib/api";
import { EVENT_LABELS, eventTypeColorVar } from "@/lib/events";
import { t } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";
import { useTokenColors } from "@/lib/use-token-colors";
import { ChartPie } from "lucide-react";

const CAT_VARS = [
  "--cat-1",
  "--cat-2",
  "--cat-3",
  "--cat-4",
  "--cat-5",
  "--cat-6",
  "--cat-7",
  "--cat-8",
  "--offline",
  "--card",
  "--line",
  "--txt",
  "--mut",
];

export function EventsByTypeDonut() {
  useLangVersion();
  const colors = useTokenColors(CAT_VARS);
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["events-by-type"],
    queryFn: () => api<TypeShare[]>("/dashboard/events-by-type?days=7"),
    refetchInterval: 60_000,
  });

  const rows = (data ?? []).map((t) => ({
    ...t,
    label: EVENT_LABELS[t.type] ?? t.type,
    color: colors?.[eventTypeColorVar(t.type)] ?? "",
  }));

  return (
    <SectionCard title={t("События по типам")} subtitle={t("Доля от общего · 7 дней")}>
      {isError ? (
        <QueryError error={error} onRetry={() => refetch()} />
      ) : isLoading || !colors ? (
        <Skeleton className="h-[220px]" />
      ) : rows.length === 0 ? (
        <EmptyState icon={ChartPie} title={t("Событий нет")} description={t("За неделю ничего не зафиксировано.")} />
      ) : (
        <div className="flex items-center gap-4">
          {/* фиксированный размер: ResponsiveContainer во flex измеряет ширину нулём */}
          <PieChart width={200} height={200} className="flex-none">
            <Pie
              data={rows}
              dataKey="count"
              nameKey="label"
              innerRadius={62}
              outerRadius={94}
              paddingAngle={2}
              stroke={colors["--card"]}
              strokeWidth={2}
              isAnimationActive={false}
            >
              {rows.map((r) => (
                <Cell key={r.type} fill={r.color} />
              ))}
            </Pie>
            <Tooltip
              formatter={(value, name, item) => [
                `${value} · ${(item.payload as TypeShare).share_pct}%`,
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
          <ul className="flex min-w-0 flex-1 flex-col gap-1.5">
            {rows.map((r) => (
              <li key={r.type} className="flex items-center gap-2 text-xs">
                <span className="h-2 w-2 flex-none rounded-full" style={{ background: r.color }} />
                <span className="truncate font-semibold text-mut">{r.label}</span>
                <span className="num ml-auto font-bold">{r.share_pct}%</span>
              </li>
            ))}
          </ul>
        </div>
      )}
    </SectionCard>
  );
}
