"use client";

/* Мини-тур первого входа: собственный лёгкий компонент (без сторонних библиотек).
   Подсвечивает элементы с data-tour через «spotlight» (box-shadow-вырез) и показывает
   карточку с пояснением. Флаг прохождения — localStorage (разрешено правилом CLAUDE.md). */

import { useCallback, useEffect, useState } from "react";

import { Button } from "@/components/ui/button";
import { t } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";
import { MAIN_TOUR, TOUR_STORAGE_KEY, type TourStep } from "@/lib/tours";

interface Rect {
  top: number;
  left: number;
  width: number;
  height: number;
}

function targetRect(step: TourStep): Rect | null {
  const el = document.querySelector<HTMLElement>(`[data-tour="${step.target}"]`);
  if (!el) return null;
  const r = el.getBoundingClientRect();
  // display:none, свёрнутый drawer или элемент за пределами экрана — цели «нет»
  if (r.width === 0 || r.height === 0 || r.right <= 0 || r.left >= window.innerWidth) return null;
  return { top: r.top - 6, left: r.left - 6, width: r.width + 12, height: r.height + 12 };
}

export function Tour({
  open,
  onClose,
  steps = MAIN_TOUR,
}: {
  open: boolean;
  onClose: () => void;
  steps?: TourStep[];
}) {
  useLangVersion();
  const [index, setIndex] = useState(0);
  const [rect, setRect] = useState<Rect | null>(null);

  const finish = useCallback(() => {
    try {
      localStorage.setItem(TOUR_STORAGE_KEY, "done");
    } catch {
      /* приватный режим */
    }
    setIndex(0);
    onClose();
  }, [onClose]);

  useEffect(() => {
    if (!open) return;
    const update = () => {
      const r = targetRect(steps[index]);
      if (r === null) {
        // цель шага не на этой странице — пропускаем шаг, а не зависаем
        if (index < steps.length - 1) setIndex(index + 1);
        else finish();
        return;
      }
      setRect(r);
    };
    update();
    window.addEventListener("resize", update);
    return () => window.removeEventListener("resize", update);
  }, [open, index, steps, finish]);

  if (!open || !rect) return null;

  const step = steps[index];
  const last = index === steps.length - 1;
  // Карточка — под подсветкой; если не влезает вниз, поднимаем выше элемента
  const cardW = 320;
  const below = rect.top + rect.height + 180 < window.innerHeight;
  const cardTop = below ? rect.top + rect.height + 12 : Math.max(12, rect.top - 190);
  const cardLeft = Math.min(Math.max(12, rect.left), window.innerWidth - cardW - 12);

  return (
    <div className="fixed inset-0 z-[100]" role="dialog" aria-label={t("Обучающий тур")}>
      {/* spotlight: прозрачное окно над целью, всё остальное затемнено */}
      <div
        className="absolute rounded-card transition-all duration-200"
        style={{
          top: rect.top,
          left: rect.left,
          width: rect.width,
          height: rect.height,
          // затемнение — токеном фона текущей темы (без hardcoded-цветов)
          boxShadow: "0 0 0 9999px rgb(var(--bg) / 0.72)",
        }}
      />
      <div
        className="absolute w-[320px] rounded-card border border-line bg-card p-4 shadow-2xl"
        style={{ top: cardTop, left: cardLeft }}
      >
        <div className="text-[15px] font-bold">{step.title}</div>
        <p className="mt-1 text-sm leading-relaxed text-mut">{step.text}</p>
        <div className="mt-3 flex items-center justify-between">
          <div className="flex gap-1.5" aria-label={t("Шаг {0} из {1}", index + 1, steps.length)}>
            {steps.map((s, i) => (
              <span
                key={s.target}
                className={`h-1.5 w-1.5 rounded-full ${i === index ? "bg-accent" : "bg-line"}`}
              />
            ))}
          </div>
          <div className="flex gap-2">
            <Button variant="ghost" size="sm" onClick={finish}>
              {t("Пропустить")}
            </Button>
            <Button
              size="sm"
              onClick={() => (last ? finish() : setIndex((i) => i + 1))}
            >
              {last ? t("Понятно!") : t("Далее")}
            </Button>
          </div>
        </div>
      </div>
    </div>
  );
}

/** Хук автозапуска тура при первом входе + ручной перезапуск (кнопка «?»). */
export function useTour() {
  const [open, setOpen] = useState(false);
  useEffect(() => {
    let done = "done";
    try {
      done = localStorage.getItem(TOUR_STORAGE_KEY) ?? "";
    } catch {
      /* нет localStorage — тур не навязываем */
    }
    if (done !== "done") {
      // даём layout'у отрисоваться, затем стартуем
      const t = setTimeout(() => setOpen(true), 600);
      return () => clearTimeout(t);
    }
  }, []);
  return { open, start: () => setOpen(true), close: () => setOpen(false) };
}
