"use client";

/* Экран «Смена» (APP-2): статус устройства, «Начать рейс» (после чек-листа), таймер, км,
   перерыв с причинами, напоминание через 4 часа, «Завершить рейс». */

import { useMutation, useQueryClient } from "@tanstack/react-query";
import { Coffee, Flag, Play, RadioTower, Utensils, Fuel, BedDouble, Bath, ClipboardCheck } from "lucide-react";
import Link from "next/link";
import { useEffect, useState } from "react";

import { useDriverMe } from "@/components/driver/data";
import { BigButton, Card, DriverHeader } from "@/components/driver/shell";
import { QueryError } from "@/components/ui/query-error";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill } from "@/components/ui/status-pill";
import { useToast } from "@/components/ui/toast";
import { api, ApiError, type BreakReason, type DriverMe } from "@/lib/api";
import { formatEventTime } from "@/components/event-modal";
import { t, perLang } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";

const BREAKS: { reason: BreakReason; label: string; icon: typeof Coffee }[] = perLang(() => [
  { reason: "устал", label: t("Устал"), icon: BedDouble },
  { reason: "туалет", label: t("Туалет"), icon: Bath },
  { reason: "еда", label: t("Еда"), icon: Utensils },
  { reason: "заправка", label: t("Заправка"), icon: Fuel },
]);
const REMIND_AFTER_MS = 4 * 3600 * 1000;

function useNow(tick = 1000) {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now()), tick);
    return () => clearInterval(id);
  }, [tick]);
  return now;
}

function hms(ms: number) {
  const s = Math.max(0, Math.floor(ms / 1000));
  const h = Math.floor(s / 3600);
  const m = Math.floor((s % 3600) / 60);
  return `${h}:${String(m).padStart(2, "0")}:${String(s % 60).padStart(2, "0")}`;
}

function isToday(iso: string) {
  const d = new Date(iso);
  const n = new Date();
  return d.getFullYear() === n.getFullYear() && d.getMonth() === n.getMonth() && d.getDate() === n.getDate();
}

