"use client";

/* Обучение (APP-6): карточки 30-секундных уроков, назначенные — сверху, отметка прохождения. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { CheckCircle2, Clock, GraduationCap, Play } from "lucide-react";
import { useEffect, useState } from "react";

import { useDriverMe } from "@/components/driver/data";
import { BigButton, Card, DriverHeader } from "@/components/driver/shell";
import { Skeleton } from "@/components/ui/skeleton";
import { useToast } from "@/components/ui/toast";
import { api, type TrainingOut } from "@/lib/api";
import { t, perLang } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";
import { cn } from "@/lib/utils";

const LESSONS: Record<string, { intro: string; tips: string[] }> = perLang(() => ({
  "Управление усталостью": {
    intro: t("Сонливость и провалы внимания — повод безопасно остановиться и отдохнуть. Предупреждение приложения не заменяет отдых."),
    tips: [
      t("Планируйте места для отдыха до выезда. При сонливости не ждите планового перерыва."),
      t("Зевота, тяжёлые веки, «пропущенный» километр — сигналы остановиться сейчас."),
      t("Кофе и энергетики не заменяют полноценный сон."),
      t("Сообщите координатору, если не можете безопасно продолжать рейс."),
    ],
  },
  "Техника перерывов в рейсе": {
    intro: t("Перерыв — часть безопасного рейса. Его длительность сама по себе не доказывает восстановление внимания."),
    tips: [
      t("Сначала припаркуйтесь в разрешённом безопасном месте."),
      t("При сонливости нужен отдых; напитки не гарантируют бодрость."),
      t("Возобновляйте движение только когда можете делать это безопасно."),
      t("Отметьте перерыв в приложении — координатор видит, что вы отдохнули."),
    ],
  },
  "Телефон и дорога": {
    intro: t("Настройка телефона и сообщения отвлекают от дороги. Оставьте их до безопасной остановки."),
    tips: [
      t("Автоответ «за рулём, перезвоню» — включите перед выездом."),
      t("Настройте навигатор до выезда. Громкая связь тоже может отвлекать."),
      t("Для важного звонка или сообщения остановитесь в разрешённом безопасном месте и припаркуйтесь."),
      t("Телефон в бардачке — самая простая защита от привычки."),
    ],
  },
}));
const FALLBACK = perLang(() => ({ intro: t("Короткий урок о безопасности в рейсе."), tips: [t("Перерыв каждые 2 часа."), t("Взгляд на дорогу."), t("Ремень всегда.")] }));

export default function LearnPage() {
  useLangVersion();
  const me = useDriverMe();
  const catalog = useQuery({ queryKey: ["trainings"], queryFn: () => api<TrainingOut[]>("/trainings") });
  const qc = useQueryClient();
  const toast = useToast();
  const [open, setOpen] = useState<{ title: string; duration: number; itemId: number | null } | null>(null);
  const [left, setLeft] = useState(0);
  const [localDone, setLocalDone] = useState<Set<string>>(new Set());

  useEffect(() => {
    if (!open) return;
    setLeft(open.duration);
    const id = setInterval(() => setLeft((s) => (s > 0 ? s - 1 : 0)), 1000);
    return () => clearInterval(id);
  }, [open]);

  const complete = useMutation({
    mutationFn: (itemId: number) => api(`/drivers/${me.data?.driver.id}/trainings/${itemId}/complete`, { method: "POST" }),
    onSuccess: () => {
      toast(t("Урок засчитан. Отличная работа!"));
      qc.invalidateQueries({ queryKey: ["driver-me"] });
      setOpen(null);
    },
    onError: (e) => toast(e instanceof Error ? e.message : t("Не удалось отметить")),
  });

  const assigned = me.data?.trainings ?? [];
  const assignedIds = new Set(assigned.map((tr) => tr.training_id));
  const others = (catalog.data ?? []).filter((tr) => !assignedIds.has(tr.id));

  if (open) {
    const lesson = LESSONS[open.title] ?? FALLBACK;
    const done = left === 0;
    return (
      <>
        <DriverHeader title={t("Урок")} />
        <div className="flex flex-col gap-3 p-4">
          <Card>
            <div className="flex items-center justify-between">
              <div className="text-sm font-bold text-mut">{t("30-секундный урок")}</div>
              <div className={cn("num flex items-center gap-1 text-sm font-bold", done ? "text-ok" : "text-mut")} aria-live="polite">
                <Clock size={16} /> {done ? t("готово") : t("{0} с", left)}
              </div>
            </div>
            <h2 className="mt-1 text-2xl font-extrabold">{open.title}</h2>
            <p className="mt-2">{lesson.intro}</p>
            <ol className="mt-3 flex flex-col gap-2">
              {lesson.tips.map((t, i) => (
                <li key={t} className="flex gap-3">
                  <span className="num grid h-8 w-8 shrink-0 place-items-center rounded-full bg-accent/15 font-extrabold text-accent">{i + 1}</span>
                  <span>{t}</span>
                </li>
              ))}
            </ol>
          </Card>
          {open.itemId !== null ? (
            <BigButton tone="ok" disabled={!done || complete.isPending} onClick={() => complete.mutate(open.itemId as number)}>
              <CheckCircle2 /> {done ? t("Отметить пройденным") : t("Дочитайте до конца")}
            </BigButton>
          ) : (
            <BigButton
              tone="ok"
              disabled={!done}
              onClick={() => {
                setLocalDone(new Set(localDone).add(open.title));
                setOpen(null);
              }}
            >
              <CheckCircle2 /> {t("Готово")}
            </BigButton>
          )}
          <BigButton tone="outline" onClick={() => setOpen(null)}>
            {t("Назад")}
          </BigButton>
        </div>
      </>
    );
  }

  return (
    <>
      <DriverHeader title={t("Обучение")} />
      <div className="flex flex-col gap-3 p-4">
        <p className="text-mut">{t("Уроки по 30 секунд — самое полезное, без лекций. Назначенные координатором — сверху.")}</p>
        {(me.isLoading || catalog.isLoading) && <Skeleton className="h-40 rounded-card" />}
        {assigned.map((tr) => (
          <Card key={tr.id} className="flex items-center gap-3">
            <div className={cn("grid h-12 w-12 shrink-0 place-items-center rounded-btn", tr.status === "completed" ? "bg-ok/15 text-ok" : "bg-warn/15 text-warn")}>
              {tr.status === "completed" ? <CheckCircle2 size={24} /> : <GraduationCap size={24} />}
            </div>
            <div className="min-w-0 flex-1">
              <div className="font-extrabold">{t(tr.title)}</div>
              <div className="text-sm text-mut">{tr.status === "completed" ? t("Пройден") : t("Назначен координатором · 30 с")}</div>
            </div>
            {tr.status !== "completed" && (
              <button
                type="button"
                onClick={() => setOpen({ title: tr.title, duration: tr.duration_s, itemId: tr.id })}
                className="grid h-14 w-14 shrink-0 place-items-center rounded-btn bg-accent text-onaccent"
                aria-label={t("Начать: {0}", t(tr.title))}
              >
                <Play size={24} />
              </button>
            )}
          </Card>
        ))}
        {others.map((tr) => (
          <Card key={tr.id} className="flex items-center gap-3">
            <div className={cn("grid h-12 w-12 shrink-0 place-items-center rounded-btn", localDone.has(tr.title) ? "bg-ok/15 text-ok" : "bg-accent/15 text-accent")}>
              {localDone.has(tr.title) ? <CheckCircle2 size={24} /> : <GraduationCap size={24} />}
            </div>
            <div className="min-w-0 flex-1">
              <div className="font-extrabold">{t(tr.title)}</div>
              <div className="num text-sm text-mut">{tr.duration_s} {t("с")}</div>
            </div>
            <button
              type="button"
              onClick={() => setOpen({ title: tr.title, duration: tr.duration_s, itemId: null })}
              className="grid h-14 w-14 shrink-0 place-items-center rounded-btn border border-line bg-page text-accent"
              aria-label={t("Открыть: {0}", t(tr.title))}
            >
              <Play size={24} />
            </button>
          </Card>
        ))}
      </div>
    </>
  );
}
