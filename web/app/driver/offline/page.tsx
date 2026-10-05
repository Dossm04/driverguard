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
          Камера доступна без сети после подготовки на этом телефоне. Сохранённые события и чек-листы отправятся после восстановления связи и входа в ту же учётную запись.
        </p>
        <a
          href="/driver/camera"
          className="mt-6 inline-flex min-h-14 items-center rounded-card bg-accent px-6 font-extrabold text-onaccent"
        >
          Открыть камеру
        </a>
      </div>
    </div>
  );
}
