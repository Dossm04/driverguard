"use client";

/* Страница «События» (ШАГ 7, WEB-4): фильтры, таблица с пагинацией,
   review ✓/✗ с пересчётом Score без перезагрузки, экспорт CSV, модалка. */

import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { Check, ChevronLeft, ChevronRight, Download, Play, ShieldCheck, X } from "lucide-react";
import { useEffect, useMemo, useState } from "react";

import { EventModal, formatEventTime } from "@/components/event-modal";
import { Button } from "@/components/ui/button";
import { DataTable, type Column } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { QueryError } from "@/components/ui/query-error";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { useToast } from "@/components/ui/toast";
import { api, currentUser, type EventItem, saveBlob } from "@/lib/api";
import { EVENT_ICONS, EVENT_LABELS, STATUS_PILLS, eventTitle } from "@/lib/events";
import { t, perLang } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";
import { usePeriod } from "@/lib/period";
import { useReviewEvent } from "@/lib/queries";
import { fleetDayStart } from "@/lib/time";
import { cn } from "@/lib/utils";

const PAGE_SIZE = 20;

const STATUS_CHIPS = perLang(() => [
  { value: "", label: t("Все") },
  { value: "new", label: t("Новые") },
  { value: "confirmed", label: t("Подтверждённые") },
  { value: "false_positive", label: t("Ложные") },
] as const);

interface EventList {
  items: EventItem[];
  total: number;
  page: number;
  page_size: number;
}

interface DriverRow {
  id: number;
  name: string;
}

function periodFrom(period: "today" | "7d" | "30d"): string {
  const now = new Date();
  if (period === "today") {
    // календарный день парка (Asia/Almaty) — так же считает backend (APP_TZ)
    return fleetDayStart(now).toISOString();
  }
  const days = period === "7d" ? 7 : 30;
  return new Date(now.getTime() - days * 86_400_000).toISOString();
}

function buildParams(filters: {
  type: string;
  driverId: string;
  status: string;
  tsFrom: string;
  page: number;
  pageSize: number;
}): string {
  const params = new URLSearchParams();
  if (filters.type) params.set("type", filters.type);
  if (filters.driverId) params.set("driver_id", filters.driverId);
  if (filters.status) params.set("status", filters.status);
  params.set("ts_from", filters.tsFrom);
  params.set("page", String(filters.page));
  params.set("page_size", String(filters.pageSize));
  return params.toString();
}

