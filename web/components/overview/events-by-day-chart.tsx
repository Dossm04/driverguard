"use client";

/* «События по дням · Последние 7 дней»: сгруппированные столбики
   Критические (--danger) и Предупреждения (--warn), как в Figma. */

import { useQuery } from "@tanstack/react-query";
import {
  Bar,
  BarChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from "recharts";

import { SectionCard } from "@/components/ui/section-card";
import { Skeleton } from "@/components/ui/skeleton";
import { QueryError } from "@/components/ui/query-error";
import { api, type DayPoint } from "@/lib/api";
import { t, localeTag } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";
import { useTokenColors } from "@/lib/use-token-colors";

function LegendDot({ color, label }: { color: string; label: string }) {
  return (
    <span className="flex items-center gap-1.5 text-xs font-semibold text-mut">
      <span className="h-2 w-2 rounded-full" style={{ background: color }} />
      {label}
    </span>
  );
}

export function EventsByDayChart() {
  useLangVersion();
  const colors = useTokenColors(["--danger", "--warn", "--line", "--mut", "--card", "--txt"]);
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["events-by-day"],
    queryFn: () => api<DayPoint[]>("/dashboard/events-by-day?days=7"),
    refetchInterval: 60_000,
  });

  const points = (data ?? []).map((d) => ({
    day: new Date(d.date + "T00:00:00").toLocaleDateString(localeTag(), {
      day: "2-digit",
      month: "2-digit",
    }),
    Критические: d.critical,
    Предупреждения: d.warning,
  }));

  return (
    <SectionCard
      title={t("События по дням")}
      subtitle={t("Последние 7 дней")}
      action={
        colors && (
          <div className="flex gap-4">
            <LegendDot color={colors["--danger"]} label={t("Критические")} />
            <LegendDot color={colors["--warn"]} label={t("Предупреждения")} />
          </div>
        )
      }
    >
      {isError ? (
        <QueryError error={error} onRetry={() => refetch()} />
      ) : isLoading || !colors ? (
        <Skeleton className="h-[220px]" />
      ) : (
        <div className="h-[220px]">
          <ResponsiveContainer width="100%" height="100%">
            <BarChart data={points} barGap={2} margin={{ top: 4, right: 4, left: -18, bottom: 0 }}>
              <CartesianGrid vertical={false} stroke={colors["--line"]} strokeOpacity={0.6} />
              <XAxis
                dataKey="day"
                tickLine={false}
                axisLine={false}
                tick={{ fill: colors["--mut"], fontSize: 11 }}
              />
              <YAxis
                allowDecimals={false}
                tickLine={false}
                axisLine={false}
                tick={{ fill: colors["--mut"], fontSize: 11 }}
              />
              <Tooltip
                cursor={{ fill: colors["--line"], opacity: 0.25 }}
                contentStyle={{
                  background: colors["--card"],
                  border: `1px solid ${colors["--line"]}`,
                  borderRadius: 12,
                  color: colors["--txt"],
                  fontSize: 12,
                }}
                labelStyle={{ color: colors["--mut"], fontWeight: 700 }}
              />
              <Bar dataKey={t("Критические")} fill={colors["--danger"]} radius={[4, 4, 0, 0]} maxBarSize={18} isAnimationActive={false} />
              <Bar dataKey={t("Предупреждения")} fill={colors["--warn"]} radius={[4, 4, 0, 0]} maxBarSize={18} isAnimationActive={false} />
            </BarChart>
          </ResponsiveContainer>
        </div>
      )}
    </SectionCard>
  );
}
