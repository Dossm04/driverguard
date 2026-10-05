"use client";

/* Глобальный период «Сегодня | 7 дней | 30 дней» (правило 2 CLAUDE.md):
   страницы читают его через usePeriod() и передают в запросы к API. */

import { createContext, useContext, useState } from "react";

import type { Period } from "@/lib/api";

/** Единый тип периода — из lib/api (не дублируем список значений). */
export type PeriodValue = Period;

const PeriodContext = createContext<{
  period: PeriodValue;
  setPeriod: (p: PeriodValue) => void;
}>({ period: "today", setPeriod: () => {} });

export function PeriodProvider({ children }: { children: React.ReactNode }) {
  const [period, setPeriod] = useState<PeriodValue>("today");
  return (
    <PeriodContext.Provider value={{ period, setPeriod }}>{children}</PeriodContext.Provider>
  );
}

export function usePeriod() {
  return useContext(PeriodContext);
}
