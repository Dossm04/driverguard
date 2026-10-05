"use client";

/* Live-карта (ШАГ 6, WEB-3): CARTO-подложка по теме, маршрут М-36, маркеры машин
   по статусам (пульсация у критичных), панель списка, попапы с действиями.
   Импортируется только динамически (ssr: false) — leaflet требует window. */

import L from "leaflet";
import { Phone, User, Wifi, WifiOff } from "lucide-react";
import { useTheme } from "next-themes";
import Link from "next/link";
import { useRef } from "react";
import { MapContainer, Marker, Polyline, Popup, TileLayer } from "react-leaflet";

import { formatEventTime } from "@/components/event-modal";
import { Button } from "@/components/ui/button";
import { eventTitle } from "@/lib/events";
import { t, perLang } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";
import { ROUTE, ROUTE_CENTER } from "@/lib/route";
import { useLive, type LiveVehicle } from "@/lib/use-live";
import { useTokenColors } from "@/lib/use-token-colors";
import { cn } from "@/lib/utils";

// Подложка: OpenStreetMap без ключа (CARTO с 2025 года требует API-ключ — водяной знак
// «API KEY REQUIRED»). Тёмная тема — CSS-фильтр .tiles-dark над светлыми тайлами. Свой
// провайдер с ключом — NEXT_PUBLIC_MAP_TILES_LIGHT / NEXT_PUBLIC_MAP_TILES_DARK (шаблон URL).
const OSM_TILES = "https://tile.openstreetmap.org/{z}/{x}/{y}.png";
const TILE_URLS = {
  dark: process.env.NEXT_PUBLIC_MAP_TILES_DARK || OSM_TILES,
  light: process.env.NEXT_PUBLIC_MAP_TILES_LIGHT || OSM_TILES,
};
const DARK_NEEDS_FILTER = !process.env.NEXT_PUBLIC_MAP_TILES_DARK;
const ATTRIBUTION =
  '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a> contributors';

const STATUS_LABELS: Record<LiveVehicle["status"], string> = perLang(() => ({
  ok: t("Норма"),
  warn: t("Усталость"),
  danger: t("Критично"),
  offline: t("Нет связи"),
}));

const MARKER_ICONS = Object.fromEntries(
  (["ok", "warn", "danger", "offline"] as const).map((s) => [
    s,
    L.divIcon({
      className: "",
      html: `<div class="dg-mk dg-mk-${s}">🚚</div>`,
      iconSize: [36, 36],
      iconAnchor: [18, 18],
    }),
  ]),
) as Record<LiveVehicle["status"], L.DivIcon>;

function scoreClass(score: number | null): string {
  if (score == null) return "text-mut";
  if (score >= 85) return "text-ok";
  if (score >= 70) return "text-warn";
  return "text-danger";
}

function StatusDot({ status }: { status: LiveVehicle["status"] }) {
  useLangVersion();
  return (
    <span
      className={cn(
        "h-2 w-2 flex-none rounded-full",
        status === "ok" && "bg-ok",
        status === "warn" && "bg-warn",
        status === "danger" && "bg-danger",
        status === "offline" && "bg-offline",
      )}
    />
  );
}

