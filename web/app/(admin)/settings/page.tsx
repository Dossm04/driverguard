"use client";

/* Страница «Настройки» (ШАГ 11, WEB-9): Скоринг (веса, модификаторы, предпросмотр
   пересчёта), Пороги устройства, Пользователи, Устройства, Уведомления, Внешний вид,
   Хранение данных. Редактирует admin; координатор и наблюдатель видят значения. */

import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import {
  Bell,
  ClipboardCheck,
  Cpu,
  Database,
  Gauge,
  Palette,
  RotateCw,
  Save,
  Sliders,
  UserPlus,
  Users,
} from "lucide-react";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import { formatEventTime } from "@/components/event-modal";
import { ChecklistTab } from "@/components/settings/checklist-tab";
import { Button } from "@/components/ui/button";
import { DataTable, type Column } from "@/components/ui/data-table";
import { EmptyState } from "@/components/ui/empty-state";
import { QueryError } from "@/components/ui/query-error";
import { SectionCard } from "@/components/ui/section-card";
import { Skeleton } from "@/components/ui/skeleton";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";
import { useToast } from "@/components/ui/toast";
import {
  api,
  currentUser,
  type DeviceRow,
  type NotificationSettingsValue,
  type RetentionSettingsValue,
  type ScoringPreviewRow,
  type ScoringSettingsValue,
  type SettingOut,
  type ThresholdSettingsValue,
  type UserRow,
} from "@/lib/api";
import { EVENT_LABELS } from "@/lib/events";
import { LangList } from "@/components/ui/lang-switch";
import { t, perLang } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";
import { cn } from "@/lib/utils";

const TABS = perLang(() => [
  { id: "scoring", title: t("Скоринг"), icon: Gauge },
  { id: "thresholds", title: t("Пороги устройства"), icon: Sliders },
  { id: "checklist", title: t("Чек-лист"), icon: ClipboardCheck },
  { id: "users", title: t("Пользователи"), icon: Users },
  { id: "devices", title: t("Устройства"), icon: Cpu },
  { id: "notifications", title: t("Уведомления"), icon: Bell },
  { id: "appearance", title: t("Внешний вид"), icon: Palette },
  { id: "retention", title: t("Хранение данных"), icon: Database },
] as const);
type TabId = (typeof TABS)[number]["id"];

const ROLE_PILLS: Record<string, { label: string; tone: PillTone }> = perLang(() => ({
  admin: { label: t("Администратор"), tone: "accent" },
  coordinator: { label: t("Координатор"), tone: "ok" },
  viewer: { label: t("Наблюдатель"), tone: "offline" },
  driver: { label: t("Водитель"), tone: "warn" },
}));

const inputCls =
  "h-9 w-full rounded-btn border border-line bg-page px-3 text-sm num focus:outline-none focus:ring-2 focus:ring-accent disabled:opacity-60";

function NumberField({
  label,
  value,
  onChange,
  min,
  max,
  step = 1,
  unit,
  disabled,
}: {
  label: string;
  value: number;
  onChange: (v: number) => void;
  min: number;
  max: number;
  step?: number;
  unit?: string;
  disabled?: boolean;
}) {
  // Локальный текст: пока поле пустое, родителю ничего не шлём (иначе «стёр цифру» = 0)
  useLangVersion();
  const [text, setText] = useState(String(value));
  useEffect(() => setText(String(value)), [value]);
  return (
    <label className="flex flex-col gap-1 text-xs font-semibold text-mut">
      <span className="truncate">{label}</span>
      <span className="flex items-center gap-2">
        <input
          type="number"
          className={inputCls}
          value={text}
          min={min}
          max={max}
          step={step}
          disabled={disabled}
          onChange={(e) => {
            setText(e.target.value);
            const n = Number(e.target.value);
            if (e.target.value !== "" && Number.isFinite(n)) onChange(n);
          }}
        />
        {unit && <span className="whitespace-nowrap">{unit}</span>}
      </span>
    </label>
  );
}

