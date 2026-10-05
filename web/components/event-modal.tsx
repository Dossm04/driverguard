"use client";

/* Модалка события (WEB-4): клип из MinIO (если есть) или стилизованный ИК-кадр,
   метаданные, review-кнопки. Все цвета — токенами. */

import { useQuery } from "@tanstack/react-query";
import { Check, TriangleAlert, User, X } from "lucide-react";
import { useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { StatusPill } from "@/components/ui/status-pill";
import { api, type EventItem } from "@/lib/api";
import { EVENT_ICONS, STATUS_PILLS, eventTitle } from "@/lib/events";
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
  const clock = fleetTime(event.ts, true);

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
      <div className="w-full max-w-2xl rounded-card border border-line bg-card p-5 shadow-2xl">
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

        {/* Клип из MinIO; ошибки не прячем (правило 8 CLAUDE.md), без клипа — ИК-кадр */}
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
          <div
            className="relative grid aspect-video place-items-center overflow-hidden rounded-btn"
            style={{
              background:
                "radial-gradient(ellipse at 50% 42%, rgb(var(--ok) / 0.18) 0%, rgb(var(--bg)) 75%)",
            }}
          >
            <div
              className="pointer-events-none absolute inset-0"
              style={{
                background:
                  "repeating-linear-gradient(0deg, rgb(var(--txt) / 0.04) 0 1px, transparent 1px 3px)",
              }}
            />
            <User size={96} className="text-mut/60" />
            <span className="num absolute left-3 top-2.5 flex items-center gap-1.5 font-mono text-xs text-ok">
              <span className="h-2 w-2 animate-pulse rounded-full bg-danger" />
              {t("ИК ·")}{" "}{clock} · 640×480 · REC
            </span>
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
              {event.lat != null && event.lon != null ? (
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
            <dt className="text-mut">Confidence</dt>
            <dd className="font-semibold">{Math.round(event.confidence * 100)}%</dd>
          </div>
          {event.context?.source === "pwa_camera" && (
            <div className="flex justify-between gap-3">
              <dt className="text-mut">{t("Источник")}</dt>
              <dd className="font-semibold">{t("Камера телефона (PWA)")}</dd>
            </div>
          )}
        </dl>

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
          {t("«Ложное срабатывание» возвращает баллы водителю, а кадр автоматически уходит в датасет дообучения — модель становится точнее с каждой неделей.")}
        </p>
      </div>
    </div>
  );
}