function csvEscape(value: string): string {
  // Ячейка «=CMD()» / «+…» / «@…» в Excel — формула: экранируем апострофом (как backend)
  if (/^[=+\-@\t\r]/.test(value) && Number.isNaN(Number(value))) value = `'${value}`;
  return /[";\n]/.test(value) ? `"${value.replace(/"/g, '""')}"` : value;
}

export default function EventsPage() {
  useLangVersion();
  const { period } = usePeriod();
  const toast = useToast();
  const review = useReviewEvent();
  const [type, setType] = useState("");
  const [driverId, setDriverId] = useState("");
  const [status, setStatus] = useState("");
  const [page, setPage] = useState(1);
  const [selected, setSelected] = useState<EventItem | null>(null);
  const [exporting, setExporting] = useState(false);
  // Роль читаем в эффекте (localStorage нет при SSR — иначе расхождение гидрации)
  const [canReview, setCanReview] = useState(false);
  useEffect(() => {
    const role = currentUser()?.role;
    setCanReview(role === "admin" || role === "coordinator");
  }, []);

  const tsFrom = useMemo(() => periodFrom(period), [period]);
  const filters = { type, driverId, status, tsFrom, page, pageSize: PAGE_SIZE };

  const drivers = useQuery({
    queryKey: ["drivers"],
    queryFn: () => api<DriverRow[]>("/drivers"),
    staleTime: 60_000,
  });
  const events = useQuery({
    queryKey: ["events", type, driverId, status, tsFrom, page],
    queryFn: () => api<EventList>(`/events?${buildParams(filters)}`),
    placeholderData: keepPreviousData, // при листании не мигаем скелетоном
    refetchInterval: 15_000, // новые события с телефонов/устройств появляются без F5
  });

  const resetPage = () => setPage(1);
  const totalPages = events.data ? Math.max(1, Math.ceil(events.data.total / PAGE_SIZE)) : 1;
  // Смена периода в топбаре — на первую страницу; если после review/фильтра
  // страница выпала за пределы списка — прижимаем к последней (иначе ложное «Событий нет»)
  useEffect(() => setPage(1), [tsFrom]);
  useEffect(() => {
    if (events.data && page > totalPages) setPage(totalPages);
  }, [events.data, page, totalPages]);

  const doReview = (uuid: string, newStatus: "confirmed" | "false_positive") =>
    review.mutate(
      { uuid, status: newStatus },
      {
        onSuccess: (updated) =>
          setSelected((prev) => (prev?.uuid === uuid ? updated : prev)),
      },
    );

  const exportCsv = async () => {
    setExporting(true);
    try {
      // выгружаем ВСЕ страницы текущего фильтра (до 2000 строк)
      const rows: EventItem[] = [];
      let p = 1;
      let total = Infinity;
      while (rows.length < total && p <= 10) {
        const chunk = await api<EventList>(
          `/events?${buildParams({ ...filters, page: p, pageSize: 200 })}`,
        );
        total = chunk.total;
        rows.push(...chunk.items);
        p += 1;
      }
      const header = [
        "uuid",
        t("тип"),
        t("название"),
        "severity",
        t("водитель"),
        t("машина"),
        t("дата_время"),
        t("скорость_кмч"),
        "confidence",
        t("широта"),
        t("долгота"),
        t("статус"),
      ];
      const lines = rows.map((e) =>
        [
          e.uuid,
          e.type,
          eventTitle(e.type, e.value),
          e.severity,
          e.driver_name ?? "",
          e.vehicle_plate ?? "",
          new Date(e.ts).toISOString(),
          e.speed_kmh != null ? String(Math.round(e.speed_kmh)) : "",
          String(e.confidence),
          e.lat != null ? String(e.lat) : "",
          e.lon != null ? String(e.lon) : "",
          e.status,
        ]
          .map(csvEscape)
          .join(";"),
      );
      // BOM — чтобы Excel открыл кириллицу как UTF-8
      const blob = new Blob(["﻿" + [header.join(";"), ...lines].join("\r\n")], {
        type: "text/csv;charset=utf-8",
      });
      saveBlob(blob, t("driverguard_события.csv"));
      toast(
        rows.length < total
          ? t("Выгружены первые {0} из {1} — сузьте фильтры для полного списка", rows.length, total)
          : t("Экспортировано событий: {0}", rows.length),
      );
    } catch (e) {
      toast(e instanceof Error ? e.message : t("Не удалось выгрузить CSV"));
    } finally {
      setExporting(false);
    }
  };

  const columns: Column<EventItem>[] = [
    {
      key: "event",
      header: t("Событие"),
      render: (e) => {
        const Icon = EVENT_ICONS[e.type] ?? ShieldCheck;
        return (
          <span className="flex items-center gap-2.5">
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
            <b className="whitespace-nowrap">{eventTitle(e.type, e.value)}</b>
          </span>
        );
      },
    },
    {
      key: "driver",
      header: t("Водитель · машина"),
      render: (e) => (
        <span>
          {e.driver_name}
          <span className="num block text-xs text-mut">{e.vehicle_plate}</span>
        </span>
      ),
    },
    {
      key: "ts",
      header: t("Время"),
      render: (e) => <span className="num whitespace-nowrap">{formatEventTime(e.ts)}</span>,
    },
    {
      key: "speed",
      header: t("Скорость"),
      render: (e) => (
        <span className="num whitespace-nowrap">
          {e.speed_kmh != null ? t("{0} км/ч", Math.round(e.speed_kmh)) : "—"}
        </span>
      ),
    },
    {
      key: "conf",
      header: "Conf.",
      render: (e) => (
        <span className="block h-1.5 w-[70px] overflow-hidden rounded-full bg-cardh" title={String(e.confidence)}>
          <span
            className="block h-full rounded-full bg-accent"
            style={{ width: `${Math.round(e.confidence * 100)}%` }}
          />
        </span>
      ),
    },
    {
      key: "status",
      header: t("Статус"),
      render: (e) => {
        const pill = STATUS_PILLS[e.status];
        return <StatusPill tone={pill.tone}>{pill.label}</StatusPill>;
      },
    },
    {
      key: "actions",
      header: "",
      className: "text-right",
      render: (e) => (
        <span className="flex justify-end gap-1.5 whitespace-nowrap">
          {canReview && e.status !== "confirmed" && (
            <Button
              variant="ok"
              size="sm"
              aria-label={t("Подтвердить")}
              disabled={review.isPending}
              onClick={() => doReview(e.uuid, "confirmed")}
            >
              <Check size={14} />
            </Button>
          )}
          {canReview && e.status !== "false_positive" && (
            <Button
              variant="danger"
              size="sm"
              aria-label={t("Ложное")}
              disabled={review.isPending}
              onClick={() => doReview(e.uuid, "false_positive")}
            >
              <X size={14} />
            </Button>
          )}
          <Button variant="outline" size="sm" onClick={() => setSelected(e)}>
            <Play size={14} className="text-accent" /> {t("Клип")}
          </Button>
        </span>
      ),
    },
  ];

  return (
    <div className="flex flex-col gap-3">
      {/* Тулбар фильтров */}
      <div className="flex flex-wrap items-center gap-2.5 rounded-card border border-line bg-card p-3">
        <select
          aria-label={t("Фильтр по типу")}
          className="h-9 rounded-btn border border-line bg-cardh px-3 text-sm font-semibold"
          value={type}
          onChange={(e) => {
            setType(e.target.value);
            resetPage();
          }}
        >
          <option value="">{t("Все типы")}</option>
          {Object.entries(EVENT_LABELS).map(([value, label]) => (
            <option key={value} value={value}>
              {label}
            </option>
          ))}
        </select>
        <select
          aria-label={t("Фильтр по водителю")}
          className="h-9 rounded-btn border border-line bg-cardh px-3 text-sm font-semibold"
          value={driverId}
          onChange={(e) => {
            setDriverId(e.target.value);
            resetPage();
          }}
        >
          <option value="">{t("Все водители")}</option>
          {(drivers.data ?? []).map((d) => (
            <option key={d.id} value={d.id}>
              {d.name}
            </option>
          ))}
        </select>
        <div className="flex gap-1" role="tablist" aria-label={t("Статус")}>
          {STATUS_CHIPS.map((chip) => (
            <button
              key={chip.value}
              role="tab"
              aria-selected={status === chip.value}
              onClick={() => {
                setStatus(chip.value);
                resetPage();
              }}
              className={cn(
                "rounded-btn border border-line px-3 py-1.5 text-xs font-bold text-mut transition-colors hover:text-txt",
                status === chip.value && "border-accent bg-accent/10 text-accent",
              )}
            >
              {chip.label}
            </button>
          ))}
        </div>
        <Button
          variant="outline"
          className="ml-auto"
          disabled={exporting || !events.data?.total}
          onClick={exportCsv}
        >
          <Download size={16} />
          {exporting ? t("Выгружаем…") : t("Экспорт CSV")}
        </Button>
      </div>

      {/* Таблица */}
      <div className="rounded-card border border-line bg-card p-2">
        {events.isError ? (
          <QueryError error={events.error} onRetry={() => events.refetch()} />
        ) : events.isLoading ? (
          <div className="flex flex-col gap-2 p-2">
            {Array.from({ length: 6 }, (_, i) => (
              <Skeleton key={i} className="h-12" />
            ))}
          </div>
        ) : events.data && events.data.items.length > 0 ? (
          <>
            <DataTable
              columns={columns}
              rows={events.data.items}
              rowKey={(e) => e.uuid}
            />
            <div className="flex items-center justify-between px-2 py-2">
              <span className="num text-xs text-mut">
                {(page - 1) * PAGE_SIZE + 1}–
                {Math.min(page * PAGE_SIZE, events.data.total)} {t("из")}{" "}{events.data.total}
              </span>
              <span className="flex gap-1.5">
                <Button
                  variant="outline"
                  size="icon"
                  aria-label={t("Предыдущая страница")}
                  disabled={page <= 1}
                  onClick={() => setPage((p) => p - 1)}
                >
                  <ChevronLeft size={16} />
                </Button>
                <Button
                  variant="outline"
                  size="icon"
                  aria-label={t("Следующая страница")}
                  disabled={page >= totalPages}
                  onClick={() => setPage((p) => p + 1)}
                >
                  <ChevronRight size={16} />
                </Button>
              </span>
            </div>
          </>
        ) : (
          <EmptyState
            icon={ShieldCheck}
            title={t("Событий нет")}
            description={t("По выбранным фильтрам ничего не найдено — отличная смена.")}
          />
        )}
      </div>

      <EventModal
        event={selected}
        onClose={() => setSelected(null)}
        review={
          canReview
            ? {
                onReview: (s) => selected && doReview(selected.uuid, s),
                pending: review.isPending,
              }
            : undefined
        }
      />
    </div>
  );
}
