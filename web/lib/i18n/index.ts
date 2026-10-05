/* Три языка интерфейса (пакет 7): русский (исходный текст в коде), казахский и английский.
   Словари ключуются исходной русской строкой: t("Обзор") → «Шолу» / "Overview"; если перевода
   нет — возвращается русский текст, интерфейс никогда не ломается. Плейсхолдеры {0}, {1}.
   Выбор языка хранится отдельно для панели и PWA (dg-lang / dg-lang-driver) и применяется
   перезагрузкой страницы — так работают и строки, вычисленные на уровне модуля. */

import { EN } from "./en";
import { KK } from "./kk";

export type Lang = "ru" | "kk" | "en";

export const LANGS: { value: Lang; label: string; short: string; locale: string }[] = [
  { value: "ru", label: "Русский", short: "RU", locale: "ru-RU" },
  { value: "kk", label: "Қазақша", short: "KZ", locale: "kk-KZ" },
  { value: "en", label: "English", short: "EN", locale: "en-GB" },
];

const DICTS: Record<Lang, Record<string, string> | null> = { ru: null, kk: KK, en: EN };

function storageKey(): string {
  const path = typeof location !== "undefined" ? location.pathname : "";
  const driver = path === "/driver" || path.startsWith("/driver/");
  return driver ? "dg-lang-driver" : "dg-lang";
}

function isLang(v: unknown): v is Lang {
  return v === "ru" || v === "kk" || v === "en";
}

function readLang(): Lang {
  if (typeof window === "undefined") return "ru";
  try {
    const stored = localStorage.getItem(storageKey());
    if (isLang(stored)) return stored;
  } catch {
    /* приватный режим — язык по умолчанию */
  }
  return "ru";
}

let current: Lang | null = null;
const listeners = new Set<() => void>();
let version = 0;

/** Текущий язык: на сервере всегда ru, в браузере — из localStorage (один раз за загрузку). */
export function getLang(): Lang {
  if (current === null) current = readLang();
  return current;
}

/** Смена языка без перезагрузки: сохраняем, уведомляем подписчиков (useLangVersion в
    компонентах и perLang-константы), состояние страниц — фото, ответы, формы — не теряется. */
export function setLang(lang: Lang): void {
  if (lang === getLang()) return;
  try {
    localStorage.setItem(storageKey(), lang);
  } catch {
    /* без localStorage язык живёт до перезагрузки */
  }
  current = lang;
  version += 1;
  if (typeof document !== "undefined") document.documentElement.lang = lang;
  listeners.forEach((fn) => fn());
}

export function subscribe(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function getVersion(): number {
  return version;
}

/** Константа уровня модуля, зависящая от языка: массив/объект пересчитывается при смене языка.
    Возвращает Proxy, поэтому `X.map(...)`, `X[key]`, `Object.entries(X)` работают как с обычным
    значением, а строки внутри всегда на текущем языке. */
export function perLang<T extends object>(factory: () => T): T {
  let cachedLang: Lang | null = null;
  let value: T | null = null;
  const resolve = (): T => {
    const lang = getLang();
    if (value === null || lang !== cachedLang) {
      value = factory();
      cachedLang = lang;
    }
    return value;
  };
  return new Proxy({} as T, {
    get(_target, prop) {
      const v = resolve();
      const r = Reflect.get(v, prop, v);
      return typeof r === "function" ? r.bind(v) : r;
    },
    has: (_target, prop) => prop in resolve(),
    ownKeys: () => Reflect.ownKeys(resolve()),
    getOwnPropertyDescriptor(_target, prop) {
      const d = Object.getOwnPropertyDescriptor(resolve(), prop);
      return d ? { ...d, configurable: true } : undefined;
    },
    getPrototypeOf: () => Object.getPrototypeOf(resolve()),
  });
}

export function localeTag(): string {
  return LANGS.find((l) => l.value === getLang())?.locale ?? "ru-RU";
}

/** Перевод строки интерфейса. Аргументы подставляются вместо {0}, {1}, … */
export function t(text: string, ...args: (string | number | null | undefined)[]): string {
  const dict = DICTS[getLang()];
  let out = dict?.[text] ?? text;
  if (args.length) out = out.replace(/\{(\d+)\}/g, (m, i) => String(args[Number(i)] ?? m));
  return out;
}

/** Склонение по языку: ru — три формы, kk — после числительного единственное, en — one/many. */
export function plural(n: number, one: string, few: string, many: string): string {
  const lang = getLang();
  if (lang === "kk") return t(one);
  if (lang === "en") return t(Math.abs(n) === 1 ? one : many);
  const abs = Math.abs(n) % 100;
  const last = abs % 10;
  if (abs >= 11 && abs <= 14) return many;
  if (last === 1) return one;
  if (last >= 2 && last <= 4) return few;
  return many;
}
