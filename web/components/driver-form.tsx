"use client";

/* Модалка «Добавить / Редактировать водителя» (WEB-6): RHF+zod, депо и машина из справочников,
   телефон+PIN создают или обновляют учётку PWA (backend BE-2), фото — POST /drivers/{id}/photo. */

import { zodResolver } from "@hookform/resolvers/zod";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { Pencil, UserPlus, X } from "lucide-react";
import { useEffect, useRef, useState, useMemo } from "react";
import { useForm } from "react-hook-form";
import { z } from "zod";

import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { useToast } from "@/components/ui/toast";
import { api, API_URL, getToken, type DepotOut, type DriverOut, type VehicleOut } from "@/lib/api";
import { t } from "@/lib/i18n";
import { useLang } from "@/lib/i18n/react";

// Схема собирается на текущем языке (сообщения валидации переводятся живьём)
const buildSchema = () =>
  z
  .object({
    name: z.string().trim().min(3, t("Введите ФИО, например «Иванов А.С.»")),
    depot_id: z.string(),
    vehicle_id: z.string(),
    phone: z
      .string()
      .trim()
      .regex(/^\+7\d{10}$/, t("Формат: +7XXXXXXXXXX"))
      .or(z.literal("")),
    pin: z.string().regex(/^\d{4,6}$/, t("PIN — от 4 до 6 цифр")).or(z.literal("")),
  })
  .refine((d) => !d.pin || d.phone, {
    message: t("PIN работает только вместе с телефоном"),
    path: ["pin"],
  });
type FormData = z.infer<ReturnType<typeof buildSchema>>;

const inputCls =
  "h-10 rounded-btn border border-line bg-page px-3 text-sm font-normal focus:outline-none focus:ring-2 focus:ring-accent";
const PHOTO_MAX = 5 * 1024 * 1024;

async function uploadPhoto(driverId: number, file: File): Promise<DriverOut> {
  const body = new FormData();
  body.append("file", file);
  const res = await fetch(`${API_URL}/drivers/${driverId}/photo`, {
    method: "POST",
    headers: { Authorization: `Bearer ${getToken() ?? ""}` },
    body,
  });
  if (!res.ok) {
    let detail = t("Не удалось загрузить фото");
    try {
      detail = (await res.json()).detail ?? detail;
    } catch {
      /* без тела */
    }
    throw new Error(String(detail));
  }
  return res.json();
}

