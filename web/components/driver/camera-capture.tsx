"use client";

/* Живая камера для чек-листа (APP-3): getUserMedia → кадр с видео → JPEG ≤ 1600 px.
   Если камеры нет (ноутбук без камеры, http без TLS, отказ в доступе) — родитель открывает
   обычный выбор файла (onFallback). Силуэт ракурса рисуется поверх видоискателя. */

import { Camera, ImageIcon, X } from "lucide-react";
import { useEffect, useRef, useState } from "react";

import { Silhouette } from "@/components/driver/silhouette";
import { t } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";

const MAX_SIDE = 1600;

/** Есть ли в браузере живая камера: нужен HTTPS (или localhost) и mediaDevices. */
export function cameraAvailable(): boolean {
  return (
    typeof navigator !== "undefined" &&
    !!navigator.mediaDevices?.getUserMedia &&
    typeof window !== "undefined" &&
    window.isSecureContext
  );
}

export function CameraCapture({
  slot,
  label,
  hint,
  onCapture,
  onFallback,
  onClose,
}: {
  slot: string;
  label: string;
  hint: string;
  onCapture: (file: File) => void;
  onFallback: () => void;
  onClose: () => void;
}) {
  useLangVersion();
  const videoRef = useRef<HTMLVideoElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const [error, setError] = useState("");
  const [ready, setReady] = useState(false);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    let cancelled = false;
    navigator.mediaDevices
      .getUserMedia({
        video: { facingMode: { ideal: "environment" }, width: { ideal: 1600 }, height: { ideal: 1200 } },
        audio: false,
      })
      .then((stream) => {
        if (cancelled) {
          stream.getTracks().forEach((t) => t.stop());
          return;
        }
        streamRef.current = stream;
        const v = videoRef.current;
        if (v) {
          v.srcObject = stream;
          v.onloadedmetadata = () => setReady(true);
          v.play().catch(() => {});
        }
      })
      .catch((e: unknown) => {
        const name = e instanceof Error ? e.name : "";
        setError(
          name === "NotAllowedError"
            ? t("Нет доступа к камере. Разрешите её в настройках браузера или выберите файл.")
            : t("Камера недоступна на этом устройстве — выберите файл."),
        );
      });
    return () => {
      cancelled = true;
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    };
  }, []);

  const shoot = () => {
    const v = videoRef.current;
    if (!v || !v.videoWidth) return;
    setBusy(true);
    const scale = Math.min(1, MAX_SIDE / Math.max(v.videoWidth, v.videoHeight));
    const canvas = document.createElement("canvas");
    canvas.width = Math.round(v.videoWidth * scale);
    canvas.height = Math.round(v.videoHeight * scale);
    canvas.getContext("2d")?.drawImage(v, 0, 0, canvas.width, canvas.height);
    canvas.toBlob(
      (blob) => {
        setBusy(false);
        if (!blob) {
          setError(t("Не удалось сохранить кадр — попробуйте ещё раз"));
          return;
        }
        onCapture(new File([blob], `${slot}.jpg`, { type: "image/jpeg" }));
      },
      "image/jpeg",
      0.85,
    );
  };

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label={t("Камера: {0}", label)}
      className="fixed inset-0 z-50 flex flex-col bg-black text-white"
      data-testid="camera-capture"
    >
      <div className="flex items-center justify-between p-3">
        <div>
          <div className="text-xs opacity-70">{t("Фото")}</div>
          <div className="text-lg font-extrabold">{label}</div>
        </div>
        <button
          type="button"
          onClick={onClose}
          aria-label={t("Закрыть камеру")}
          className="grid h-11 w-11 place-items-center rounded-full bg-white/10"
        >
          <X />
        </button>
      </div>
      <div className="relative flex-1 overflow-hidden">
        {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
        <video ref={videoRef} playsInline muted autoPlay className="h-full w-full object-cover" />
        <Silhouette slot={slot} className="pointer-events-none absolute left-[10%] top-[15%] h-[70%] w-[80%] text-white/60" />
        <p className="absolute inset-x-0 bottom-3 px-4 text-center text-sm drop-shadow">{hint}</p>
        {error && (
          <div role="alert" className="absolute inset-x-4 top-4 rounded-btn bg-danger px-4 py-3 text-sm font-bold text-white">
            {error}
          </div>
        )}
      </div>
      <div className="grid grid-cols-[1fr_auto_1fr] items-center gap-3 p-4">
        <button
          type="button"
          onClick={onFallback}
          className="flex min-h-12 items-center justify-center gap-2 rounded-btn bg-white/10 text-sm font-bold"
        >
          <ImageIcon size={18} /> {t("Файл")}
        </button>
        <button
          type="button"
          onClick={shoot}
          disabled={busy || !ready || !!error}
          aria-label={t("Сделать снимок")}
          className="grid h-20 w-20 place-items-center rounded-full border-4 border-white bg-white/20 disabled:opacity-40"
        >
          <Camera size={32} />
        </button>
        <span />
      </div>
    </div>
  );
}