export function LiveMapPage() {
  useLangVersion();
  const { vehicles, connected } = useLive();
  const { resolvedTheme } = useTheme();
  const mapRef = useRef<L.Map | null>(null);
  const markerRefs = useRef<Record<number, L.Marker | null>>({});
  const colors = useTokenColors(["--accent"]);

  // компонент грузится только на клиенте (ssr:false) — тема известна сразу;
  // до её разрешения тайлы не рендерим, чтобы не тянуть лишний набор
  const tileUrl = resolvedTheme
    ? resolvedTheme === "light"
      ? TILE_URLS.light
      : TILE_URLS.dark
    : null;

  const focusVehicle = (v: LiveVehicle) => {
    mapRef.current?.flyTo([v.lat, v.lon], 10, { duration: 0.8 });
    // попап открываем после начала перелёта, чтобы не дёргать карту
    setTimeout(() => markerRefs.current[v.vehicle_id]?.openPopup(), 350);
  };

  return (
    <div className="relative h-full overflow-hidden rounded-card border border-line">
      <MapContainer
        ref={mapRef}
        center={ROUTE_CENTER}
        zoom={7}
        className="h-full w-full"
        // inline-стиль сильнее leaflet.css (он грузится позже globals и красит фон в #ddd)
        style={{ background: "rgb(var(--bg))" }}
        zoomControl
      >
        {/* key пересоздаёт слой при смене темы (правило 1 CLAUDE.md) */}
        {tileUrl && (
          <TileLayer
            key={tileUrl + resolvedTheme}
            url={tileUrl}
            attribution={ATTRIBUTION}
            maxZoom={19}
            className={resolvedTheme === "dark" && DARK_NEEDS_FILTER ? "tiles-dark" : undefined}
          />
        )}
        {colors && (
          <Polyline
            positions={ROUTE}
            pathOptions={{ color: colors["--accent"], opacity: 0.35, weight: 5 }}
          />
        )}
        {vehicles.map((v) => (
          <Marker
            key={v.vehicle_id}
            position={[v.lat, v.lon]}
            icon={MARKER_ICONS[v.status]}
            ref={(marker) => {
              markerRefs.current[v.vehicle_id] = marker;
            }}
          >
            <Popup>
              <div className="min-w-[210px]">
                <div className="num text-[15px] font-extrabold">{v.plate}</div>
                <div className="mt-1 flex items-center justify-between gap-3 text-sm">
                  <span className="font-semibold">{v.driver_name ?? "—"}</span>
                  <b className={cn("num", scoreClass(v.score))}>Score {v.score ?? "—"}</b>
                </div>
                <div className="num mt-0.5 text-xs text-mut">
                  {t("Скорость:")}{" "}<b className="text-txt">{Math.round(v.speed_kmh)} {t("км/ч")}</b>
                  {v.status === "offline" && t(" · нет связи")}
                </div>
                {v.last_event && (
                  <div
                    className={cn(
                      "mt-1.5 text-xs font-semibold",
                      v.last_event.severity === "critical" ? "text-danger" : "text-warn",
                    )}
                  >
                    ⚠ {eventTitle(v.last_event.type, v.last_event.value)} ·{" "}
                    <span className="num">{formatEventTime(v.last_event.ts)}</span>
                  </div>
                )}
                <div className="mt-2.5 flex gap-2">
                  {/* inline-цвет: .leaflet-container a в leaflet.css сильнее utility-классов */}
                  {v.driver_phone && (
                    <Button size="sm" asChild>
                      <a href={`tel:${v.driver_phone}`} style={{ color: "rgb(var(--onaccent))" }}>
                        <Phone size={14} /> {t("Позвонить")}
                      </a>
                    </Button>
                  )}
                  {v.driver_id && (
                    <Button size="sm" variant="outline" asChild>
                      <Link
                        href={`/drivers/${v.driver_id}`}
                        style={{ color: "rgb(var(--txt))" }}
                      >
                        <User size={14} /> {t("Профиль")}
                      </Link>
                    </Button>
                  )}
                </div>
              </div>
            </Popup>
          </Marker>
        ))}
      </MapContainer>

      {/* Индикатор соединения (правее кнопок зума leaflet) */}
      <div className="absolute left-14 top-3 z-[600]">
        {connected ? (
          <span className="flex items-center gap-1.5 rounded-full border border-line bg-card/90 px-2.5 py-1 text-xs font-bold text-ok backdrop-blur">
            <span className="h-2 w-2 animate-pulse rounded-full bg-ok" />
            LIVE
          </span>
        ) : (
          <span className="flex items-center gap-1.5 rounded-full border border-danger/50 bg-card/90 px-2.5 py-1 text-xs font-bold text-danger backdrop-blur">
            <WifiOff size={13} />
            {t("Нет связи — переподключение…")}
          </span>
        )}
      </div>

      {/* Панель машин */}
      <aside className="absolute z-[600] overflow-y-auto rounded-card border border-line bg-card/90 p-2 backdrop-blur max-lg:inset-x-3 max-lg:bottom-3 max-lg:h-[36%] lg:bottom-3 lg:right-3 lg:top-3 lg:w-[280px]">
        <div className="flex items-center gap-1.5 px-2 pb-1.5 pt-1 text-[11px] font-bold uppercase tracking-wide text-mut">
          <Wifi size={13} className="text-ok" />
          {t("Машины ·")}{" "}{vehicles.length}
        </div>
        {vehicles.length === 0 && (
          <div className="px-2 py-6 text-center text-xs text-mut">
            {connected ? t("Ждём позиции машин…") : t("Нет соединения с сервером")}
          </div>
        )}
        {vehicles.map((v) => (
          <button
            key={v.vehicle_id}
            data-veh-row
            onClick={() => focusVehicle(v)}
            className="flex w-full items-center gap-2.5 rounded-btn px-2 py-2 text-left transition-colors hover:bg-cardh"
          >
            <StatusDot status={v.status} />
            <div className="min-w-0">
              <div className="num truncate text-sm font-bold">{v.plate}</div>
              <div className="truncate text-xs text-mut">{v.driver_name}</div>
            </div>
            <div className="num ml-auto text-right">
              <div className="text-sm font-bold">{Math.round(v.speed_kmh)} {t("км/ч")}</div>
              <div className={cn("text-xs font-extrabold", scoreClass(v.score))}>
                {v.score ?? "—"}
              </div>
            </div>
          </button>
        ))}
      </aside>

      {/* Легенда */}
      <div className="absolute left-3 z-[600] flex flex-wrap gap-x-3 gap-y-1 rounded-card border border-line bg-card/90 px-3 py-2 text-xs font-semibold backdrop-blur max-lg:bottom-[calc(36%+1.25rem)] max-lg:right-3 lg:bottom-3">
        {(Object.keys(STATUS_LABELS) as LiveVehicle["status"][]).map((s) => (
          <span key={s} className="flex items-center gap-1.5">
            <StatusDot status={s} />
            {STATUS_LABELS[s]}
          </span>
        ))}
      </div>
    </div>
  );
}
