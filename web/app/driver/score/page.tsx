"use client";

/* «Мой Score» (APP-4, SEC-5): кольцо, серия, мини-лидерборд «я и ±2», лента с советами,
   что именно хранится о водителе. Тон — «второй пилот». */

import { useQuery } from "@tanstack/react-query";
import { Flame, ShieldCheck } from "lucide-react";

import { useDriverMe } from "@/components/driver/data";
import { Card, DriverHeader } from "@/components/driver/shell";
import { formatEventTime } from "@/components/event-modal";
import { QueryError } from "@/components/ui/query-error";
import { ScoreRing } from "@/components/ui/score-ring";
import { Skeleton } from "@/components/ui/skeleton";
import { api, type LeaderboardOut } from "@/lib/api";
import { EVENT_ICONS, eventTitle } from "@/lib/events";
import { t, perLang } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";
import { cn, pluralRu } from "@/lib/utils";

const ZONE_TEXT = perLang(() => ({
  ok: { title: t("Отличная неделя!"), text: t("Так держать — вы в зелёной зоне.") },
  warn: { title: t("Хорошо, есть куда расти"), text: t("Пара спокойных дней — и снова зелёная зона.") },
  danger: { title: t("Сложная неделя"), text: t("Бывает. Ниже — что помогает быстрее всего. Мы на вашей стороне.") },
}) as const);

const ADVICE: Record<string, string> = perLang(() => ({
  microsleep: t("Остановитесь и подремлите 20 минут — это работает лучше кофе."),
  distraction: t("Три секунды в сторону на 90 км/ч — это 75 метров вслепую. Взгляд на дорогу."),
  phone: t("Телефон подождёт: включите автоответ или остановитесь на обочине."),
  smoking: t("Перекур лучше на стоянке — и безопаснее, и приятнее."),
  seatbelt: t("Ремень — две секунды, которые спасают."),
  speeding: t("Плюс 10 км/ч экономят минуты, а риск растёт вдвое."),
  fatigue: t("Глаза устают — это сигнал сделать перерыв, а не ускориться."),
  head_nod: t("Клевок головой — организм просит сна. Ближайшая стоянка — ваша."),
  camera_sabotage: t("Камера — ваш свидетель в спорной ситуации. Пусть видит дорогу."),
  harsh_braking: t("Чуть больше дистанции — и тормозить получится плавнее."),
  sos: t("Вы вызвали помощь — правильно сделали."),
}));

