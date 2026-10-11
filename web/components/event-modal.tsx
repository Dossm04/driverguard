"use client";

/* Реальные параметры события и клип, если он загружен. Все цвета — токенами. */

import { useQuery } from "@tanstack/react-query";
import { Check, TriangleAlert, User, X } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { StatusPill } from "@/components/ui/status-pill";
import { api, type EventItem } from "@/lib/api";
import { EVENT_ICONS, STATUS_PILLS, eventTitle } from "@/lib/events";
import { measurementRows } from "@/lib/event-measurements";
import { t } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";
import { fleetDate, fleetDayMonth, fleetTime } from "@/lib/time";

/** Время события по поясу парка: «14:32», «Вчера 14:32» или «03.09 14:32». */
export function formatEventTime(ts: string): string {
  const d = new Date(ts);
  const now = new Date();
  const time = fleetTime(d);
  const day = fleetDate(d);
  if (day === fleetDate(now)) return time;
  if (day === fleetDate(new Date(now.getTime() - 86_400_000))) return t("Вчера {0}", time);
  return `${fleetDayMonth(d)} ${time}`;
}

export interface ReviewActions {
  onReview: (status: "confirmed" | "false_positive") => void;
  pending: boolean;
}

export function EventModal({
  event,
  onClose,
  review,
}: {
  event: EventItem | null;
  onClose: () => void;
  /** Кнопки review показываются, только если передан обработчик (страница «События»). */
  review?: ReviewActions;
}) {
  useLangVersion();
  const clip = useQuery({
    queryKey: ["clip-url", event?.uuid],
    queryFn: () => api<{ url: string }>(`/events/${event!.uuid}/clip-url`),
    enabled: Boolean(event?.clip_key),
    staleTime: 5 * 60_000, // presigned живёт 10 минут
  });
  // Битый файл в хранилище (video onError) — говорим честно, а не показываем чёрный экран
  const [videoBroken, setVideoBroken] = useState(false);
  useEffect(() => setVideoBroken(false), [event?.uuid]);
  useEffect(() => {
    if (!event) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [event, onClose]);

  if (!event) return null;
  const Icon = EVENT_ICONS[event.type] ?? User;
  const pill = STATUS_PILLS[event.status];
  const readings = measurementRows(event.measurements);
  const uncalibrated = event.context?.confidence_status === "uncalibrated"
    || ["face_rules", "hand_gesture", "gps_rules"].includes(String(event.context?.detector));

  return (
    <div
      className="fixed inset-0 z-[105] flex items-center justify-center p-4"
      role="dialog"
      aria-label={t("Событие: {0}", eventTitle(event.type, event.value))}
      onClick={(e) => {
        if (e.target === e.currentTarget) onClose();
      }}
      style={{ background: "rgb(var(--bg) / 0.75)" }}
    >
      <div className="max-h-[90dvh] w-full max-w-2xl overflow-y-auto rounded-card border border-line bg-card p-5 shadow-2xl">
        <div className="mb-4 flex items-center gap-3">
          <div className="grid h-9 w-9 flex-none place-items-center rounded-btn bg-danger/15 text-danger">
            <Icon size={18} />
          </div>
          <h3 className="text-base font-bold">{eventTitle(event.type, event.value)}</h3>
          <StatusPill tone={pill.tone}>{pill.label}</StatusPill>
          <Button variant="ghost" size="icon" className="ml-auto" aria-label={t("Закрыть")} onClick={onClose}>
            <X size={18} />
          </Button>
        </div>

        {/* Отсутствие клипа не подменяется фиктивным кадром камеры. */}
        {event.clip_key && (clip.isError || videoBroken) ? (
          <div className="grid aspect-video w-full place-items-center rounded-btn border border-danger/40 bg-danger/10 p-4 text-center">
            <span className="flex flex-col items-center gap-2 text-sm font-semibold text-danger">
              <TriangleAlert size={28} />
              {videoBroken
                ? t("Клип недоступен: файл не читается или удалён из хранилища")
                : clip.error instanceof Error
                  ? clip.error.message
                  : t("Не удалось получить ссылку на клип")}
            </span>
          </div>
        ) : event.clip_key && clip.data?.url ? (
          <video
            src={clip.data.url}
            controls
            className="aspect-video w-full rounded-btn bg-page"
            aria-label={t("Видеоклип события")}
            onError={() => setVideoBroken(true)}
          />
        ) : (
          <div className="rounded-btn border border-line bg-page p-5 text-center text-sm text-mut">
            {event.clip_key ? t("Загрузка видеоклипа…") : t("Видеоклип не загружен")}
          </div>
        )}

        <dl className="num mt-4 grid grid-cols-1 gap-x-6 gap-y-1.5 text-sm sm:grid-cols-2">
          <div className="flex justify-between gap-3">
            <dt className="text-mut">{t("Водитель")}</dt>
            <dd className="text-right font-semibold">
              {event.driver_name ?? "—"}
              {event.driver_phone && (
                <span className="block text-xs font-normal text-mut">{event.driver_phone}</span>
              )}
            </dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-mut">{t("Машина")}</dt>
            <dd className="font-semibold">{event.vehicle_plate ?? "—"}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-mut">{t("Время")}</dt>
            <dd className="font-semibold">{formatEventTime(event.ts)}</dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-mut">{t("Скорость")}</dt>
            <dd className="font-semibold">
              {event.speed_kmh != null ? t("{0} км/ч", Math.round(event.speed_kmh)) : "—"}
            </dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-mut">{t("Координаты")}</dt>
            <dd className="font-semibold">
              {event.gps_valid && event.lat != null && event.lon != null ? (
                <a
                  className="text-accent hover:underline"
                  target="_blank"
                  rel="noreferrer"
                  href={`https://www.openstreetmap.org/?mlat=${event.lat}&mlon=${event.lon}#map=12/${event.lat}/${event.lon}`}
                >
                  {event.lat}, {event.lon}
                </a>
              ) : (
                "—"
              )}
            </dd>
          </div>
          <div className="flex justify-between gap-3">
            <dt className="text-mut">{t("Оценка уверенности")}</dt>
            <dd className="text-right font-semibold">
              {uncalibrated ? t("Не калибрована") : `${Math.round(event.confidence * 100)}%`}
            </dd>
          </div>
          {["pwa_camera", "android_camera"].includes(String(event.context?.source)) && (
            <div className="flex justify-between gap-3">
              <dt className="text-mut">{t("Источник")}</dt>
              <dd className="font-semibold">
                {event.context?.source === "android_camera"
                  ? t("Приложение Android") : t("Камера телефона (PWA)")}
              </dd>
            </div>
          )}
        </dl>

        {readings.length > 0 && (
          <section className="mt-4 rounded-btn border border-line bg-page p-4">
            <h4 className="text-sm font-semibold">{t("Измерения в момент события")}</h4>
            <dl className="num mt-3 grid grid-cols-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
              {readings.map((reading) => (
                <div key={reading.key} className="flex justify-between gap-3">
                  <dt className="text-mut">{reading.label}</dt>
                  <dd className="whitespace-nowrap text-right font-semibold">{reading.value}</dd>
                </div>
              ))}
            </dl>
            {event.measurements?.rule_version && (
              <p className="mt-3 text-xs text-mut">
                {t("Версия правил")}: {event.measurements.rule_version}
              </p>
            )}
            <p className="mt-2 text-xs leading-relaxed text-mut">
              {t("Это наблюдения устройства, а не подтверждение сна или медицинский диагноз.")}
            </p>
          </section>
        )}
        {typeof event.context?.note === "string" && event.context.note && (
          <p className="mt-4 whitespace-pre-wrap break-words text-sm leading-relaxed text-mut">
            {event.context.note}
          </p>
        )}

        {review && (
          <div className="mt-4 flex flex-wrap gap-2">
            {event.status !== "confirmed" && (
              <Button
                variant="ok"
                size="sm"
                disabled={review.pending}
                onClick={() => review.onReview("confirmed")}
              >
                <Check size={14} /> {t("Подтвердить")}
              </Button>
            )}
            {event.status !== "false_positive" && (
              <Button
                variant="danger"
                size="sm"
                disabled={review.pending}
                onClick={() => review.onReview("false_positive")}
              >
                <X size={14} /> {t("Ложное срабатывание")}
              </Button>
            )}
          </div>
        )}
        <p className="mt-4 text-xs leading-relaxed text-mut">
          {t("«Ложное срабатывание» исключает событие из оценки водителя и добавляет его в очередь проверки. Дообучение проводится отдельно после проверки данных.")}
        </p>
      </div>
    </div>
  );
}
