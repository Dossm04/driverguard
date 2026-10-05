"use client";

/* Подписка на WebSocket /ws/live (BE-16): позиции машин + статус соединения.
   При разрыве — переподключение с экспоненциальной паузой (US: индикатор «нет связи»). */

import { useEffect, useRef, useState } from "react";

import { WS_URL, getToken, refreshTokens } from "@/lib/api";

export interface LiveEventInfo {
  type: string;
  value: number | null;
  severity: string;
  ts: string;
}

export interface LiveVehicle {
  vehicle_id: number;
  plate: string;
  driver_id: number | null;
  driver_name: string | null;
  driver_phone: string | null;
  lat: number;
  lon: number;
  speed_kmh: number;
  status: "ok" | "warn" | "danger" | "offline";
  score: number | null;
  last_event: LiveEventInfo | null;
}

export function useLive() {
  const [vehicles, setVehicles] = useState<LiveVehicle[]>([]);
  const [connected, setConnected] = useState(false);
  const attempt = useRef(0);

  useEffect(() => {
    let ws: WebSocket | null = null;
    let timer: ReturnType<typeof setTimeout>;
    let closed = false;

    const connect = () => {
      const token = getToken();
      if (!token || closed) return;
      ws = new WebSocket(`${WS_URL}?token=${encodeURIComponent(token)}`);
      ws.onopen = () => {
        attempt.current = 0;
        setConnected(true);
      };
      ws.onmessage = (e) => {
        try {
          const msg = JSON.parse(e.data as string);
          if (msg.type === "positions") setVehicles(msg.vehicles);
        } catch {
          /* нераспознанный кадр — игнорируем */
        }
      };
      ws.onclose = async (e) => {
        setConnected(false);
        if (closed) return;
        if (e.code === 4401 || e.code === 1006 || !e.wasClean) {
          // access-токен мог истечь (сервер закрывает без кода 4401 при рукопожатии) —
          // обновляем тем же путём, что HTTP-клиент, и переподключаемся с новым
          await refreshTokens();
        }
        const delay = Math.min(1000 * 2 ** attempt.current, 10_000);
        attempt.current += 1;
        timer = setTimeout(connect, delay);
      };
      ws.onerror = () => ws?.close();
    };

    connect();
    return () => {
      closed = true;
      clearTimeout(timer);
      ws?.close();
    };
  }, []);

  return { vehicles, connected };
}
