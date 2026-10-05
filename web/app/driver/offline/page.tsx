"use client";

import { WifiOff } from "lucide-react";
import { t } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";

/* Страница из кэша service worker, когда сеть недоступна (APP-8). */
export default function DriverOfflinePage() {
  useLangVersion();
  return (
    <div className="grid min-h-screen place-items-center px-6 text-center">
      <div>
        <div className="mx-auto grid h-20 w-20 place-items-center rounded-full bg-warn/15 text-warn">
          <WifiOff size={36} />
        </div>
        <h1 className="mt-5 text-2xl font-extrabold">{t("Нет сети")}</h1>
        <p className="mt-2 text-mut">
          {t("Приложение открылось из кэша. Как только связь появится, всё обновится само — заполненный чек-лист отправится автоматически.")}
        </p>
        <a
          href="/driver"
          className="mt-6 inline-flex min-h-14 items-center rounded-card bg-accent px-6 font-extrabold text-onaccent"
        >
          {t("Попробовать снова")}
        </a>
      </div>
    </div>
  );
}
