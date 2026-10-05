"use client";

import { useQuery } from "@tanstack/react-query";
import { Bell, CircleHelp, LogOut, Menu, Moon, Search, Sun } from "lucide-react";
import { useTheme } from "next-themes";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import { formatEventTime } from "@/components/event-modal";
import { EVENT_ICONS, eventTitle } from "@/lib/events";
import { type EventItem } from "@/lib/api";

import { NAV_ITEMS } from "@/components/layout/sidebar";
import { LangSwitch } from "@/components/ui/lang-switch";
import { t, perLang } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";
import { useSummary } from "@/lib/queries";
import { Avatar } from "@/components/ui/avatar";
import { Button } from "@/components/ui/button";
import { api, currentUser } from "@/lib/api";
import { usePeriod, type PeriodValue } from "@/lib/period";
import { logout } from "@/lib/auth";
import { cn } from "@/lib/utils";

const PERIODS: { value: PeriodValue; label: string }[] = perLang(() => [
  { value: "today", label: t("Сегодня") },
  { value: "7d", label: t("7 дней") },
  { value: "30d", label: t("30 дней") },
]);

const ROLE_LABELS: Record<string, string> = perLang(() => ({
  admin: t("Координатор"),
  coordinator: t("Координатор"),
  viewer: t("Руководитель"),
  driver: t("Водитель"),
}));

function ThemeToggle() {
  useLangVersion();
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  return (
    <Button
      variant="outline"
      size="icon"
      data-tour="theme"
      aria-label={t("Переключить тему")}
      onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}
    >
      {mounted && resolvedTheme === "dark" ? <Sun size={18} /> : <Moon size={18} />}
    </Button>
  );
}

/* Колокольчик: последние критические события с переходом в «События» (WEB-10) */
function Notifications({ count }: { count: number }) {
  useLangVersion();
  const router = useRouter();
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const latest = useQuery({
    queryKey: ["critical-latest", 5],
    queryFn: () => api<EventItem[]>("/dashboard/critical-latest?limit=5"),
    enabled: open,
  });
  useEffect(() => {
    if (!open) return;
    const onDown = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node)) setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && setOpen(false);
    document.addEventListener("mousedown", onDown);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDown);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);
  return (
    <div ref={ref} className="relative">
      <Button
        variant="outline"
        size="icon"
        className="relative"
        data-tour="bell"
        aria-label={t("Уведомления")}
        aria-expanded={open}
        onClick={() => setOpen((v) => !v)}
      >
        <Bell size={18} />
        {count ? (
          <span className="num absolute -right-1.5 -top-1.5 rounded-full bg-danger px-1.5 py-px text-[10px] font-bold text-onaccent">
            {count}
          </span>
        ) : null}
      </Button>
      {open && (
        <div
          role="dialog"
          aria-label={t("Последние критические события")}
          className="absolute right-0 top-11 z-40 w-80 rounded-card border border-line bg-card p-2 shadow-lg"
        >
          <div className="flex items-center justify-between px-2 pb-1 pt-1 text-[11px] font-bold uppercase tracking-wide text-mut">
            {t("Критические события")}
            <span className="num">{count} {t("новых")}</span>
          </div>
          {latest.isLoading && <div className="px-2 py-3 text-xs text-mut">{t("Загружаем…")}</div>}
          {latest.isError && <div className="px-2 py-3 text-xs text-danger">{t("Не удалось загрузить")}</div>}
          {latest.data?.length === 0 && <div className="px-2 py-3 text-xs text-mut">{t("Критических событий нет")}</div>}
          {latest.data?.map((e) => {
            const Icon = EVENT_ICONS[e.type];
            return (
              <button
                key={e.uuid}
                type="button"
                onClick={() => {
                  setOpen(false);
                  router.push("/events");
                }}
                className="flex w-full items-center gap-2.5 rounded-btn px-2 py-2 text-left hover:bg-cardh"
              >
                <span className="grid h-8 w-8 shrink-0 place-items-center rounded-full bg-danger/15 text-danger">
                  {Icon ? <Icon size={16} /> : null}
                </span>
                <span className="min-w-0 flex-1">
                  <span className="block truncate text-sm font-bold">{eventTitle(e.type, e.value)}</span>
                  <span className="block truncate text-xs text-mut">
                    {e.driver_name ?? "—"} · {e.vehicle_plate ?? "—"} · <span className="num">{formatEventTime(e.ts)}</span>
                  </span>
                </span>
              </button>
            );
          })}
          <button
            type="button"
            onClick={() => {
              setOpen(false);
              router.push("/events");
            }}
            className="mt-1 w-full rounded-btn px-2 py-2 text-center text-xs font-bold text-accent hover:bg-cardh"
          >
            {t("Все события →")}
          </button>
        </div>
      )}
    </div>
  );
}