function VersionLine({ setting }: { setting?: SettingOut<unknown> }) {
  useLangVersion();
  if (!setting) return null;
  return (
    <span className="num text-xs text-mut">
      {t("версия")}{" "}{setting.version}
      {setting.updated_by_name ? ` · ${setting.updated_by_name}` : ""}
      {setting.updated_at ? ` · ${formatEventTime(setting.updated_at)}` : ""}
    </span>
  );
}

function useSaveSetting(key: string, invalidate: string[] = []) {
  const toast = useToast();
  const queryClient = useQueryClient();
  return useMutation({
    mutationFn: (value: unknown) =>
      api<SettingOut>(`/settings/${key}`, { method: "PUT", body: JSON.stringify({ value }) }),
    onSuccess: (saved) => {
      toast(t("Сохранено · версия {0}", saved.version));
      for (const k of ["settings", ...invalidate]) queryClient.invalidateQueries({ queryKey: [k] });
    },
    onError: (e) => toast(e instanceof Error ? e.message : t("Не удалось сохранить")),
  });
}

/* ── Скоринг ─────────────────────────────────────────────────────────── */
function ScoringTab({ setting, isAdmin }: { setting?: SettingOut<ScoringSettingsValue>; isAdmin: boolean }) {
  useLangVersion();
  const [value, setValue] = useState<ScoringSettingsValue | null>(() =>
    setting ? structuredClone(setting.value) : null,
  );
  const [preview, setPreview] = useState<ScoringPreviewRow[] | null>(null);
  const save = useSaveSetting("scoring", ["leaderboard", "summary", "red-zone", "driver-profile", "report"]);
  const toast = useToast();
  const previewMutation = useMutation({
    mutationFn: (v: ScoringSettingsValue) =>
      api<ScoringPreviewRow[]>("/settings/scoring/preview", { method: "POST", body: JSON.stringify(v) }),
    onSuccess: setPreview,
    onError: (e) => toast(e instanceof Error ? e.message : t("Не удалось рассчитать")),
  });
  if (!value) return <Skeleton className="h-[320px] rounded-card" />;

  const columns: Column<ScoringPreviewRow>[] = [
    { key: "name", header: t("Водитель"), render: (r) => <b>{r.name}</b> },
    { key: "now", header: t("Сейчас"), render: (r) => <span className="num">{r.score_now}</span> },
    { key: "new", header: t("Станет"), render: (r) => <b className="num">{r.score_new}</b> },
    {
      key: "delta",
      header: "Δ",
      render: (r) =>
        r.delta === 0 ? (
          <span className="text-mut">—</span>
        ) : (
          <span className={cn("num font-bold", r.delta > 0 ? "text-ok" : "text-danger")}>
            {r.delta > 0 ? "▲" : "▼"} {Math.abs(r.delta)}
          </span>
        ),
    },
  ];

  return (
    <div className="grid gap-3 xl:grid-cols-[3fr_2fr]">
      <SectionCard
        title={t("Веса событий")}
        subtitle={t("штраф в баллах за событие (0–50)")}
        action={<VersionLine setting={setting} />}
      >
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
          {Object.keys(EVENT_LABELS).map((type) => (
            <NumberField
              key={type}
              label={EVENT_LABELS[type]}
              value={value.weights[type] ?? 0}
              min={0}
              max={50}
              step={0.5}
              disabled={!isAdmin}
              onChange={(v) => setValue({ ...value, weights: { ...value.weights, [type]: v } })}
            />
          ))}
        </div>
        <h4 className="mb-2 mt-5 text-sm font-bold">{t("Модификаторы скорости")}</h4>
        <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          <NumberField
            label={t("Порог «быстро»")}
            unit={t("км/ч")}
            value={value.modifiers.fast_kmh}
            min={20}
            max={150}
            disabled={!isAdmin}
            onChange={(v) => setValue({ ...value, modifiers: { ...value.modifiers, fast_kmh: v } })}
          />
          <NumberField
            label={t("Множитель телефон/сон на скорости")}
            unit="×"
            value={value.modifiers.fast_mult}
            min={1}
            max={3}
            step={0.1}
            disabled={!isAdmin}
            onChange={(v) => setValue({ ...value, modifiers: { ...value.modifiers, fast_mult: v } })}
          />
          <NumberField
            label={t("Порог «стоим»")}
            unit={t("км/ч")}
            value={value.modifiers.slow_kmh}
            min={0}
            max={20}
            disabled={!isAdmin}
            onChange={(v) => setValue({ ...value, modifiers: { ...value.modifiers, slow_kmh: v } })}
          />
          <NumberField
            label={t("Множитель телефона на стоянке")}
            unit="×"
            value={value.modifiers.slow_mult}
            min={0}
            max={1}
            step={0.1}
            disabled={!isAdmin}
            onChange={(v) => setValue({ ...value, modifiers: { ...value.modifiers, slow_mult: v } })}
          />
        </div>
        <div className="mt-4 flex flex-wrap gap-2">
          <Button variant="outline" disabled={previewMutation.isPending} onClick={() => previewMutation.mutate(value)}>
            <Gauge size={16} /> {previewMutation.isPending ? t("Считаем…") : t("Предпросмотр пересчёта")}
          </Button>
          {isAdmin && (
            <Button disabled={save.isPending} onClick={() => save.mutate(value, { onSuccess: () => setPreview(null) })}>
              <Save size={16} /> {save.isPending ? t("Сохраняем…") : t("Сохранить")}
            </Button>
          )}
        </div>
        <p className="mt-3 text-xs leading-relaxed text-mut">
          {t("Score = clamp(40..100, 100 − Σ(вес × модификатор скорости) × 7/дней × 0.8 + бонус серии ≤10). Изменения версионируются и попадают в аудит; Score пересчитывается сразу.")}
        </p>
      </SectionCard>
      <SectionCard title={t("Предпросмотр пересчёта")} subtitle={t("недельный Score водителей при новых весах")}>
        {preview === null ? (
          <EmptyState icon={Gauge} title={t("Ещё не считали")} description={t("Измените веса и нажмите «Предпросмотр пересчёта».")} />
        ) : (
          <DataTable columns={columns} rows={preview} rowKey={(r) => r.driver_id} />
        )}
      </SectionCard>
    </div>
  );
}

