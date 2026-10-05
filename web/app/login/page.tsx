"use client";

import { zodResolver } from "@hookform/resolvers/zod";
import { Shield } from "lucide-react";
import { useRouter } from "next/navigation";
import { useMemo, useState } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Button } from "@/components/ui/button";
import { login } from "@/lib/auth";
import { LangSwitch } from "@/components/ui/lang-switch";
import { t } from "@/lib/i18n";
import { useLang } from "@/lib/i18n/react";

// Подсказки с демо-паролями: в dev всегда, в production-сборке — только если стенд
// сознательно собран с NEXT_PUBLIC_DEMO_HINTS=1 (публичный туннель их не показывает)
const SHOW_DEMO_HINTS = process.env.NODE_ENV !== "production" || process.env.NEXT_PUBLIC_DEMO_HINTS === "1";


// Схема собирается на текущем языке (сообщения валидации переводятся живьём)
const buildSchema = () =>
  z.object({
    email: z.string().min(1, t("Введите email")).email(t("Некорректный email")),
    password: z.string().min(1, t("Введите пароль")),
  });
type FormData = z.infer<ReturnType<typeof buildSchema>>;

export default function LoginPage() {
  const lang = useLang();
  const router = useRouter();
  const [serverError, setServerError] = useState("");
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
  } = useForm<FormData>({ resolver: zodResolver(useMemo(buildSchema, [lang])) });

  const onSubmit = async (data: FormData) => {
    setServerError("");
    try {
      await login(data.email, data.password);
      router.replace("/");
    } catch (e) {
      setServerError(e instanceof Error ? e.message : t("Не удалось войти"));
    }
  };

  return (
    <div className="grid min-h-screen place-items-center bg-page p-4">
      <div className="w-full max-w-sm rounded-card border border-line bg-card p-6">
        <div className="mb-5 flex items-center gap-3">
          <div className="grid h-11 w-11 place-items-center rounded-btn bg-accent/15 text-accent">
            <Shield size={24} />
          </div>
          <div>
            <div className="text-lg font-extrabold">DriverGuard</div>
            <div className="text-xs text-mut">{t("Панель координатора")}</div>
          </div>
          <LangSwitch className="ml-auto" />
        </div>

        <form onSubmit={handleSubmit(onSubmit)} className="flex flex-col gap-3" noValidate>
          <label className="flex flex-col gap-1 text-sm font-semibold">
            Email
            <input
              type="email"
              autoComplete="username"
              className="h-10 rounded-btn border border-line bg-page px-3 text-sm font-normal focus:outline-none focus:ring-2 focus:ring-accent"
              placeholder="admin@driverguard.kz"
              {...register("email")}
            />
            {errors.email && <span className="text-xs font-normal text-danger">{errors.email.message}</span>}
          </label>

          <label className="flex flex-col gap-1 text-sm font-semibold">
            {t("Пароль")}
            <input
              type="password"
              autoComplete="current-password"
              className="h-10 rounded-btn border border-line bg-page px-3 text-sm font-normal focus:outline-none focus:ring-2 focus:ring-accent"
              placeholder="••••••••"
              {...register("password")}
            />
            {errors.password && (
              <span className="text-xs font-normal text-danger">{errors.password.message}</span>
            )}
          </label>

          {serverError && (
            <div className="rounded-btn bg-danger/10 px-3 py-2 text-sm text-danger">{serverError}</div>
          )}

          <Button type="submit" size="lg" disabled={isSubmitting} className="mt-1">
            {isSubmitting ? t("Входим...") : t("Войти")}
          </Button>
        </form>

        <p className="mt-4 text-center text-xs text-mut">
          {SHOW_DEMO_HINTS && t("Демо-доступ: admin@driverguard.kz · admin123")}
        </p>
      </div>
    </div>
  );
}
