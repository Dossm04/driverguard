"use client";

/* «Водители в красной зоне» (30-дневный Score < 60): аватар, ФИО, поездки,
   крупный Score, «Назначить обучение» → POST trainings + toast. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, GraduationCap, PartyPopper } from "lucide-react";
import { useState } from "react";

import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { SectionCard } from "@/components/ui/section-card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { useToast } from "@/components/ui/toast";
import { QueryError } from "@/components/ui/query-error";
import { api, type RedZoneRow } from "@/lib/api";
import { t } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";
import { pluralRu } from "@/lib/utils";

export function RedZone() {
  useLangVersion();
  const toast = useToast();
  const queryClient = useQueryClient();
  const [assigned, setAssigned] = useState<Set<number>>(new Set());
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["red-zone"],
    queryFn: () => api<RedZoneRow[]>("/dashboard/red-zone"),
    refetchInterval: 60_000,
  });

  const assign = useMutation({
    mutationFn: (row: RedZoneRow) =>
      api<{ training: string }>(`/drivers/${row.driver_id}/trainings`, {
        method: "POST",
        body: JSON.stringify({}),
      }),
    onSuccess: (result, row) => {
      toast(t("Микрообучение «{0}» назначено: {1}", result.training, row.name));
      setAssigned((prev) => new Set(prev).add(row.driver_id));
      queryClient.invalidateQueries({ queryKey: ["red-zone"] });
    },
    onError: (e) => toast(e instanceof Error ? e.message : t("Не удалось назначить обучение")),
  });

  return (
    <SectionCard
      title={t("Водители в красной зоне")}
      action={<StatusPill tone="warn">Score &lt;60</StatusPill>}
    >
      {isError ? (
        <QueryError error={error} onRetry={() => refetch()} />
      ) : isLoading ? (
        <div className="flex flex-col gap-2">
          {Array.from({ length: 3 }, (_, i) => (
            <Skeleton key={i} className="h-14" />
          ))}
        </div>
      ) : !data || data.length === 0 ? (
        <EmptyState
          icon={PartyPopper}
          title={t("Никого")}
          description={t("По доступным данным водителей в красной зоне нет.")}
        />
      ) : (
        <ul>
          {data.map((row) => {
            const tone = row.score < 55 ? "danger" : "warn";
            return (
              <li
                key={row.driver_id}
                className="flex items-center gap-3 border-b border-line/60 py-2.5 last:border-b-0"
              >
                <Avatar name={row.name} ring={tone} />
                <div className="min-w-0">
                  <div className="truncate text-sm font-bold">{row.name}</div>
                  <div className="num text-xs text-mut">
                    {row.trips_30d} {pluralRu(row.trips_30d, t("поездка"), t("поездки"), t("поездок"))}
                  </div>
                </div>
                <span
                  className={`num ml-auto text-xl font-extrabold ${
                    tone === "danger" ? "text-danger" : "text-warn"
                  }`}
                >
                  {row.score}
                </span>
                {assigned.has(row.driver_id) ? (
                  <Button variant="outline" size="sm" disabled>
                    <CheckCircle2 size={14} className="text-ok" />
                    {t("Назначено")}
                  </Button>
                ) : (
                  <Button
                    variant="danger"
                    size="sm"
                    disabled={assign.isPending}
                    onClick={() => assign.mutate(row)}
                  >
                    <GraduationCap size={14} />
                    {t("Назначить обучение")}
                  </Button>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </SectionCard>
  );
}