/* ── Пороги устройства ──────────────────────────────────────────────── */
const THRESHOLD_FIELDS: { key: keyof ThresholdSettingsValue; label: string; unit: string; min: number; max: number; step?: number }[] = perLang(() => [
  { key: "MICROSLEEP_MS", label: t("Микросон: глаза закрыты"), unit: t("мс"), min: 500, max: 5000, step: 100 },
  { key: "PERCLOS_WARN", label: t("PERCLOS: доля закрытых глаз за 60 с"), unit: t("доля"), min: 0.05, max: 0.6, step: 0.01 },
  { key: "YAWN_MS", label: t("Зевок: рот открыт"), unit: t("мс"), min: 500, max: 5000, step: 100 },
  { key: "NOD_MS", label: t("Клевок головой"), unit: t("мс"), min: 500, max: 5000, step: 100 },
  { key: "NOFACE_MS", label: t("Лицо не видно (саботаж)"), unit: t("мс"), min: 1000, max: 10000, step: 500 },
  { key: "speed_limit_highway", label: t("Лимит скорости: трасса"), unit: t("км/ч"), min: 60, max: 130 },
  { key: "speed_limit_city", label: t("Лимит скорости: город"), unit: t("км/ч"), min: 30, max: 80 },
]);

function ThresholdsTab({ setting, isAdmin }: { setting?: SettingOut<ThresholdSettingsValue>; isAdmin: boolean }) {
  useLangVersion();
  const [value, setValue] = useState<ThresholdSettingsValue | null>(() => (setting ? { ...setting.value } : null));
  const save = useSaveSetting("thresholds");
  if (!value) return <Skeleton className="h-[240px] rounded-card" />;
  return (
    <SectionCard
      title={t("Пороги устройства")}
      subtitle={t("уходят на устройства через /devices/{id}/config (SYS-4)")}
      action={<VersionLine setting={setting} />}
    >
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-3">
        {THRESHOLD_FIELDS.map((f) => (
          <NumberField
            key={f.key}
            label={f.label}
            unit={f.unit}
            value={value[f.key]}
            min={f.min}
            max={f.max}
            step={f.step}
            disabled={!isAdmin}
            onChange={(v) => setValue({ ...value, [f.key]: v })}
          />
        ))}
      </div>
      {isAdmin && (
        <Button className="mt-4" disabled={save.isPending} onClick={() => save.mutate(value)}>
          <Save size={16} /> {save.isPending ? t("Сохраняем…") : t("Сохранить")}
        </Button>
      )}
    </SectionCard>
  );
}

