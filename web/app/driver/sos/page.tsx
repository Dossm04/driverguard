"use client";

/* SOS (APP-5, BOT-2): удержание 3 с, причина, координаты Geolocation API, «Координатор уведомлён». */

import { useMutation } from "@tanstack/react-query";
import { CarFront, HeartPulse, HelpCircle, Wrench, CheckCircle2, Loader2 } from "lucide-react";
import Link from "next/link";
import { useEffect, useRef, useState } from "react";

import { useDriverMe } from "@/components/driver/data";
import { BigButton, Card, DriverHeader } from "@/components/driver/shell";
import { api, type EventItem, type SosReason } from "@/lib/api";
import { t } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";
import { cn } from "@/lib/utils";

const HOLD_MS = 3000;
const REASONS: { reason: SosReason; icon: typeof Wrench }[] = [
  { reason: "Поломка", icon: Wrench },
  { reason: "ДТП", icon: CarFront },
  { reason: "Здоровье", icon: HeartPulse },
  { reason: "Другое", icon: HelpCircle },
];

type Stage = "hold" | "reason" | "sending" | "done";
type Coords = { lat: number; lon: number } | null;

function position(options: PositionOptions): Promise<Coords> {
  return new Promise((resolve) => {
    navigator.geolocation.getCurrentPosition(
      (pos) => resolve({ lat: pos.coords.latitude, lon: pos.coords.longitude }),
      () => resolve(null),
      options,
    );
  });
}

/** Сначала точный GPS (8 с), при неудаче — грубая позиция по сети/кэшу (до 10 минут). */
async function locate(): Promise<Coords> {
  if (typeof navigator === "undefined" || !navigator.geolocation) return null;
  return (
    (await position({ enableHighAccuracy: true, timeout: 8000, maximumAge: 60_000 })) ??
    (await position({ enableHighAccuracy: false, timeout: 5000, maximumAge: 600_000 }))
  );
}

