"use client";

/* React-хуки i18n — отдельно от чистого t(), чтобы серверные компоненты могли импортировать словарь. */

import { useEffect, useState, useSyncExternalStore } from "react";

import { getLang, getVersion, subscribe, type Lang } from "./index";

const serverVersion = () => 0;

/** Подписка компонента на смену языка: любой компонент, который вызывает t(), вызывает этот
    хук первым — тогда переключатель RU·KZ·EN перерисовывает тексты без перезагрузки. */
export function useLangVersion(): number {
  return useSyncExternalStore(subscribe, getVersion, serverVersion);
}

/** Язык для компонентов-переключателей (на сервере и до монтирования — ru). */
export function useLang(): Lang {
  useLangVersion();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  return mounted ? getLang() : "ru";
}

/** Проставляет <html lang> — читалки экрана и переносы слов зависят от него. */
export function useHtmlLang(): void {
  useEffect(() => {
    document.documentElement.lang = getLang();
  }, []);
}
