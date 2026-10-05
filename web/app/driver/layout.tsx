"use client";

/* PWA водителя: защита маршрутов (токен → /driver/login), регистрация service worker,
   отправка отложенных чек-листов при появлении сети (APP-8). Макет 390–430px, одна рука. */

import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { DriverTabs } from "@/components/driver/shell";
import { ToastProvider, useToast } from "@/components/ui/toast";
import { getToken } from "@/lib/api";
import { flushPendingChecklists } from "@/lib/offline-queue";

function OfflineQueueFlusher() {
  const toast = useToast();
  useEffect(() => {
    const flush = () =>
      flushPendingChecklists().then((results) => {
        for (const r of results) toast(r);
      });
    flush();
    window.addEventListener("online", flush);
    return () => window.removeEventListener("online", flush);
  }, [toast]);
  return null;
}

export default function DriverLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const pathname = usePathname();
  const isPublic = pathname === "/driver/login" || pathname === "/driver/offline";
  const [ready, setReady] = useState(false);

  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    if (process.env.NODE_ENV === "production") {
      navigator.serviceWorker.register("/sw.js").catch(() => {
        /* без SW приложение работает как обычный сайт */
      });
    } else {
      // dev: кэш статики мешал бы горячей перезагрузке — снимаем старые регистрации
      navigator.serviceWorker.getRegistrations().then((rs) => rs.forEach((r) => r.unregister()));
    }
  }, []);

  useEffect(() => {
    if (isPublic) {
      setReady(true);
      return;
    }
    if (!getToken()) router.replace("/driver/login");
    else setReady(true);
  }, [isPublic, router]);

  if (!ready) return null;
  return (
    <ToastProvider>
      <div className="mx-auto flex min-h-screen w-full max-w-[430px] flex-col bg-page text-[17px] leading-relaxed">
        <div className={isPublic ? "flex-1" : "flex-1 pb-24"}>{children}</div>
        {!isPublic && (
          <>
            <OfflineQueueFlusher />
            <DriverTabs />
          </>
        )}
      </div>
    </ToastProvider>
  );
}
