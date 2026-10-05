"use client";

/* Оболочка PWA водителя (ТЗ 5.4, UX-4): шапка с темой и установкой, нижние вкладки ≥56px.
   Тексты — тон «второй пилот»: без штрафных формулировок. */

import {
  Camera,
  ClipboardCheck,
  Download,
  Gauge,
  GraduationCap,
  LogOut,
  Moon,
  Siren,
  Sun,
  Truck,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useTheme } from "next-themes";
import { useEffect, useState } from "react";

import { logoutTo } from "@/lib/auth";
import { LangSwitch } from "@/components/ui/lang-switch";
import { t, perLang } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";
import { cn } from "@/lib/utils";

const TABS = perLang(() => [
  { href: "/driver", label: t("Смена"), icon: Truck },
  { href: "/driver/checklist", label: t("Чек-лист"), icon: ClipboardCheck },
  { href: "/driver/camera", label: t("Камера"), icon: Camera },
  { href: "/driver/score", label: "Score", icon: Gauge },
  { href: "/driver/sos", label: "SOS", icon: Siren, danger: true },
  { href: "/driver/learn", label: t("Обучение"), icon: GraduationCap },
]);

interface BeforeInstallPromptEvent extends Event {
  prompt: () => Promise<void>;
  userChoice: Promise<{ outcome: "accepted" | "dismissed" }>;
}

/* Событие beforeinstallprompt приходит один раз на страницу — храним его на уровне модуля,
   чтобы кнопка «Установить» не пропадала при переходе между вкладками PWA. */
let deferredPrompt: BeforeInstallPromptEvent | null = null;
const promptListeners = new Set<() => void>();
if (typeof window !== "undefined") {
  window.addEventListener("beforeinstallprompt", (e) => {
    e.preventDefault();
    deferredPrompt = e as BeforeInstallPromptEvent;
    promptListeners.forEach((fn) => fn());
  });
  window.addEventListener("appinstalled", () => {
    deferredPrompt = null;
    promptListeners.forEach((fn) => fn());
  });
}

/** Кнопка «Установить»: появляется, когда браузер готов предложить установку PWA. */
export function useInstallPrompt() {
  const [deferred, setDeferred] = useState<BeforeInstallPromptEvent | null>(deferredPrompt);
  const [installed, setInstalled] = useState(false);
  useEffect(() => {
    const sync = () => setDeferred(deferredPrompt);
    promptListeners.add(sync);
    sync();
    if (window.matchMedia("(display-mode: standalone)").matches) setInstalled(true);
    return () => {
      promptListeners.delete(sync);
    };
  }, []);
  const install = async () => {
    if (!deferred) return;
    await deferred.prompt();
    const choice = await deferred.userChoice;
    if (choice.outcome === "accepted") setInstalled(true);
    deferredPrompt = null;
    setDeferred(null);
  };
  return { canInstall: Boolean(deferred) && !installed, install };
}

export function ThemeToggle() {
  useLangVersion();
  const { resolvedTheme, setTheme } = useTheme();
  const [mounted, setMounted] = useState(false);
  useEffect(() => setMounted(true), []);
  const dark = mounted ? resolvedTheme === "dark" : true;
  return (
    <button
      type="button"
      aria-label={dark ? t("Светлая тема") : t("Тёмная тема")}
      onClick={() => setTheme(dark ? "light" : "dark")}
      className="grid h-14 w-14 place-items-center rounded-btn text-mut transition-colors hover:bg-cardh hover:text-txt"
    >
      {dark ? <Sun size={22} /> : <Moon size={22} />}
    </button>
  );
}

export function DriverHeader({ title }: { title: string }) {
  useLangVersion();
  const { canInstall, install } = useInstallPrompt();
  return (
    <header className="sticky top-0 z-20 flex h-16 items-center gap-2 border-b border-line bg-sidebar/95 px-3 backdrop-blur">
      <div className="grid h-10 w-10 place-items-center rounded-btn bg-accent/15 text-accent">
        <Truck size={22} />
      </div>
      <div className="min-w-0 flex-1">
        <div className="truncate text-[17px] font-extrabold leading-tight">{title}</div>
        <div className="text-xs text-mut">{t("DriverGuard · водитель")}</div>
      </div>
      {canInstall && (
        <button
          type="button"
          onClick={install}
          className="flex h-14 items-center gap-1.5 rounded-btn px-3 text-sm font-bold text-accent hover:bg-accent/10"
        >
          <Download size={18} /> {t("Установить")}
        </button>
      )}
      <LangSwitch />
      <ThemeToggle />
      <button
        type="button"
        aria-label={t("Выйти")}
        onClick={() => logoutTo("/driver/login")}
        className="grid h-14 w-14 place-items-center rounded-btn text-mut hover:bg-cardh hover:text-txt"
      >
        <LogOut size={22} />
      </button>
    </header>
  );
}

export function DriverTabs() {
  useLangVersion();
  const pathname = usePathname();
  return (
    <nav
      aria-label={t("Разделы приложения")}
      className="fixed inset-x-0 bottom-0 z-20 border-t border-line bg-sidebar/95 backdrop-blur"
      style={{ paddingBottom: "env(safe-area-inset-bottom)" }}
    >
      <ul className="mx-auto grid max-w-[430px] grid-cols-6">
        {TABS.map((t) => {
          const active = t.href === "/driver" ? pathname === "/driver" : pathname.startsWith(t.href);
          return (
            <li key={t.href}>
              <Link
                href={t.href}
                aria-current={active ? "page" : undefined}
                className={cn(
                  "flex min-h-16 flex-col items-center justify-center gap-1 text-[11px] font-bold text-mut transition-colors",
                  active && !t.danger && "text-accent",
                  t.danger && "text-danger",
                  active && t.danger && "bg-danger/10",
                )}
              >
                <t.icon size={24} />
                {t.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </nav>
  );
}

/** Большая тач-кнопка (≥56px, текст 18px) — основной элемент управления одной рукой. */
export function BigButton({
  className,
  tone = "accent",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { tone?: "accent" | "ok" | "danger" | "outline" }) {
  return (
    <button
      type="button"
      className={cn(
        "flex min-h-16 w-full items-center justify-center gap-2 rounded-card px-5 text-lg font-extrabold transition-colors focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-accent disabled:opacity-40 [&_svg]:size-6",
        tone === "accent" && "bg-accent text-onaccent hover:bg-accent/90",
        tone === "ok" && "bg-ok text-onaccent hover:bg-ok/90",
        tone === "danger" && "bg-danger text-onaccent hover:bg-danger/90",
        tone === "outline" && "border border-line bg-card text-txt hover:bg-cardh",
        className,
      )}
      {...props}
    />
  );
}

export function Card({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return <div className={cn("rounded-card border border-line bg-card p-4", className)} {...props} />;
}
