"use client";

import {
  ClipboardCheck,
  FileBarChart,
  LayoutDashboard,
  Map,
  Settings,
  Shield,
  TriangleAlert,
  Trophy,
  Users,
  Wifi,
  X,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect } from "react";

import { t, perLang } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";
import { useSummary } from "@/lib/queries";
import { cn, pluralRu } from "@/lib/utils";

export const NAV_ITEMS = perLang(() => [
  { href: "/", title: t("Обзор"), icon: LayoutDashboard },
  { href: "/live-map", title: t("Live-карта"), icon: Map },
  { href: "/events", title: t("События"), icon: TriangleAlert, badge: true },
  { href: "/leaderboard", title: t("Лидерборд"), icon: Trophy },
  { href: "/drivers", title: t("Водители"), icon: Users },
  { href: "/checklists", title: t("Чек-листы"), icon: ClipboardCheck },
  { href: "/reports", title: t("Отчёты"), icon: FileBarChart },
  { href: "/settings", title: t("Настройки"), icon: Settings },
] as const);

/* ≥ lg (1024px) — постоянная колонка 236px; ниже — выдвижная панель (drawer) по кнопке
   меню в топбаре, закрывается по ссылке, крестику, скриму и Esc (ТЗ: мобильная версия админки). */
export function Sidebar({ open = false, onClose }: { open?: boolean; onClose?: () => void }) {
  useLangVersion();
  const pathname = usePathname();
  const { data: summary } = useSummary();
  const online = summary?.vehicles.online;
  const total = summary?.vehicles.total;
  const offline = online !== undefined && total !== undefined ? total - online : undefined;

  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => e.key === "Escape" && onClose?.();
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose]);

  return (
    <>
      {open && (
        <button
          type="button"
          aria-label={t("Закрыть меню")}
          onClick={onClose}
          className="fixed inset-0 z-30 bg-page/70 backdrop-blur-sm lg:hidden"
        />
      )}
      <aside
        data-testid="sidebar"
        className={cn(
          "flex w-[236px] flex-none flex-col border-r border-line bg-sidebar px-3 py-4",
          "fixed inset-y-0 left-0 z-40 transition-transform lg:static lg:translate-x-0",
          open ? "translate-x-0" : "-translate-x-full",
        )}
      >
      <div className="flex items-center gap-2.5 px-2 pb-4">
        <div className="grid h-9 w-9 place-items-center rounded-btn bg-accent/15 text-accent">
          <Shield size={20} />
        </div>
        <div className="leading-tight">
          <div className="text-[15px] font-extrabold tracking-wide">DriverGuard</div>
          <div className="text-[11px] text-mut">Fleet Safety</div>
        </div>
        <button
          type="button"
          aria-label={t("Скрыть меню")}
          onClick={onClose}
          className="ml-auto grid h-9 w-9 place-items-center rounded-btn text-mut hover:bg-cardh hover:text-txt lg:hidden"
        >
          <X size={20} />
        </button>
      </div>

      <nav className="flex flex-col gap-0.5" data-tour="nav" aria-label={t("Основная навигация")}>
        {NAV_ITEMS.map(({ href, title, icon: Icon, ...item }) => {
          const active = pathname === href;
          const badge = "badge" in item && item.badge ? summary?.badges.new_events : undefined;
          return (
            <Link
              key={href}
              href={href}
              onClick={onClose}
              className={cn(
                "flex items-center gap-2.5 rounded-btn px-3 py-2.5 text-sm font-semibold text-mut transition-colors hover:bg-cardh hover:text-txt",
                active && "bg-accent/10 text-txt shadow-[inset_2px_0_0] shadow-accent",
              )}
            >
              <Icon size={20} />
              {title}
              {badge ? (
                <span className="num ml-auto rounded-full bg-danger px-1.5 py-px text-[11px] font-bold text-onaccent">
                  {badge}
                </span>
              ) : null}
            </Link>
          );
        })}
      </nav>

      <Link
        href="/settings?tab=devices"
        className="mt-auto block rounded-card border border-line bg-card p-3 transition-colors hover:border-accent"
        data-tour="devices"
        aria-label={t("Устройства: кто онлайн и офлайн")}
      >
        <div className="flex items-center gap-1.5 text-[11px] font-bold uppercase tracking-wide text-mut">
          <Wifi size={14} className="text-ok" />
          {t("Устройств онлайн")}
        </div>
        <div className="num mt-1 text-lg font-extrabold">
          {online ?? "—"}
          <span className="text-sm font-semibold text-mut">/{total ?? "—"}</span>
        </div>
        <div className="mt-2 flex gap-1" aria-hidden>
          {Array.from({ length: total ?? 6 }, (_, i) => (
            <span
              key={i}
              className={cn(
                "h-1.5 flex-1 rounded-full",
                online !== undefined && i < online ? "bg-ok" : "bg-offline/50",
              )}
            />
          ))}
        </div>
        {offline !== undefined && offline > 0 && (
          <div className="num mt-1.5 text-[11px] text-mut">
            {offline} {pluralRu(offline, t("устройство"), t("устройства"), t("устройств"))} {t("офлайн")}
          </div>
        )}
      </Link>
      </aside>
    </>
  );
}