export default function ShiftPage() {
  useLangVersion();
  const me = useDriverMe();
  const toast = useToast();
  const qc = useQueryClient();
  const now = useNow();
  const [pickBreak, setPickBreak] = useState(false);
  const [confirmStop, setConfirmStop] = useState(false);
  const invalidate = () => qc.invalidateQueries({ queryKey: ["driver-me"] });
  const fail = (e: unknown) => toast(e instanceof Error ? e.message : t("Не получилось, попробуйте ещё раз"));

  const start = useMutation({
    mutationFn: (d: DriverMe) =>
      api("/trips/start", {
        method: "POST",
        body: JSON.stringify({ driver_id: d.driver.id, vehicle_id: d.driver.vehicle?.id, device_id: d.device?.id ?? null }),
      }),
    onSuccess: () => {
      toast(t("Рейс начат. Хорошей дороги!"));
      invalidate();
    },
    onError: fail,
  });
  const startBreak = useMutation({
    mutationFn: ({ tripId, reason }: { tripId: number; reason: BreakReason }) =>
      api(`/trips/${tripId}/breaks`, { method: "POST", body: JSON.stringify({ reason }) }),
    onSuccess: () => {
      setPickBreak(false);
      toast(t("Перерыв начат. Отдохните как следует"));
      invalidate();
    },
    onError: fail,
  });
  const endBreak = useMutation({
    mutationFn: (tripId: number) => api(`/trips/${tripId}/breaks/end`, { method: "POST" }),
    onSuccess: () => {
      toast(t("Продолжаем рейс"));
      invalidate();
    },
    onError: fail,
  });
  const stop = useMutation({
    mutationFn: (tripId: number) => api(`/trips/${tripId}/stop`, { method: "POST" }),
    onSuccess: () => {
      setConfirmStop(false);
      toast(t("Рейс завершён. Спасибо за работу!"));
      invalidate();
    },
    onError: fail,
  });

  if (me.isError) {
    const notDriver = me.error instanceof ApiError && me.error.status === 404;
    return (
      <>
        <DriverHeader title={t("Смена")} />
        <div className="p-4">
          {notDriver ? (
            <Card>
              <div className="text-lg font-extrabold">{t("Это приложение для водителей")}</div>
              <p className="mt-1 text-mut">{t("Учётная запись не привязана к водителю. Панель координатора — на главной странице.")}</p>
            </Card>
          ) : (
            <QueryError error={me.error} onRetry={() => me.refetch()} />
          )}
        </div>
      </>
    );
  }
  const d = me.data;
  if (!d) {
    return (
      <>
        <DriverHeader title={t("Смена")} />
        <div className="flex flex-col gap-3 p-4">
          <Skeleton className="h-24 rounded-card" />
          <Skeleton className="h-40 rounded-card" />
        </div>
      </>
    );
  }

  const trip = d.active_trip;
  const checklistOk = Boolean(d.last_checklist && isToday(d.last_checklist.created_at) && d.last_checklist.verdict !== "не_допущен");
  const blocked = d.last_checklist && isToday(d.last_checklist.created_at) && d.last_checklist.verdict === "не_допущен";
  const elapsed = trip ? now - new Date(trip.started_at).getTime() : 0;
  const sinceRest = trip ? now - new Date(trip.last_break_end ?? trip.started_at).getTime() : 0;
  const remind = Boolean(trip && !trip.break && sinceRest >= REMIND_AFTER_MS);

  return (
    <>
      <DriverHeader title={d.driver.name} />
      <div className="flex flex-col gap-3 p-4">
        <p className="text-mut">
          {t("Здравствуйте!")}{" "}{trip ? t("Вы в рейсе — берегите себя.") : t("Готовы к выезду? Сначала быстрый чек-лист.")}
        </p>
        <Card className="flex items-center gap-3">
          <div className="grid h-12 w-12 place-items-center rounded-btn bg-accent/15 text-accent">
            <RadioTower size={24} />
          </div>
          <div className="min-w-0 flex-1">
            <div className="font-extrabold">{d.driver.vehicle ? `${d.driver.vehicle.plate} · ${d.driver.vehicle.model}` : t("Машина не закреплена")}</div>
            <div className="text-sm text-mut">
              {d.device ? t("Устройство {0}", d.device.serial) : t("Устройства в кабине нет")}
              {d.device?.last_seen ? ` · ${formatEventTime(d.device.last_seen)}` : ""}
            </div>
          </div>
          {d.device && (
            <StatusPill tone={d.device.online ? "ok" : "offline"}>{d.device.online ? t("Онлайн") : t("Офлайн")}</StatusPill>
          )}
        </Card>

        {!trip ? (
          <Card className="flex flex-col gap-3">
            <div className="text-sm font-bold text-mut">{t("Перед выездом")}</div>
            {checklistOk ? (
              <div className="flex items-center gap-2 text-ok">
                <ClipboardCheck size={22} /> {t("Чек-лист на сегодня пройден")}
              </div>
            ) : blocked ? (
              <div className="rounded-btn bg-danger/10 px-4 py-3 text-danger">
                {t("Машина сегодня не допущена к рейсу. Свяжитесь с координатором, он поможет.")}
              </div>
            ) : (
              <Link href="/driver/checklist" className="flex min-h-14 items-center gap-2 rounded-btn bg-warn/15 px-4 font-bold text-warn">
                <ClipboardCheck size={22} /> {t("Сначала пройдите чек-лист (7 фото)")}
              </Link>
            )}
            <BigButton className="min-h-24 text-2xl" disabled={!checklistOk || start.isPending} onClick={() => start.mutate(d)}>
              <Play /> {start.isPending ? t("Начинаем…") : t("Начать рейс")}
            </BigButton>
          </Card>
        ) : (
          <>
            <Card className="text-center">
              <div className="text-sm font-bold text-mut">{trip.break ? t("Перерыв") : t("В пути")}</div>
              <div className="num mt-1 text-5xl font-extrabold tabular-nums" aria-live="off">
                {hms(trip.break ? now - new Date(trip.break.started_at).getTime() : elapsed)}
              </div>
              <div className="mt-2 flex justify-center gap-6 text-mut">
                <span>
                  <b className="num text-txt">{Math.round(trip.distance_km)}</b> {t("км")}
                </span>
                <span>
                  {t("начали в")}{" "}<b className="num text-txt">{formatEventTime(trip.started_at)}</b>
                </span>
              </div>
            </Card>

            {remind && (
              <div role="status" className="rounded-card bg-warn/15 px-4 py-3 font-bold text-warn">
                {t("Вы за рулём уже 4 часа. Самое время сделать перерыв — дорога подождёт.")}
              </div>
            )}

            {trip.break ? (
              <Card className="flex flex-col gap-3">
                <div>
                  {t("Причина:")}{" "}<b>{t(trip.break.reason)}</b> {t("· с")}{" "}{formatEventTime(trip.break.started_at)}
                </div>
                <BigButton tone="ok" disabled={endBreak.isPending} onClick={() => endBreak.mutate(trip.id)}>
                  <Play /> {t("Продолжить рейс")}
                </BigButton>
              </Card>
            ) : pickBreak ? (
              <Card className="flex flex-col gap-3">
                <div className="font-bold">{t("Почему останавливаемся?")}</div>
                <div className="grid grid-cols-2 gap-2">
                  {BREAKS.map((b) => (
                    <button
                      key={b.reason}
                      type="button"
                      disabled={startBreak.isPending}
                      onClick={() => startBreak.mutate({ tripId: trip.id, reason: b.reason })}
                      className="flex min-h-20 flex-col items-center justify-center gap-1 rounded-card border border-line bg-page font-bold hover:bg-cardh"
                    >
                      <b.icon size={26} className="text-accent" /> {b.label}
                    </button>
                  ))}
                </div>
                <BigButton tone="outline" onClick={() => setPickBreak(false)}>
                  {t("Отмена")}
                </BigButton>
              </Card>
            ) : (
              <BigButton tone="outline" onClick={() => setPickBreak(true)}>
                <Coffee /> {t("Перерыв")}
              </BigButton>
            )}

            {confirmStop ? (
              <Card className="flex flex-col gap-3">
                <div className="font-bold">{t("Завершить рейс?")}</div>
                <BigButton tone="danger" disabled={stop.isPending} onClick={() => stop.mutate(trip.id)}>
                  <Flag /> {t("Да, завершить")}
                </BigButton>
                <BigButton tone="outline" onClick={() => setConfirmStop(false)}>
                  {t("Ещё в пути")}
                </BigButton>
              </Card>
            ) : (
              <BigButton tone="outline" className="text-danger" onClick={() => setConfirmStop(true)}>
                <Flag /> {t("Завершить рейс")}
              </BigButton>
            )}
          </>
        )}
      </div>
    </>
  );
}
