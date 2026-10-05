"use client";

import { Truck } from "lucide-react";
import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { BigButton, ThemeToggle } from "@/components/driver/shell";
import { driverLogin } from "@/lib/auth";
import { LangSwitch } from "@/components/ui/lang-switch";
import { t } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";

// Подсказки с демо-паролями: в dev всегда, в production-сборке — только если стенд
// сознательно собран с NEXT_PUBLIC_DEMO_HINTS=1 (публичный туннель их не показывает)
const SHOW_DEMO_HINTS = process.env.NODE_ENV !== "production" || process.env.NEXT_PUBLIC_DEMO_HINTS === "1";


export default function DriverLoginPage() {
  useLangVersion();
  const router = useRouter();
  const [phone, setPhone] = useState("+7");
  const [pin, setPin] = useState("");
  const [error, setError] = useState("");
  const [busy, setBusy] = useState(false);
  const [cameraAfterLogin, setCameraAfterLogin] = useState(false);

  useEffect(() => {
    // QR cards may prefill only the demo identifier, never a password or token.
    const params = new URLSearchParams(window.location.search);
    const requestedPhone = params.get("phone");
    if (requestedPhone && /^\+7\d{10}$/.test(requestedPhone)) setPhone(requestedPhone);
    setCameraAfterLogin(params.get("next") === "camera");
  }, []);

  const submit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError("");
    if (!/^\+7\d{10}$/.test(phone)) {
      setError(t("Телефон в формате +7XXXXXXXXXX"));
      return;
    }
    if (!/^\d{4,6}$/.test(pin)) {
      setError(t("PIN — от 4 до 6 цифр"));
      return;
    }
    setBusy(true);
    try {
      await driverLogin(phone, pin);
      router.replace(cameraAfterLogin ? "/driver/camera" : "/driver");
    } catch (err) {
      setError(err instanceof Error ? err.message : t("Не удалось войти"));
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="flex min-h-screen flex-col px-5 pb-8 pt-4">
      <div className="flex items-center justify-end gap-2">
        <LangSwitch />
        <ThemeToggle />
      </div>
      <div className="mt-6 flex items-center gap-3">
        <div className="grid h-14 w-14 place-items-center rounded-card bg-accent/15 text-accent">
          <Truck size={30} />
        </div>
        <div>
          <h1 className="text-2xl font-extrabold leading-tight">DriverGuard</h1>
          <div className="text-sm text-mut">{t("Приложение водителя")}</div>
        </div>
      </div>
      <p className="mt-6 text-mut">{t("Ваш второй пилот в рейсе: чек-лист, Score, SOS и короткие уроки.")}</p>

      <form onSubmit={submit} className="mt-8 flex flex-col gap-4" noValidate>
        <label className="flex flex-col gap-1.5 text-sm font-bold text-mut">
          {t("Телефон")}
          <input
            type="tel"
            inputMode="tel"
            autoComplete="tel"
            value={phone}
            onChange={(e) => setPhone(e.target.value.replace(/[^\d+]/g, ""))}
            className="h-16 rounded-card border border-line bg-card px-4 text-xl font-bold text-txt num focus:outline-none focus:ring-2 focus:ring-accent"
            placeholder="+7 701 000 00 00"
          />
        </label>
        <label className="flex flex-col gap-1.5 text-sm font-bold text-mut">
          PIN
          <input
            type="password"
            inputMode="numeric"
            autoComplete="current-password"
            maxLength={6}
            value={pin}
            onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))}
            className="h-16 rounded-card border border-line bg-card px-4 text-2xl font-bold tracking-[0.5em] text-txt num focus:outline-none focus:ring-2 focus:ring-accent"
            placeholder="••••"
          />
        </label>
        {error && (
          <div role="alert" className="rounded-btn bg-danger/10 px-4 py-3 text-danger">
            {error}
          </div>
        )}
        <BigButton type="submit" disabled={busy}>
          {busy ? t("Входим…") : t("Войти")}
        </BigButton>
        <p className="text-center text-sm text-mut">
          {t("Устройство запоминается — вводить PIN каждый раз не нужно.")}
        </p>
      </form>
      <p className="mt-auto pt-8 text-center text-xs text-mut">{SHOW_DEMO_HINTS && t("Демо: +77012441832 · PIN 1234")}</p>
    </div>
  );
}