export function Topbar({ onStartTour, onMenu }: { onStartTour: () => void; onMenu?: () => void }) {
  useLangVersion();
  const pathname = usePathname();
  const router = useRouter();
  const [query, setQuery] = useState("");
  const { period, setPeriod } = usePeriod();
  const { data: summary } = useSummary();
  const user = currentUser();
  // Префикс-матч: вложенные маршруты (/drivers/5) наследуют заголовок раздела
  const title =
    NAV_ITEMS.find(
      (n) => pathname === n.href || (n.href !== "/" && pathname.startsWith(`${n.href}/`)),
    )?.title ?? "DriverGuard";

  return (
    <header className="flex items-center gap-2 border-b border-line bg-sidebar px-3 py-3 md:gap-3 md:px-5">
      <Button variant="outline" size="icon" className="lg:hidden" aria-label={t("Открыть меню")} onClick={onMenu}>
        <Menu size={18} />
      </Button>
      <h1 className="truncate text-lg font-bold">{title}</h1>

      <div className="relative ml-auto hidden md:block">
        <Search size={16} className="absolute left-3 top-1/2 -translate-y-1/2 text-mut" />
        <input
          className="h-9 w-56 rounded-btn border border-line bg-card pl-9 pr-3 text-sm text-txt placeholder:text-mut focus:outline-none focus:ring-2 focus:ring-accent"
          placeholder={t("Поиск водителя или машины…")}
          aria-label={t("Поиск")}
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter" && query.trim()) {
              router.push(`/drivers?q=${encodeURIComponent(query.trim())}`);
            }
          }}
        />
      </div>

      {/* На узких экранах сегмент периода заменяется компактным select */}
      <select
        aria-label={t("Период")}
        value={period}
        onChange={(e) => setPeriod(e.target.value as PeriodValue)}
        className="h-9 rounded-btn border border-line bg-card px-2 text-xs font-bold text-txt sm:hidden"
      >
        {PERIODS.map((p) => (
          <option key={p.value} value={p.value}>
            {p.label}
          </option>
        ))}
      </select>
      <div
        className="hidden rounded-btn border border-line bg-card p-0.5 sm:flex"
        data-tour="period"
        role="tablist"
        aria-label={t("Период")}
      >
        {PERIODS.map((p) => (
          <button
            key={p.value}
            role="tab"
            aria-selected={period === p.value}
            onClick={() => setPeriod(p.value)}
            className={cn(
              "rounded-[10px] px-3 py-1.5 text-xs font-bold text-mut transition-colors",
              period === p.value && "bg-accent text-onaccent",
            )}
          >
            {p.label}
          </button>
        ))}
      </div>

      <Notifications count={summary?.badges.new_events ?? 0} />

      <Button
        variant="outline"
        size="icon"
        data-tour="help"
        aria-label={t("Показать подсказки")}
        onClick={onStartTour}
      >
        <CircleHelp size={18} />
      </Button>

      <LangSwitch className="hidden xl:flex" />
      <ThemeToggle />

      <div className="flex items-center gap-2 border-l border-line pl-3">
        <Avatar name={user?.name ?? "?"} size={34} />
        <div className="hidden leading-tight lg:block">
          <div className="text-sm font-bold">{user?.name?.split(" ")[0] ?? "—"}</div>
          <div className="text-[11px] text-mut">{ROLE_LABELS[user?.role ?? ""] ?? ""}</div>
        </div>
        <Button variant="ghost" size="icon" aria-label={t("Выйти")} onClick={logout}>
          <LogOut size={18} />
        </Button>
      </div>
    </header>
  );
}