/* ── Пользователи ───────────────────────────────────────────────────── */
function UsersTab({ isAdmin, meId }: { isAdmin: boolean; meId: number | null }) {
  useLangVersion();
  const toast = useToast();
  const queryClient = useQueryClient();
  const users = useQuery({
    queryKey: ["users"],
    queryFn: () => api<UserRow[]>("/users"),
    enabled: isAdmin,
    refetchInterval: 30_000, // «кто онлайн» обновляется само
  });
  const onlineCount = users.data?.filter((u) => u.online).length ?? 0;
  const [form, setForm] = useState({ name: "", email: "", role: "coordinator", password: "" });
  const create = useMutation({
    mutationFn: () => api<UserRow>("/users", { method: "POST", body: JSON.stringify(form) }),
    onSuccess: (u) => {
      toast(t("Пользователь добавлен: {0}", u.name));
      setForm({ name: "", email: "", role: "coordinator", password: "" });
      queryClient.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (e) => toast(e instanceof Error ? e.message : t("Не удалось добавить")),
  });
  const setRole = useMutation({
    mutationFn: ({ id, role }: { id: number; role: string }) =>
      api<UserRow>(`/users/${id}`, { method: "PATCH", body: JSON.stringify({ role }) }),
    onSuccess: (u) => {
      toast(t("Роль изменена: {0}", u.name));
      queryClient.invalidateQueries({ queryKey: ["users"] });
    },
    onError: (e) => toast(e instanceof Error ? e.message : t("Не удалось изменить роль")),
  });
  if (!isAdmin) {
    return <EmptyState icon={Users} title={t("Только для администратора")} description={t("Управление пользователями и ролями доступно администратору.")} />;
  }
  const columns: Column<UserRow>[] = [
    { key: "name", header: t("Имя"), render: (u) => <b>{u.name}</b> },
    { key: "login", header: t("Email / телефон"), render: (u) => <span className="num text-mut">{u.email ?? u.phone ?? "—"}</span> },
    {
      key: "role",
      header: t("Роль"),
      render: (u) =>
        u.role === "driver" || u.id === meId ? (
          <StatusPill tone={ROLE_PILLS[u.role].tone}>{ROLE_PILLS[u.role].label}</StatusPill>
        ) : (
          <select
            aria-label={t("Роль: {0}", u.name)}
            className="h-8 rounded-btn border border-line bg-cardh px-2 text-xs font-semibold"
            value={u.role}
            disabled={setRole.isPending}
            onChange={(e) => setRole.mutate({ id: u.id, role: e.target.value })}
          >
            <option value="admin">{t("Администратор")}</option>
            <option value="coordinator">{t("Координатор")}</option>
            <option value="viewer">{t("Наблюдатель")}</option>
          </select>
        ),
    },
    {
      key: "online",
      header: t("Онлайн"),
      render: (u) =>
        u.online ? (
          <StatusPill tone="ok">{t("Онлайн")}</StatusPill>
        ) : (
          <span className="num text-xs text-mut">{u.last_seen ? formatEventTime(u.last_seen) : t("не заходил")}</span>
        ),
    },
    { key: "created", header: t("Создан"), render: (u) => <span className="num text-mut">{u.created_at ? formatEventTime(u.created_at) : "—"}</span> },
  ];
  return (
    <div className="grid gap-3 xl:grid-cols-[3fr_2fr]">
      <SectionCard
        title={t("Пользователи и роли")}
        subtitle={
          users.data
            ? t("онлайн {0} из {1} · водители создаются в разделе «Водители»", onlineCount, users.data.length)
            : t("учётки водителей создаются в разделе «Водители»")
        }
      >
        {users.isError ? (
          <QueryError error={users.error} onRetry={() => users.refetch()} />
        ) : users.isLoading || !users.data ? (
          <Skeleton className="h-[200px]" />
        ) : (
          <DataTable columns={columns} rows={users.data} rowKey={(u) => u.id} />
        )}
      </SectionCard>
      <SectionCard title={t("Добавить пользователя")} subtitle={t("доступ к панели по email и паролю")}>
        <form
          className="flex flex-col gap-3"
          onSubmit={(e) => {
            e.preventDefault();
            create.mutate();
          }}
        >
          <label className="flex flex-col gap-1 text-xs font-semibold text-mut">
            {t("Имя")}
            <input className={inputCls} required minLength={3} placeholder={t("Иванова А.С.")} value={form.name} onChange={(e) => setForm({ ...form, name: e.target.value })} />
          </label>
          <label className="flex flex-col gap-1 text-xs font-semibold text-mut">
            Email
            <input className={inputCls} type="email" required placeholder="user@driverguard.kz" value={form.email} onChange={(e) => setForm({ ...form, email: e.target.value })} />
          </label>
          <label className="flex flex-col gap-1 text-xs font-semibold text-mut">
            {t("Роль")}
            <select className={inputCls} value={form.role} onChange={(e) => setForm({ ...form, role: e.target.value })}>
              <option value="coordinator">{t("Координатор")}</option>
              <option value="viewer">{t("Наблюдатель (только чтение)")}</option>
              <option value="admin">{t("Администратор")}</option>
            </select>
          </label>
          <label className="flex flex-col gap-1 text-xs font-semibold text-mut">
            {t("Пароль")}
            <input className={inputCls} type="password" autoComplete="new-password" required minLength={8} placeholder={t("не менее 8 символов")} value={form.password} onChange={(e) => setForm({ ...form, password: e.target.value })} />
          </label>
          <Button type="submit" disabled={create.isPending}>
            <UserPlus size={16} /> {create.isPending ? t("Добавляем…") : t("Добавить пользователя")}
          </Button>
        </form>
      </SectionCard>
    </div>
  );
}

/* ── Устройства ─────────────────────────────────────────────────────── */
function DevicesTab({ canManage }: { canManage: boolean }) {
  useLangVersion();
  const toast = useToast();
  const queryClient = useQueryClient();
  const devices = useQuery({
    queryKey: ["devices"],
    queryFn: () => api<DeviceRow[]>("/devices"),
    refetchInterval: 30_000,
  });
  const reboot = useMutation({
    mutationFn: (id: number) => api<DeviceRow>(`/devices/${id}/reboot`, { method: "POST" }),
    onSuccess: (d) => {
      toast(t("Перезагрузка запрошена: {0}", d.serial));
      queryClient.invalidateQueries({ queryKey: ["devices"] });
    },
    onError: (e) => toast(e instanceof Error ? e.message : t("Не удалось отправить команду")),
  });
  const columns: Column<DeviceRow>[] = [
    { key: "serial", header: t("Серийный №"), render: (d) => <b className="num">{d.serial}</b> },
    { key: "plate", header: t("Машина"), render: (d) => <span className="num">{d.vehicle_plate ?? "—"}</span> },
    { key: "fw", header: t("Прошивка"), render: (d) => <span className="num text-mut">{d.fw_version ?? "—"}</span> },
    { key: "model", header: t("Модель ИИ"), render: (d) => <span className="num text-mut">{d.model_version ?? "—"}</span> },
    { key: "seen", header: t("Последний онлайн"), render: (d) => <span className="num">{d.last_seen ? formatEventTime(d.last_seen) : t("никогда")}</span> },
    {
      key: "status",
      header: t("Статус"),
      render: (d) =>
        d.status === "reboot_requested" ? (
          <StatusPill tone="warn">{t("Перезагрузка запрошена")}</StatusPill>
        ) : d.online ? (
          <StatusPill tone="ok">{t("Онлайн")}</StatusPill>
        ) : (
          <StatusPill tone="offline">{t("Офлайн")}</StatusPill>
        ),
    },
    {
      key: "actions",
      header: "",
      className: "text-right",
      render: (d) =>
        canManage ? (
          <Button
            variant="outline"
            size="sm"
            aria-label={t("Перезагрузить {0}", d.serial)}
            disabled={reboot.isPending || d.status === "reboot_requested"}
            onClick={() => reboot.mutate(d.id)}
          >
            <RotateCw size={14} /> {t("Перезагрузить")}
          </Button>
        ) : null,
    },
  ];
  const online = (devices.data ?? []).filter((d) => d.online).length;
  const total = devices.data?.length ?? 0;
  return (
    <SectionCard title={t("Устройства")} subtitle={t("онлайн — heartbeat за последние 5 минут (BE-17)")}>
      {devices.data && (
        <div className="mb-3 flex flex-wrap items-center gap-2 text-sm" data-testid="devices-summary">
          <StatusPill tone="ok">{t("Онлайн")}{" "}{online}</StatusPill>
          <StatusPill tone="offline">{t("Офлайн")}{" "}{total - online}</StatusPill>
          <span className="num text-mut">{t("всего")}{" "}{total}</span>
        </div>
      )}
      {devices.isError ? (
        <QueryError error={devices.error} onRetry={() => devices.refetch()} />
      ) : devices.isLoading || !devices.data ? (
        <Skeleton className="h-[220px]" />
      ) : (
        <DataTable columns={columns} rows={devices.data} rowKey={(d) => d.id} />
      )}
      <p className="mt-3 text-xs text-mut">{t("Команда «Перезагрузить» доставляется устройству при следующем запросе конфигурации.")}</p>
    </SectionCard>
  );
}

/* ── Уведомления ────────────────────────────────────────────────────── */
function NotificationsTab({ setting, isAdmin }: { setting?: SettingOut<NotificationSettingsValue>; isAdmin: boolean }) {
  useLangVersion();
  const [value, setValue] = useState<NotificationSettingsValue | null>(() =>
    setting ? { ...setting.value, critical_types: [...setting.value.critical_types] } : null,
  );
  const save = useSaveSetting("notifications");
  if (!value) return <Skeleton className="h-[240px] rounded-card" />;
  const toggle = (type: string) =>
    setValue({
      ...value,
      critical_types: value.critical_types.includes(type)
        ? value.critical_types.filter((t) => t !== type)
        : [...value.critical_types, type],
    });
  return (
    <SectionCard title={t("Telegram-алерты координатору")} subtitle={t("бот перечитывает эти настройки каждые 15 с")} action={<VersionLine setting={setting} />}>
      <label className="flex max-w-sm flex-col gap-1 text-xs font-semibold text-mut">
        {t("Chat ID координатора")}
        <input
          className={inputCls}
          placeholder={t("например, 123456789 или -1001234567890")}
          value={value.telegram_chat_id}
          disabled={!isAdmin}
          onChange={(e) => setValue({ ...value, telegram_chat_id: e.target.value })}
        />
      </label>
      <h4 className="mb-2 mt-4 text-sm font-bold">{t("Какие типы событий слать")}</h4>
      <div className="grid gap-2 sm:grid-cols-2 lg:grid-cols-3">
        {Object.entries(EVENT_LABELS).map(([type, label]) => (
          <label key={type} className="flex items-center gap-2 text-sm">
            <input
              type="checkbox"
              className="h-4 w-4 accent-[rgb(var(--accent))]"
              checked={value.critical_types.includes(type)}
              disabled={!isAdmin}
              onChange={() => toggle(type)}
            />
            {label}
          </label>
        ))}
      </div>
      {isAdmin && (
        <Button className="mt-4" disabled={save.isPending} onClick={() => save.mutate(value)}>
          <Save size={16} /> {save.isPending ? t("Сохраняем…") : t("Сохранить")}
        </Button>
      )}
    </SectionCard>
  );
}

/* ── Внешний вид ────────────────────────────────────────────────────── */
function AppearanceTab() {
  useLangVersion();
  const { theme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const options = [
    { value: "dark", label: t("Тёмная"), hint: t("как в Figma, по умолчанию") },
    { value: "light", label: t("Светлая"), hint: t("для яркого офиса и проектора") },
    { value: "system", label: t("Системная"), hint: t("следует настройке ОС") },
  ];
  return (
    <div className="grid gap-3 xl:grid-cols-2">
      <SectionCard title={t("Тема")} subtitle={t("сохраняется в этом браузере (UX-1)")}>
        <div className="flex flex-col gap-2" role="radiogroup" aria-label={t("Тема")}>
          {options.map((o) => (
            <label key={o.value} className="flex cursor-pointer items-center gap-3 rounded-btn border border-line p-3 hover:bg-cardh">
              <input
                type="radio"
                name="theme"
                value={o.value}
                className="h-4 w-4 accent-[rgb(var(--accent))]"
                checked={mounted && theme === o.value}
                onChange={() => setTheme(o.value)}
              />
              <span>
                <b className="block text-sm">{o.label}</b>
                <span className="block text-xs text-mut">{o.hint}</span>
              </span>
            </label>
          ))}
        </div>
      </SectionCard>
      <SectionCard title={t("Язык интерфейса")} subtitle={t("сохраняется в этом браузере отдельно для панели и приложения водителя")}>
        <LangList />
      </SectionCard>
    </div>
  );
}

/* ── Хранение данных ────────────────────────────────────────────────── */
function RetentionTab({ setting, isAdmin }: { setting?: SettingOut<RetentionSettingsValue>; isAdmin: boolean }) {
  useLangVersion();
  const [value, setValue] = useState<RetentionSettingsValue | null>(() => (setting ? { ...setting.value } : null));
  const save = useSaveSetting("retention");
  if (!value) return <Skeleton className="h-[200px] rounded-card" />;
  return (
    <SectionCard title={t("Сроки хранения")} subtitle={t("ТЗ 6.2.3: события 12 мес, клипы 90 дней, фото 180 дней, аудит 3 года")} action={<VersionLine setting={setting} />}>
      <div className="grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
        <NumberField label={t("События и агрегаты")} unit={t("мес")} value={value.events_months} min={1} max={36} disabled={!isAdmin} onChange={(v) => setValue({ ...value, events_months: v })} />
        <NumberField label={t("Видеоклипы")} unit={t("дней")} value={value.clips_days} min={7} max={365} disabled={!isAdmin} onChange={(v) => setValue({ ...value, clips_days: v })} />
        <NumberField label={t("Фото чек-листов")} unit={t("дней")} value={value.photos_days} min={7} max={365} disabled={!isAdmin} onChange={(v) => setValue({ ...value, photos_days: v })} />
        <NumberField label={t("Аудит действий")} unit={t("лет")} value={value.audit_years} min={1} max={10} disabled={!isAdmin} onChange={(v) => setValue({ ...value, audit_years: v })} />
      </div>
      {isAdmin && (
        <Button className="mt-4" disabled={save.isPending} onClick={() => save.mutate(value)}>
          <Save size={16} /> {save.isPending ? t("Сохраняем…") : t("Сохранить")}
        </Button>
      )}
    </SectionCard>
  );
}

/* ── Страница ───────────────────────────────────────────────────────── */
export default function SettingsPage() {
  useLangVersion();
  const [tab, setTab] = useState<TabId>("scoring");
  const [role, setRole] = useState<string | null>(null);
  const [meId, setMeId] = useState<number | null>(null);
  useEffect(() => {
    const me = currentUser();
    setRole(me?.role ?? null);
    setMeId(me?.id ?? null);
    // /settings?tab=devices — переход из виджета «Устройств онлайн» в сайдбаре
    const wanted = new URLSearchParams(window.location.search).get("tab");
    if (wanted && TABS.some((t) => t.id === wanted)) setTab(wanted as TabId);
  }, []);
  const isAdmin = role === "admin";
  const canManage = role === "admin" || role === "coordinator";

  const settings = useQuery({ queryKey: ["settings"], queryFn: () => api<SettingOut[]>("/settings") });
  const byKey = Object.fromEntries((settings.data ?? []).map((s) => [s.key, s])) as Record<
    string,
    SettingOut<unknown>
  >;

  return (
    <div className="flex flex-col gap-3">
      <div className="flex flex-wrap gap-1.5" role="tablist" aria-label={t("Разделы настроек")}>
        {TABS.map((t) => (
          <button
            key={t.id}
            role="tab"
            aria-selected={tab === t.id}
            onClick={() => setTab(t.id)}
            className={cn(
              "flex items-center gap-1.5 rounded-btn border border-line px-3 py-1.5 text-sm font-bold text-mut transition-colors hover:text-txt",
              tab === t.id && "border-accent bg-accent/10 text-accent",
            )}
          >
            <t.icon size={15} /> {t.title}
          </button>
        ))}
        {role && !isAdmin && (
          <span className="ml-auto self-center text-xs text-mut">{t("Изменять настройки может только администратор")}</span>
        )}
      </div>

      {tab === "users" ? (
        <UsersTab isAdmin={isAdmin} meId={meId} />
      ) : tab === "devices" ? (
        <DevicesTab canManage={canManage} />
      ) : tab === "appearance" ? (
        <AppearanceTab />
      ) : tab === "checklist" ? (
        <ChecklistTab isAdmin={isAdmin} />
      ) : settings.isError ? (
        <QueryError error={settings.error} onRetry={() => settings.refetch()} />
      ) : tab === "scoring" ? (
        <ScoringTab
          key={`scoring-${byKey.scoring?.version ?? "loading"}`}
          setting={byKey.scoring as SettingOut<ScoringSettingsValue> | undefined}
          isAdmin={isAdmin}
        />
      ) : tab === "thresholds" ? (
        <ThresholdsTab
          key={`thresholds-${byKey.thresholds?.version ?? "loading"}`}
          setting={byKey.thresholds as SettingOut<ThresholdSettingsValue> | undefined}
          isAdmin={isAdmin}
        />
      ) : tab === "notifications" ? (
        <NotificationsTab
          key={`notifications-${byKey.notifications?.version ?? "loading"}`}
          setting={byKey.notifications as SettingOut<NotificationSettingsValue> | undefined}
          isAdmin={isAdmin}
        />
      ) : (
        <RetentionTab
          key={`retention-${byKey.retention?.version ?? "loading"}`}
          setting={byKey.retention as SettingOut<RetentionSettingsValue> | undefined}
          isAdmin={isAdmin}
        />
      )}
    </div>
  );
}
