"use client";

/* Чек-лист (APP-3): мастер 7 фото только с камеры (capture), силуэт-подсказка, прогресс,
   анкета v2, экран «ИИ проверяет…», вердикт. Без сети — в очередь и отправка позже (APP-8). */

import { useQuery, useQueryClient } from "@tanstack/react-query";
import { Camera, CheckCircle2, AlertTriangle, XCircle, RefreshCw, Loader2, CloudOff } from "lucide-react";
import Link from "next/link";
import { useEffect, useMemo, useRef, useState } from "react";

import { BigButton, Card, DriverHeader } from "@/components/driver/shell";
import { CameraCapture, cameraAvailable } from "@/components/driver/camera-capture";
import { Silhouette } from "@/components/driver/silhouette";
import { QueryError } from "@/components/ui/query-error";
import { Skeleton } from "@/components/ui/skeleton";
import { api, ApiError, type ChecklistItemCatalog, type ChecklistOut, type ChecklistSlot } from "@/lib/api";
import { translateDiscrepancy } from "@/lib/checklist-text";
import { t, perLang } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";
import { checklistFormData, savePendingChecklist } from "@/lib/offline-queue";
import { cn } from "@/lib/utils";

const DEFAULT_SLOTS: { slot: string; label: string; hint: string }[] = perLang(() => [
  { slot: "front_lights", label: t("Перёд + фары"), hint: t("Включите ближний свет, встаньте в 3–4 метрах перед кабиной") },
  { slot: "rear_lights", label: t("Зад + габариты"), hint: t("Габариты включены, в кадре весь задний борт и фонари") },
  { slot: "left_side", label: t("Левый борт"), hint: t("Вся левая сторона от кабины до заднего колеса") },
  { slot: "right_side", label: t("Правый борт"), hint: t("Вся правая сторона, видны двери и колёса") },
  { slot: "tires", label: t("Шины"), hint: t("Крупно протектор и боковина одного колеса") },
  { slot: "windshield", label: t("Лобовое"), hint: t("Стекло целиком, чтобы были видны трещины и сколы") },
  { slot: "under_engine", label: t("Под двигателем"), hint: t("Площадка под моторным отсеком — видны ли подтёки") },
]);

const VERDICT_UI = perLang(() => ({
  допущен: { icon: CheckCircle2, tone: "text-ok bg-ok/15", title: t("Машина готова к рейсу"), text: t("Замечаний нет. Хорошей дороги!") },
  требует_внимания: { icon: AlertTriangle, tone: "text-warn bg-warn/15", title: t("Можно ехать, но есть замечания"), text: t("Посмотрите пункты ниже и покажите координатору при случае.") },
  не_допущен: { icon: XCircle, tone: "text-danger bg-danger/15", title: t("Сегодня лучше не выезжать"), text: t("Есть критичное замечание. Координатор уже видит чек-лист и свяжется с вами.") },
}) as const);

type Stage = "photos" | "form" | "sending" | "done" | "queued";

const MAX_SIDE = 1600; // px — backend принимает ≤4 МБ, фото с камеры телефона 8–15 МБ

/** Уменьшает снимок до ≤1600 px по длинной стороне и JPEG 0.85; при неудаче — исходный файл. */
async function shrinkPhoto(file: File): Promise<File> {
  try {
    const bitmap = await createImageBitmap(file);
    const scale = Math.min(1, MAX_SIDE / Math.max(bitmap.width, bitmap.height));
    if (scale === 1 && file.size <= 1_500_000) return file;
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(bitmap.width * scale);
    canvas.height = Math.round(bitmap.height * scale);
    canvas.getContext("2d")?.drawImage(bitmap, 0, 0, canvas.width, canvas.height);
    const blob = await new Promise<Blob | null>((r) => canvas.toBlob(r, "image/jpeg", 0.85));
    if (!blob) return file;
    return new File([blob], file.name.replace(/\.[^.]+$/, "") + ".jpg", { type: "image/jpeg" });
  } catch {
    return file;
  }
}