export default function ScorePage() {
  useLangVersion();
  const me = useDriverMe();
  const lb = useQuery({ queryKey: ["leaderboard", "7"], queryFn: () => api<LeaderboardOut>("/leaderboard?period=7") });
  if (me.isError) {
    return (
      <>
        <DriverHeader title={t("Мой Score")} />
        <div className="p-4">
          <QueryError error={me.error} onRetry={() => me.refetch()} />
        </div>
      </>
    );
  }
  const d = me.data;
  if (!d) {
    return (
      <>
        <DriverHeader title={t("Мой Score")} />
        <div className="flex flex-col gap-3 p-4">
          <Skeleton className="h-56 rounded-card" />
          <Skeleton className="h-40 rounded-card" />
        </div>
      </>
    );
  }
  const zone = d.score.is_new
    ? { title: t("Первая неделя"), text: t("Score появится после первого рейса. Стартуете со 100 — держите планку.") }
    : ZONE_TEXT[d.score.zone];
  const rows = lb.data?.rows ?? [];
  const myIndex = rows.findIndex((r) => r.driver_id === d.driver.id);
  const window = myIndex >= 0 ? rows.slice(Math.max(0, myIndex - 2), myIndex + 3) : [];

  return (
    <>
      <DriverHeader title={t("Мой Score")} />
      <div className="flex flex-col gap-3 p-4">
        <Card className="flex flex-col items-center text-center">
          <ScoreRing value={d.score.value} zone={d.score.zone} size={168} className="text-4xl" />
          <h2 className="mt-4 text-2xl font-extrabold">{zone.title}</h2>
          <p className="mt-1 text-mut">{zone.text}</p>
          {d.score.streak > 0 ? (
            <div className="mt-4 flex items-center gap-2 rounded-btn bg-warn/15 px-4 py-2 font-bold text-warn">
              <Flame size={20} />
              <span className="num">{d.score.streak}</span> {pluralRu(d.score.streak, t("день"), t("дня"), t("дней"))} {t("без критических событий")}
            </div>
          ) : (
            <div className="mt-4 rounded-btn bg-cardh px-4 py-2 text-sm font-bold text-mut">
              {t("Серия начнётся с первого спокойного дня — без критических событий")}
            </div>
          )}
        </Card>

        <Card>
          <div className="mb-2 text-sm font-bold text-mut">{t("Лидерборд · я и соседи · 7 дней")}</div>
          {lb.isLoading && <Skeleton className="h-32 rounded-card" />}
          {lb.isError && <div className="text-sm text-mut">{t("Лидерборд пока недоступен")}</div>}
          {window.length > 0 && (
            <ul className="flex flex-col gap-1">
              {window.map((r) => (
                <li
                  key={r.driver_id}
                  aria-current={r.driver_id === d.driver.id ? "true" : undefined}
                  className={cn(
                    "flex min-h-14 items-center gap-3 rounded-btn px-3",
                    r.driver_id === d.driver.id ? "bg-accent/15 font-extrabold" : "text-mut",
                  )}
                >
                  <span className="num w-7 text-center">{r.rank}</span>
                  <span className="flex-1 truncate">{r.driver_id === d.driver.id ? t("Вы") : r.name}</span>
                  <span className={cn("num font-extrabold", r.zone === "ok" ? "text-ok" : r.zone === "warn" ? "text-warn" : "text-danger")}>{r.score}</span>
                </li>
              ))}
            </ul>
          )}
          {lb.data && myIndex < 0 && <div className="text-sm text-mut">{t("В этом периоде рейтинга ещё нет — он появится после первого рейса.")}</div>}
        </Card>

        <Card>
          <div className="mb-2 text-sm font-bold text-mut">{t("Мои события и советы")}</div>
          {d.recent_events.length === 0 ? (
            <div className="text-mut">{t("Событий нет — так и продолжайте.")}</div>
          ) : (
            <ul className="flex flex-col gap-3">
              {d.recent_events.slice(0, 6).map((e) => {
                const Icon = EVENT_ICONS[e.type];
                return (
                  <li key={e.uuid} className="flex gap-3">
                    <div className={cn("grid h-10 w-10 shrink-0 place-items-center rounded-full", e.severity === "critical" ? "bg-danger/15 text-danger" : "bg-warn/15 text-warn")}>
                      {Icon ? <Icon size={20} /> : null}
                    </div>
                    <div className="min-w-0">
                      <div className="font-bold">
                        {eventTitle(e.type, e.value)} <span className="num text-sm font-normal text-mut">· {formatEventTime(e.ts)}</span>
                        {e.status === "false_positive" && <span className="ml-1 text-sm font-normal text-ok">{t("· снято координатором")}</span>}
                      </div>
                      <div className="text-sm text-mut">{ADVICE[e.type] ?? t("Спокойная дорога — лучший план.")}</div>
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </Card>

        <Card>
          <div className="mb-2 flex items-center gap-2 text-sm font-bold text-mut">
            <ShieldCheck size={18} /> {t("Что хранится обо мне")}
          </div>
          <ul className="flex flex-col gap-1.5 text-sm">
            <li>{t("ФИО, телефон, депо и машина — пока вы работаете в парке.")}</li>
            <li>{t("События DMS и Score —")}{" "}{d.retention.events_months} {t("мес.")}</li>
            <li>{t("Видеоклипы событий (15 с) —")}{" "}{d.retention.clips_days} {t("дн., фото чек-листов —")}{" "}{d.retention.photos_days} {t("дн.")}</li>
            <li>{t("Рейсы, перерывы и отметки обучения — вместе с событиями.")}</li>
            <li>{t("Камера в кабине не пишет постоянно: только короткий клип при событии. Лица не распознаются.")}</li>
          </ul>
        </Card>
      </div>
    </>
  );
}