export function DriverForm({
  open,
  onClose,
  driver,
  onSaved,
}: {
  open: boolean;
  onClose: () => void;
  /** Если передан — режим редактирования */
  driver?: DriverOut | null;
  onSaved?: (driver: DriverOut) => void;
}) {
  const lang = useLang();
  const schema = useMemo(buildSchema, [lang]);
  const toast = useToast();
  const queryClient = useQueryClient();
  const editing = !!driver;
  const fileRef = useRef<HTMLInputElement>(null);
  const [photo, setPhoto] = useState<File | null>(null);
  const [photoPreview, setPhotoPreview] = useState<string | null>(null);
  const {
    register,
    handleSubmit,
    reset,
    setError,
    formState: { errors },
  } = useForm<FormData>({
    resolver: zodResolver(schema),

    defaultValues: { name: "", depot_id: "", vehicle_id: "", phone: "", pin: "" },
  });

  // При открытии режима редактирования — заполнить текущими значениями
  useEffect(() => {
    if (!open) return;
    reset({
      name: driver?.name ?? "",
      depot_id: driver?.depot_id ? String(driver.depot_id) : "",
      vehicle_id: driver?.vehicle_id ? String(driver.vehicle_id) : "",
      phone: driver?.phone ?? "",
      pin: "",
    });
    setPhoto(null);
    setPhotoPreview(null);
  }, [open, driver, reset]);

  useEffect(() => {
    if (!photo) return;
    const url = URL.createObjectURL(photo);
    setPhotoPreview(url);
    return () => URL.revokeObjectURL(url);
  }, [photo]);

  // Закрытие любым способом очищает форму — иначе после 409 остаются ФИО/телефон/PIN
  const close = () => {
    reset();
    setPhoto(null);
    onClose();
  };

  const depots = useQuery({
    queryKey: ["depots"],
    queryFn: () => api<DepotOut[]>("/depots"),
    staleTime: 60_000,
    enabled: open,
  });
  const vehicles = useQuery({
    queryKey: ["vehicles"],
    queryFn: () => api<VehicleOut[]>("/vehicles"),
    staleTime: 60_000,
    enabled: open,
  });

  const save = useMutation({
    mutationFn: async (data: FormData) => {
      const payload: Record<string, unknown> = {
        name: data.name,
        depot_id: data.depot_id ? Number(data.depot_id) : null,
        phone: data.phone || null,
      };
      if (data.pin) payload.pin = data.pin;
      let saved: DriverOut;
      if (editing && driver) {
        payload.vehicle_id = data.vehicle_id ? Number(data.vehicle_id) : null;
        saved = await api<DriverOut>(`/drivers/${driver.id}`, { method: "PATCH", body: JSON.stringify(payload) });
      } else {
        saved = await api<DriverOut>("/drivers", { method: "POST", body: JSON.stringify(payload) });
        if (data.vehicle_id) {
          saved = await api<DriverOut>(`/drivers/${saved.id}`, {
            method: "PATCH",
            body: JSON.stringify({ vehicle_id: Number(data.vehicle_id) }),
          });
        }
      }
      if (photo) saved = await uploadPhoto(saved.id, photo);
      return saved;
    },
    onSuccess: (saved) => {
      toast(editing ? t("Изменения сохранены: {0}", saved.name) : t("Водитель добавлен: {0}", saved.name));
      // Новый/изменённый водитель сразу виден в списке, профиле и лидерборде
      queryClient.invalidateQueries({ queryKey: ["drivers"] });
      queryClient.invalidateQueries({ queryKey: ["driver-profile"] });
      queryClient.invalidateQueries({ queryKey: ["leaderboard"] });
      queryClient.invalidateQueries({ queryKey: ["vehicles"] });
      onSaved?.(saved);
      close();
    },
    onError: (e) =>
      setError("root", {
        message: e instanceof Error ? e.message : t("Не удалось сохранить водителя"),
      }),
  });

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open]);

  if (!open) return null;

  const freeVehicles = (vehicles.data ?? []).filter((v) => v.driver_id === null || v.driver_id === driver?.id);

  return (
    <div
      className="fixed inset-0 z-[105] flex items-center justify-center p-4"
      role="dialog"
      aria-label={editing ? t("Редактировать водителя") : t("Добавить водителя")}
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
      style={{ background: "rgb(var(--bg) / 0.75)" }}
    >
      <div className="max-h-[92vh] w-full max-w-md overflow-y-auto rounded-card border border-line bg-card p-5 shadow-2xl">
        <div className="mb-4 flex items-center gap-3">
          <div className="grid h-9 w-9 flex-none place-items-center rounded-btn bg-accent/15 text-accent">
            {editing ? <Pencil size={18} /> : <UserPlus size={18} />}
          </div>
          <h3 className="text-base font-bold">{editing ? t("Редактировать водителя") : t("Добавить водителя")}</h3>
          <Button variant="ghost" size="icon" className="ml-auto" aria-label={t("Закрыть")} onClick={close}>
            <X size={18} />
          </Button>
        </div>

        <form onSubmit={handleSubmit((data) => save.mutate(data))} className="flex flex-col gap-3" noValidate>
          <div className="flex items-center gap-3">
            <Avatar name={driver?.name || t("Новый водитель")} size={56} src={photoPreview ?? driver?.photo_url} />
            <div className="flex flex-col gap-1 text-sm">
              <Button type="button" variant="outline" size="sm" onClick={() => fileRef.current?.click()}>
                {photo || driver?.photo_url ? t("Заменить фото") : t("Добавить фото")}
              </Button>
              <span className="text-xs text-mut">{t("JPEG/PNG до 5 МБ")}</span>
            </div>
            <input
              ref={fileRef}
              type="file"
              accept="image/jpeg,image/png,image/webp"
              className="sr-only"
              aria-label={t("Фото водителя")}
              data-testid="driver-photo-input"
              onChange={(e) => {
                const f = e.target.files?.[0] ?? null;
                e.target.value = "";
                if (!f) return;
                if (f.size > PHOTO_MAX) {
                  setError("root", { message: t("Фото больше 5 МБ — выберите файл поменьше") });
                  return;
                }
                setPhoto(f);
              }}
            />
          </div>

          <label className="flex flex-col gap-1 text-sm font-semibold">
            {t("ФИО")}
            <input className={inputCls} placeholder={t("Иванов А.С.")} {...register("name")} />
            {errors.name && <span className="text-xs font-normal text-danger">{errors.name.message}</span>}
          </label>

          <label className="flex flex-col gap-1 text-sm font-semibold">
            {t("Депо")}
            <select className={inputCls} {...register("depot_id")}>
              <option value="">{t("Без депо")}</option>
              {(depots.data ?? []).map((d) => (
                <option key={d.id} value={d.id}>
                  {d.name}
                </option>
              ))}
            </select>
          </label>

          <label className="flex flex-col gap-1 text-sm font-semibold">
            {t("Машина")}
            <select className={inputCls} {...register("vehicle_id")}>
              <option value="">{t("Без машины")}</option>
              {freeVehicles.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.plate} · {v.model}
                </option>
              ))}
            </select>
            <span className="text-xs font-normal text-mut">{t("Показаны свободные машины и текущая")}</span>
          </label>

          <label className="flex flex-col gap-1 text-sm font-semibold">
            {t("Телефон")}
            <input type="tel" className={inputCls} placeholder="+77011234567" {...register("phone")} />
            {errors.phone && <span className="text-xs font-normal text-danger">{errors.phone.message}</span>}
          </label>

          <label className="flex flex-col gap-1 text-sm font-semibold">
            {editing ? t("Новый PIN (оставьте пустым, чтобы не менять)") : t("PIN для входа в приложение водителя")}
            <input
              type="password"
              inputMode="numeric"
              autoComplete="new-password"
              maxLength={6}
              className={inputCls}
              placeholder={t("4–6 цифр (необязательно)")}
              {...register("pin")}
            />
            {errors.pin && <span className="text-xs font-normal text-danger">{errors.pin.message}</span>}
          </label>

          {errors.root && (
            <div role="alert" className="rounded-btn bg-danger/10 px-3 py-2 text-sm text-danger">
              {errors.root.message}
            </div>
          )}

          <div className="mt-1 flex justify-end gap-2">
            <Button type="button" variant="outline" onClick={close}>
              {t("Отмена")}
            </Button>
            <Button type="submit" disabled={save.isPending}>
              {save.isPending ? t("Сохраняем…") : editing ? t("Сохранить") : t("Добавить")}
            </Button>
          </div>
        </form>
      </div>
    </div>
  );
}
