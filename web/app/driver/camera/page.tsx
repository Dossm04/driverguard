"use client";

/* Экран «Камера» (пакет 6): DMS прямо в телефоне — MediaPipe в браузере, правила устройства,
   события в панель и позиция на Live-карте. Для менторов: включил камеру → видит анализ. */

import { DmsCamera } from "@/components/driver/dms-camera";
import { useDriverMe } from "@/components/driver/data";
import { DriverHeader } from "@/components/driver/shell";
import { t } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";

export default function CameraPage() {
  useLangVersion();
  const me = useDriverMe();
  const plate = me.data?.driver.vehicle?.plate ?? null;
  return (
    <>
      <DriverHeader title={t("Камера")} />
      <main className="flex flex-col gap-3 p-3">
        <DmsCamera vehiclePlate={plate} />
      </main>
    </>
  );
}
