"use client";

import dynamic from "next/dynamic";

import { Skeleton } from "@/components/ui/skeleton";

// leaflet работает только в браузере — грузим карту без SSR
const LiveMap = dynamic(
  () => import("@/components/live/live-map").then((m) => m.LiveMapPage),
  { ssr: false, loading: () => <Skeleton className="h-full min-h-[420px] rounded-card" /> },
);

export default function LiveMapRoute() {
  return (
    <div className="h-full min-h-[420px]">
      <LiveMap />
    </div>
  );
}
