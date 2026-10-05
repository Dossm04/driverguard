"use client";

import { useRouter } from "next/navigation";
import { useEffect, useState } from "react";

import { Sidebar } from "@/components/layout/sidebar";
import { Topbar } from "@/components/layout/topbar";
import { Tour, useTour } from "@/components/tour";
import { ToastProvider } from "@/components/ui/toast";
import { currentUser, getToken } from "@/lib/api";
import { PeriodProvider } from "@/lib/period";

export default function AdminLayout({ children }: { children: React.ReactNode }) {
  const router = useRouter();
  const [ready, setReady] = useState(false);
  const [menuOpen, setMenuOpen] = useState(false);
  const tour = useTour();

  // Защита маршрутов по ролям (WEB-11): без токена — на вход, водителю — в PWA
  useEffect(() => {
    if (!getToken()) {
      router.replace("/login");
      return;
    }
    const role = currentUser()?.role;
    if (role === "driver") {
      router.replace("/driver");
      return;
    }
    if (!role || !["admin", "coordinator", "viewer"].includes(role)) {
      router.replace("/login");
      return;
    }
    setReady(true);
  }, [router]);

  if (!ready) return null;

  return (
    <PeriodProvider>
      <ToastProvider>
        <div className="flex h-screen overflow-hidden">
          <Sidebar open={menuOpen} onClose={() => setMenuOpen(false)} />
          <div className="flex min-w-0 flex-1 flex-col">
            <Topbar onStartTour={tour.start} onMenu={() => setMenuOpen(true)} />
            <main className="flex-1 overflow-y-auto p-3 md:p-5">{children}</main>
          </div>
        </div>
        <Tour open={tour.open} onClose={tour.close} />
      </ToastProvider>
    </PeriodProvider>
  );
}
