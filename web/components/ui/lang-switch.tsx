"use client";

/* Переключатель языка интерфейса (пакет 7): компактный сегмент RU · KZ · EN для шапок
   и список с названиями для Настроек. Выбор сохраняется отдельно для панели и PWA. */

import { LANGS, setLang, t, type Lang } from "@/lib/i18n";
import { useLang } from "@/lib/i18n/react";
import { cn } from "@/lib/utils";

export function LangSwitch({ className, size = "sm" }: { className?: string; size?: "sm" | "lg" }) {
  const lang = useLang();
  return (
    <div
      role="radiogroup"
      aria-label={t("Язык интерфейса")}
      data-testid="lang-switch"
      className={cn("flex rounded-btn border border-line bg-card p-0.5", className)}
    >
      {LANGS.map((l) => (
        <button
          key={l.value}
          type="button"
          role="radio"
          aria-checked={lang === l.value}
          aria-label={l.label}
          onClick={() => lang !== l.value && setLang(l.value)}
          className={cn(
            "rounded-[10px] font-bold text-mut transition-colors hover:text-txt",
            size === "sm" ? "px-2 py-1 text-[11px]" : "min-h-11 px-3 text-sm",
            lang === l.value && "bg-accent/15 text-accent",
          )}
        >
          {l.short}
        </button>
      ))}
    </div>
  );
}

export function LangList() {
  const lang = useLang();
  const HINT: Record<Lang, string> = {
    ru: t("основной язык панели"),
    kk: t("мемлекеттік тіл"),
    en: t("English"),
  };
  return (
    <div className="flex flex-col gap-2" role="radiogroup" aria-label={t("Язык")}>
      {LANGS.map((l) => (
        <label
          key={l.value}
          className={cn(
            "flex cursor-pointer items-center gap-3 rounded-btn border p-3",
            lang === l.value ? "border-accent bg-accent/10" : "border-line hover:bg-cardh",
          )}
        >
          <input
            type="radio"
            name="lang"
            className="h-4 w-4 accent-[rgb(var(--accent))]"
            checked={lang === l.value}
            onChange={() => setLang(l.value)}
          />
          <span>
            <b className="block text-sm">{l.label}</b>
            <span className="block text-xs text-mut">{HINT[l.value]}</span>
          </span>
        </label>
      ))}
    </div>
  );
}
