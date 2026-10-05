"use client";

/* Общие data-хуки панели (единственная точка входа для /dashboard/summary). */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";

import { useToast } from "@/components/ui/toast";
import { api, type EventItem, type Period, type SummaryOut } from "@/lib/api";
import { t } from "@/lib/i18n";

export function useSummary(period: Period = "today") {
  return useQuery({
    queryKey: ["summary", period],
    queryFn: () => api<SummaryOut>(`/dashboard/summary?period=${period}`),
    refetchInterval: 30_000,
  });
}

/** Review события (US-7): после ответа сервера инвалидируются дашборд,
    лидерборд и списки — Score пересчитывается без перезагрузки. */
export function useReviewEvent() {
  const queryClient = useQueryClient();
  const toast = useToast();
  return useMutation({
    mutationFn: ({ uuid, status }: { uuid: string; status: "confirmed" | "false_positive" }) =>
      api<EventItem>(`/events/${uuid}/review`, {
        method: "POST",
        body: JSON.stringify({ status }),
      }),
    onSuccess: (_event, vars) => {
      toast(
        vars.status === "false_positive"
          ? t("Помечено как ложное — баллы возвращены водителю, кадр ушёл в датасет дообучения")
          : t("Событие подтверждено — учтено в скоринге водителя"),
      );
      for (const key of [
        "events",
        "summary",
        "red-zone",
        "critical-latest",
        "leaderboard",
        "events-by-day",
        "events-by-type",
        "driver-profile",
        "report",
      ]) {
        queryClient.invalidateQueries({ queryKey: [key] });
      }
    },
    onError: (e) => toast(e instanceof Error ? e.message : t("Не удалось выполнить review")),
  });
}