export default function SosPage() {
  useLangVersion();
  const me = useDriverMe();
  const [stage, setStage] = useState<Stage>("hold");
  const [progress, setProgress] = useState(0);
  const [coords, setCoords] = useState<Coords>(null);
  const [error, setError] = useState("");
  const timer = useRef<number | null>(null);
  const startedAt = useRef(0);

  const stopHold = () => {
    if (timer.current) cancelAnimationFrame(timer.current);
    timer.current = null;
    setProgress(0);
  };
  const tick = () => {
    const p = Math.min(1, (performance.now() - startedAt.current) / HOLD_MS);
    setProgress(p);
    if (p >= 1) {
      timer.current = null;
      if (navigator.vibrate) navigator.vibrate(200);
      setStage("reason");
      return;
    }
    timer.current = requestAnimationFrame(tick);
  };
  const startHold = () => {
    startedAt.current = performance.now();
    timer.current = requestAnimationFrame(tick);
  };
  useEffect(() => () => stopHold(), []);

  const send = useMutation({
    mutationFn: async (reason: SosReason) => {
      // SOS не должен зависеть от успешной загрузки экрана: дотягиваем профиль здесь
      const driverId = me.data?.driver.id ?? (await me.refetch()).data?.driver.id;
      if (!driverId) throw new Error(t("Нет связи с сервером. Позвоните координатору"));
      const pos = await locate();
      setCoords(pos);
      return api<EventItem>(`/drivers/${driverId}/sos`, {
        method: "POST",
        body: JSON.stringify({ reason, lat: pos?.lat ?? null, lon: pos?.lon ?? null, gps_valid: pos !== null }),
      });
    },
    onMutate: () => {
      setStage("sending");
      setError("");
    },
    onSuccess: () => setStage("done"),
    onError: (e) => {
      setError(e instanceof Error ? e.message : t("Не удалось отправить. Позвоните координатору"));
      setStage("reason");
    },
  });

  const ring = 2 * Math.PI * 88;
  return (
    <>
      <DriverHeader title="SOS" />
      <div className="flex flex-col gap-4 p-4">
        {stage === "hold" && (
          <>
            <p className="text-center text-mut">{t("Удерживайте кнопку 3 секунды — так исключаем случайное нажатие.")}</p>
            <div className="grid place-items-center py-4">
              <button
                type="button"
                aria-label={t("SOS: удерживайте 3 секунды")}
                data-testid="sos-hold"
                onPointerDown={startHold}
                onPointerUp={stopHold}
                onPointerLeave={stopHold}
                onPointerCancel={stopHold}
                onContextMenu={(e) => e.preventDefault()}
                className="relative grid h-56 w-56 select-none place-items-center rounded-full bg-danger text-onaccent shadow-[0_0_0_12px_rgb(var(--danger)/0.15)] active:scale-95"
                style={{ touchAction: "none" }}
              >
                <svg className="absolute inset-0 -rotate-90" viewBox="0 0 200 200" aria-hidden="true">
                  <circle cx="100" cy="100" r="88" fill="none" stroke="rgb(var(--onaccent) / 0.25)" strokeWidth="8" />
                  <circle
                    cx="100"
                    cy="100"
                    r="88"
                    fill="none"
                    stroke="rgb(var(--onaccent))"
                    strokeWidth="8"
                    strokeLinecap="round"
                    strokeDasharray={ring}
                    strokeDashoffset={ring * (1 - progress)}
                  />
                </svg>
                <span className="text-5xl font-black tracking-wider">SOS</span>
              </button>
            </div>
            <p className="text-center text-sm text-mut">{t("Координатор получит вашу позицию и причину. Помощь уже близко.")}</p>
          </>
        )}

        {stage === "reason" && (
          <Card className="flex flex-col gap-3">
            <div className="text-xl font-extrabold">{t("Что случилось?")}</div>
            <div className="grid grid-cols-2 gap-2">
              {REASONS.map((r) => (
                <button
                  key={r.reason}
                  type="button"
                  onClick={() => send.mutate(r.reason)}
                  className="flex min-h-24 flex-col items-center justify-center gap-2 rounded-card border border-line bg-page text-lg font-extrabold hover:bg-cardh"
                >
                  <r.icon size={30} className="text-danger" /> {r.reason}
                </button>
              ))}
            </div>
            {error && <div role="alert" className="rounded-btn bg-danger/10 px-4 py-3 text-danger">{error}</div>}
            <BigButton tone="outline" onClick={() => setStage("hold")}>
              {t("Отмена — всё в порядке")}
            </BigButton>
          </Card>
        )}

        {stage === "sending" && (
          <div className="grid min-h-[50vh] place-items-center text-center">
            <div>
              <Loader2 size={56} className="mx-auto animate-spin text-danger" />
              <div className="mt-4 text-xl font-extrabold">{t("Определяем позицию и отправляем…")}</div>
            </div>
          </div>
        )}

        {stage === "done" && (
          <Card className="text-center" data-testid="sos-done">
            <div className="mx-auto grid h-20 w-20 place-items-center rounded-full bg-ok/15 text-ok">
              <CheckCircle2 size={44} />
            </div>
            <h2 className="mt-4 text-2xl font-extrabold">{t("Координатор уведомлён")}</h2>
            <p className={cn("mt-2", coords ? "num text-mut" : "text-warn")}>
              {coords ? t("Координаты отправлены: {0}, {1}", coords.lat.toFixed(4), coords.lon.toFixed(4)) : t("Координаты получить не удалось — сообщите место координатору голосом.")}
            </p>
            <p className="mt-2 text-mut">{t("Оставайтесь в безопасном месте. Если можете, включите аварийную сигнализацию.")}</p>
            <Link href="/driver" className="mt-5 inline-flex min-h-14 items-center rounded-card bg-accent px-6 font-extrabold text-onaccent">
              {t("Вернуться к смене")}
            </Link>
          </Card>
        )}
      </div>
    </>
  );
}