export default function ChecklistPage() {
  useLangVersion();
  const qc = useQueryClient();
  const items = useQuery({ queryKey: ["checklist-items"], queryFn: () => api<ChecklistItemCatalog[]>("/checklists/items") });
  // Ракурсы — из Настроек → Чек-лист парка; без сети — стандартные семь
  const slotsQ = useQuery({ queryKey: ["checklist-slots"], queryFn: () => api<ChecklistSlot[]>("/checklists/slots"), staleTime: 60_000 });
  const SLOTS = slotsQ.data && slotsQ.data.length > 0 ? slotsQ.data : DEFAULT_SLOTS;
  const [stage, setStage] = useState<Stage>("photos");
  const [step, setStep] = useState(0);
  const [photos, setPhotos] = useState<Record<string, File | null>>({});
  const [answers, setAnswers] = useState<Record<string, string>>({});
  const [result, setResult] = useState<ChecklistOut | null>(null);
  const [error, setError] = useState("");
  const [elapsed, setElapsed] = useState(0);
  const inputRef = useRef<HTMLInputElement>(null);
  const [camOpen, setCamOpen] = useState(false);
  const [showMissing, setShowMissing] = useState(false);
  // Живая камера, если браузер её даёт (HTTPS/localhost); иначе — системный выбор файла
  const openCapture = () => (cameraAvailable() ? setCamOpen(true) : inputRef.current?.click());

  const current = SLOTS[step];
  const file = photos[current.slot] ?? null;
  const preview = useMemo(() => (file ? URL.createObjectURL(file) : null), [file]);
  useEffect(() => () => {
    if (preview) URL.revokeObjectURL(preview);
  }, [preview]);
  useEffect(() => {
    if (stage !== "sending") return;
    setElapsed(0);
    const id = setInterval(() => setElapsed((s) => s + 1), 1000);
    return () => clearInterval(id);
  }, [stage]);

  const answerable = (items.data ?? []).filter((i) => i.method !== "auto");
  const required = answerable.filter((i) => i.base);
  const missing = required.filter((i) => !answers[i.id] || !String(answers[i.id]).trim());
  const missingIds = new Set(missing.map((i) => i.id));
  const sections = useMemo(() => {
    const map = new Map<string, ChecklistItemCatalog[]>();
    for (const i of answerable) map.set(i.section_title, [...(map.get(i.section_title) ?? []), i]);
    return Array.from(map.entries());
  }, [answerable]);

  /* Как в Google Forms: незаполненные пункты подсвечиваются красным, экран прокручивается к первому */
  const trySubmit = () => {
    if (missing.length > 0) {
      setShowMissing(true);
      document.getElementById(`ci-${missing[0].id}`)?.scrollIntoView({ behavior: "smooth", block: "center" });
      return;
    }
    void submit();
  };

  const submit = async () => {
    setStage("sending");
    setError("");
    const entry = {
      answers,
      photos: SLOTS.map((s) => {
        const f = photos[s.slot] as File;
        return { slot: s.slot, name: f.name || `${s.slot}.jpg`, type: f.type, blob: f };
      }),
    };
    try {
      const out = await api<ChecklistOut>("/checklists", { method: "POST", body: checklistFormData(entry) });
      setResult(out);
      setStage("done");
      qc.invalidateQueries({ queryKey: ["driver-me"] });
    } catch (e) {
      // 4xx и ошибка ИИ (502) — показываем причину; 503 (сервер/хранилище недоступны) и обрыв сети —
      // сохраняем локально и отправим автоматически (APP-8)
      if (e instanceof ApiError && e.status !== 503) {
        setError(e.message);
        setStage("form");
        return;
      }
      try {
        await savePendingChecklist({ created_at: new Date().toISOString(), ...entry });
        setStage("queued");
      } catch {
        setError(t("Нет сети, и сохранить локально не удалось. Попробуйте позже"));
        setStage("form");
      }
    }
  };

  const reset = () => {
    setStage("photos");
    setStep(0);
    setPhotos({});
    setAnswers({});
    setResult(null);
    setError("");
    setShowMissing(false);
  };

  if (stage === "sending") {
    return (
      <>
        <DriverHeader title={t("Чек-лист")} />
        <div className="grid min-h-[70vh] place-items-center p-6 text-center">
          <div>
            <Loader2 size={56} className="mx-auto animate-spin text-accent" />
            <h2 className="mt-5 text-2xl font-extrabold">{t("ИИ проверяет фото…")}</h2>
            <p className="mt-2 text-mut">{t("Обычно до 30 секунд. Смотрим фары, шины, стекло, утечки.")}</p>
            <p className="num mt-4 text-sm text-mut">{elapsed} {t("с")}</p>
          </div>
        </div>
      </>
    );
  }

  if (stage === "queued") {
    return (
      <>
        <DriverHeader title={t("Чек-лист")} />
        <div className="p-4">
          <Card className="text-center">
            <CloudOff size={48} className="mx-auto text-warn" />
            <h2 className="mt-4 text-xl font-extrabold">{t("Нет сети — чек-лист сохранён")}</h2>
            <p className="mt-2 text-mut">{t("Отправим автоматически, как только появится связь. Можно закрыть приложение.")}</p>
            <Link href="/driver" className="mt-5 inline-flex min-h-14 items-center rounded-card bg-accent px-6 font-extrabold text-onaccent">
              {t("К смене")}
            </Link>
          </Card>
        </div>
      </>
    );
  }

  if (stage === "done" && result) {
    const ui = VERDICT_UI[result.verdict];
    const issues = result.ai_items.filter((i) => i.status !== "ok");
    return (
      <>
        <DriverHeader title={t("Чек-лист")} />
        <div className="flex flex-col gap-3 p-4" data-testid="checklist-verdict" data-verdict={result.verdict}>
          <Card className="text-center">
            <div className={cn("mx-auto grid h-20 w-20 place-items-center rounded-full", ui.tone)}>
              <ui.icon size={40} />
            </div>
            <h2 className="mt-4 text-2xl font-extrabold">{ui.title}</h2>
            <p className="mt-1 text-mut">{ui.text}</p>
          </Card>
          {result.ai_meta?.provider === "unavailable" && (
            <Card role="status" className="border-warn/40 bg-warn/10 text-sm">
              {t("ИИ временно недоступен — фото проверит координатор. Чек-лист сохранён.")}
            </Card>
          )}
          {issues.length > 0 && result.ai_meta?.provider !== "unavailable" && (
            <Card>
              <div className="mb-2 text-sm font-bold text-mut">{t("Замечания ИИ")}</div>
              <ul className="flex flex-col gap-2">
                {issues.map((i) => (
                  <li key={i.key} className="flex gap-2">
                    {i.status === "fail" ? <XCircle className="mt-0.5 shrink-0 text-danger" size={20} /> : <AlertTriangle className="mt-0.5 shrink-0 text-warn" size={20} />}
                    <div>
                      <b>{t(i.title)}</b>
                      {i.status === "not_visible" ? <span className="text-mut"> {t("— не видно на фото")}</span> : ""}
                      {i.comment && <div className="text-sm text-mut">{i.comment}</div>}
                    </div>
                  </li>
                ))}
              </ul>
            </Card>
          )}
          {result.discrepancies.length > 0 && (
            <Card>
              <div className="mb-2 text-sm font-bold text-mut">{t("Анкета и фото расходятся")}</div>
              <ul className="list-disc pl-5 text-sm">{result.discrepancies.map((d) => <li key={d}>{translateDiscrepancy(d)}</li>)}</ul>
            </Card>
          )}
          <Link href="/driver" className="flex min-h-16 items-center justify-center rounded-card bg-accent text-lg font-extrabold text-onaccent">
            {t("К смене")}
          </Link>
          <BigButton tone="outline" onClick={reset}>
            <RefreshCw /> {t("Пройти заново")}
          </BigButton>
        </div>
      </>
    );
  }

  if (stage === "form") {
    return (
      <>
        <DriverHeader title={t("Чек-лист · анкета")} />
        <div className="flex flex-col gap-3 p-4">
          <p className="text-mut">{t("Фото готовы. Осталась короткая анкета: обязательных пунктов —")}{" "}{required.length}.</p>
          {items.isLoading && <Skeleton className="h-40 rounded-card" />}
          {sections.map(([title, list]) => (
            <Card key={t(title)}>
              <div className="mb-3 text-sm font-bold text-mut">{title}</div>
              <ul className="flex flex-col gap-4">
                {list.map((i) => (
                  <li
                    key={i.id}
                    id={`ci-${i.id}`}
                    className={cn(
                      "rounded-btn transition-colors",
                      showMissing && missingIds.has(i.id) && "-mx-2 border border-danger bg-danger/10 px-2 py-2",
                    )}
                    data-missing={showMissing && missingIds.has(i.id) ? "true" : undefined}
                  >
                    <div className="flex items-start gap-2">
                      <span className="num shrink-0 rounded-btn bg-cardh px-2 py-0.5 text-xs font-bold text-mut">{i.id}</span>
                      <span className={cn(!i.base && "text-mut")}>{t(i.text)}</span>
                    </div>
                    {showMissing && missingIds.has(i.id) && (
                      <div className="mt-1 text-xs font-bold text-danger">{t("Обязательный пункт — выберите ответ")}</div>
                    )}
                    {i.method === "input" ? (
                      <input
                        type="number"
                        inputMode="numeric"
                        aria-label={t(i.text)}
                        value={answers[i.id] ?? ""}
                        onChange={(e) => setAnswers({ ...answers, [i.id]: e.target.value })}
                        className="num mt-2 h-14 w-full rounded-btn border border-line bg-page px-4 text-lg font-bold focus:outline-none focus:ring-2 focus:ring-accent"
                        placeholder={t("км")}
                      />
                    ) : (
                      <div className="mt-2 grid grid-cols-3 gap-2" role="radiogroup" aria-label={t(i.text)}>
                        {/* значения ответа — всегда «да»/«нет»/«н-п» (их ждёт backend), переводится только подпись */}
                        {(["да", "нет", ...(i.na_allowed ? ["н-п"] : [])] as string[]).map((v) => (
                          <button
                            key={v}
                            type="button"
                            role="radio"
                            aria-checked={answers[i.id] === v}
                            onClick={() => setAnswers({ ...answers, [i.id]: v })}
                            className={cn(
                              "min-h-14 rounded-btn border border-line font-bold capitalize transition-colors",
                              answers[i.id] === v
                                ? v === "нет"
                                  ? "border-warn bg-warn/15 text-warn"
                                  : "border-accent bg-accent/15 text-accent"
                                : "bg-page text-mut hover:bg-cardh",
                            )}
                          >
                            {v === "н-п" ? t("Не прим.") : t(v)}
                          </button>
                        ))}
                      </div>
                    )}
                  </li>
                ))}
              </ul>
            </Card>
          ))}
          {items.isError && <QueryError error={items.error} onRetry={() => items.refetch()} />}
          {error && <div role="alert" className="rounded-btn bg-danger/10 px-4 py-3 text-danger">{error}</div>}
          <BigButton disabled={items.isLoading || items.isError} onClick={trySubmit}>
            {missing.length > 0 ? t("Осталось ответить: {0}", missing.length) : t("Отправить на проверку")}
          </BigButton>
          <BigButton tone="outline" onClick={() => setStage("photos")}>
            {t("Назад к фото")}
          </BigButton>
        </div>
      </>
    );
  }

  return (
    <>
      <DriverHeader title={t("Чек-лист перед рейсом")} />
      <div className="flex flex-col gap-3 p-4">
        <div className="flex items-center gap-3">
          <div className="h-2 flex-1 overflow-hidden rounded-full bg-cardh">
            <div className="h-full rounded-full bg-accent transition-all" style={{ width: `${((step + (file ? 1 : 0)) / SLOTS.length) * 100}%` }} />
          </div>
          <span className="num text-sm font-bold text-mut">
            {step + 1} / {SLOTS.length}
          </span>
        </div>
        <Card>
          <div className="text-sm font-bold text-mut">{t("Фото")}{" "}{step + 1}</div>
          <h2 className="text-2xl font-extrabold">{t(current.label)}</h2>
          <p className="mt-1 text-mut">{t(current.hint)}</p>
          <div className="mt-3 grid aspect-[5/3] place-items-center overflow-hidden rounded-card border border-dashed border-line bg-page">
            {preview ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img src={preview} alt={t(current.label)} className="h-full w-full object-cover" />
            ) : (
              <Silhouette slot={current.slot} className="h-full w-4/5 text-accent/70" />
            )}
          </div>
        </Card>
        {/* Только камера: без атрибута multiple и без галереи (APP-3) */}
        <input
          ref={inputRef}
          type="file"
          accept="image/*"
          capture="environment"
          className="sr-only"
          aria-label={t("Фото: {0}", current.label)}
          data-testid="checklist-photo-input"
          onChange={async (e) => {
            const f = e.target.files?.[0] ?? null;
            e.target.value = "";
            if (!f) return;
            const small = await shrinkPhoto(f);
            setPhotos((prev) => ({ ...prev, [current.slot]: small }));
          }}
        />
        {file ? (
          <>
            <BigButton onClick={() => (step < SLOTS.length - 1 ? setStep(step + 1) : setStage("form"))}>
              {step < SLOTS.length - 1 ? t("Далее") : t("К анкете")}
            </BigButton>
            <BigButton tone="outline" onClick={openCapture}>
              <RefreshCw /> {t("Переснять")}
            </BigButton>
          </>
        ) : (
          <BigButton className="min-h-20" onClick={openCapture}>
            <Camera /> {t("Сделать фото")}
          </BigButton>
        )}
        {step > 0 && (
          <button type="button" onClick={() => setStep(step - 1)} className="min-h-14 text-mut">
            {t("← Предыдущее фото")}
          </button>
        )}
      </div>
      {camOpen && (
        <CameraCapture
          slot={current.slot}
          label={t(current.label)}
          hint={t(current.hint)}
          onClose={() => setCamOpen(false)}
          onFallback={() => {
            setCamOpen(false);
            inputRef.current?.click();
          }}
          onCapture={async (f) => {
            setCamOpen(false);
            const small = await shrinkPhoto(f);
            setPhotos((prev) => ({ ...prev, [current.slot]: small }));
          }}
        />
      )}
    </>
  );
}
