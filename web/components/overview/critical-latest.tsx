"use client";

/* «Последние критические» — по Figma: красная иконка типа, водитель · номер,
   время с часами, кнопка «Открыть» → модалка события. */

import { useQuery } from "@tanstack/react-query";
import { CheckCircle2, Clock3, Eye } from "lucide-react";
import { useState } from "react";

import { EventModal, formatEventTime } from "@/components/event-modal";
import { Button } from "@/components/ui/button";
import { EmptyState } from "@/components/ui/empty-state";
import { SectionCard } from "@/components/ui/section-card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { QueryError } from "@/components/ui/query-error";
import { api, type EventItem } from "@/lib/api";
import { EVENT_ICONS, eventTitle } from "@/lib/events";
import { t } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";
import { pluralRu } from "@/lib/utils";

export function CriticalLatest() {
  useLangVersion();
  const [selected, setSelected] = useState<EventItem | null>(null);
  const { data, isLoading, isError, error, refetch } = useQuery({
    queryKey: ["critical-latest"],
    queryFn: () => api<EventItem[]>("/dashboard/critical-latest?limit=3"),
    refetchInterval: 30_000,
  });

  return (
    <SectionCard
      title={t("Последние критические")}
      action={
        data && data.length > 0 ? (
          <StatusPill tone="danger">
            {data.length} {pluralRu(data.length, t("событие"), t("события"), t("событий"))}
          </StatusPill>
        ) : undefined
      }
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
          icon={CheckCircle2}
          title={t("Критических событий нет")}
          description={t("Отличная работа парка — ни одного критического события.")}
        />
      ) : (
        <ul>
          {data.map((e) => {
            const Icon = EVENT_ICONS[e.type] ?? Clock3;
            return (
              <li
                key={e.uuid}
                className="flex items-center gap-3 border-b border-line/60 py-2.5 last:border-b-0"
              >
                <div className="grid h-9 w-9 flex-none place-items-center rounded-btn bg-danger/15 text-danger">
                  <Icon size={18} />
                </div>
                <div className="min-w-0">
                  <div className="truncate text-sm font-bold">
                    {eventTitle(e.type, e.value)}
                  </div>
                  <div className="truncate text-xs text-mut">
                    {e.driver_name} · <span className="num">{e.vehicle_plate}</span>
                  </div>
                </div>
                <span className="num ml-auto flex flex-none items-center gap-1 text-xs text-mut">
                  <Clock3 size={14} />
                  {formatEventTime(e.ts)}
                </span>
                <Button variant="outline" size="sm" onClick={() => setSelected(e)}>
                  <Eye size={14} className="text-accent" />
                  {t("Открыть")}
                </Button>
              </li>
            );
          })}
        </ul>
      )}
      <EventModal event={selected} onClose={() => setSelected(null)} />
    </SectionCard>
  );
}
