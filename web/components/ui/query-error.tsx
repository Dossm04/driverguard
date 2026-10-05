"use client";

/* Честное состояние ошибки загрузки (правило 8 CLAUDE.md: ошибки не скрывать). */

import { CircleAlert, RotateCcw } from "lucide-react";

import { Button } from "@/components/ui/button";
import { t } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";

export function QueryError({
  error,
  onRetry,
}: {
  error: unknown;
  onRetry: () => void;
}) {
  useLangVersion();
  const message = error instanceof Error ? error.message : t("Неизвестная ошибка");
  return (
    <div className="flex flex-col items-center justify-center gap-2 rounded-card border border-dashed border-danger/40 bg-danger/5 px-6 py-10 text-center">
      <div className="grid h-11 w-11 place-items-center rounded-full bg-danger/15 text-danger">
        <CircleAlert size={20} />
      </div>
      <h3 className="text-sm font-bold">{t("Не удалось загрузить данные")}</h3>
      <p className="max-w-sm text-xs text-mut">{message}</p>
      <Button variant="outline" size="sm" onClick={onRetry}>
        <RotateCcw size={14} />
        {t("Повторить")}
      </Button>
    </div>
  );
}
