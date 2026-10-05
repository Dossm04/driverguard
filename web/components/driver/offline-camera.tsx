"use client";

import { useEffect, useState } from "react";
import { Download, WifiOff } from "lucide-react";
import { Card } from "./shell";

type OfflineStatus = { ready: boolean; savedAt?: string; objectModel?: boolean };
async function workerRequest(type: string, progress?: (n: number) => void): Promise<OfflineStatus> {
  if (!("serviceWorker" in navigator) || !window.isSecureContext) throw new Error("Откройте сайт по HTTPS в Safari или Chrome.");
  const registration = await Promise.race([
    navigator.serviceWorker.ready,
    new Promise<never>((_, reject) => setTimeout(() => reject(new Error("Обновите страницу: офлайн-служба ещё не запущена.")), 15_000)),
  ]);
  if (!registration.active) throw new Error("Обновите страницу и повторите.");
  return new Promise((resolve, reject) => {
    const channel = new MessageChannel();
    // Reset after each progress message: slow downloads are not silently abandoned.
    let timer: ReturnType<typeof setTimeout>;
    const arm = () => { clearTimeout(timer); timer = setTimeout(() => { channel.port1.close(); reject(new Error("Подготовка прервалась. Проверьте сеть и повторите.")); }, 120_000); };
    arm();
    channel.port1.onmessage = ({ data }) => {
      if (typeof data.progress === "number") { progress?.(data.progress); arm(); return; }
      clearTimeout(timer); channel.port1.close();
      if (data.error) reject(new Error(data.error)); else resolve(data.done);
    };
    registration.active!.postMessage({ type }, [channel.port2]);
  });
}

export function OfflineCamera() {
  const [status, setStatus] = useState<OfflineStatus>({ ready: false });
  const [progress, setProgress] = useState<number | null>(null);
  const [error, setError] = useState("");
  const [online, setOnline] = useState(true);
  useEffect(() => {
    const check = () => {
      setOnline(navigator.onLine);
      void workerRequest("DG_OFFLINE_STATUS").then(setStatus).catch(() => undefined);
    };
    check();
    window.addEventListener("online", check); window.addEventListener("offline", check);
    document.addEventListener("visibilitychange", check);
    return () => { window.removeEventListener("online", check); window.removeEventListener("offline", check); document.removeEventListener("visibilitychange", check); };
  }, []);
  const prepare = async () => {
    setError(""); setProgress(0);
    try {
      const result = await workerRequest("DG_OFFLINE_PREPARE", setProgress);
      setStatus(result);
      // Best effort: not supported by every iOS version. Readiness never relies on it.
      void navigator.storage?.persist?.().catch(() => false);
    } catch (e) { setError(e instanceof Error ? e.message : "Не удалось сохранить файлы."); }
    finally { setProgress(null); }
  };
  return <Card className="text-sm" data-testid="offline-camera" data-ready={status.ready}>
    <div className="flex items-center gap-2 font-bold"><WifiOff size={18} />
      {status.ready ? "Камера подготовлена для офлайн" : "Подготовка к работе без интернета"}
    </div>
    <p className="mt-2 text-xs text-mut">{status.ready
      ? "Откройте сохранённый экран камеры и нажмите «Включить камеру». Предупреждения работают на телефоне; события отправятся после восстановления связи."
      : "Пока есть интернет, сохраните экран камеры и модели на этот телефон. Дождитесь подтверждения перед отключением сети."}</p>
    {status.ready && <p className="mt-1 text-xs text-mut">Сохранено: {new Date(status.savedAt!).toLocaleDateString("ru-RU")} · {status.objectModel ? "лицо, руки и модель предметов" : "лицо и руки"}</p>}
    {!online && <p className="mt-2 font-semibold text-warn">Сейчас нет сети</p>}
    {error && <p className="mt-2 text-xs text-danger" role="alert">{error}</p>}
    <button type="button" onClick={() => void prepare()} disabled={progress !== null || !online}
      className="mt-3 flex min-h-11 items-center gap-2 rounded-btn border border-line px-3 font-bold disabled:opacity-50" data-testid="offline-prepare">
      <Download size={16} />{progress !== null ? `Сохраняю файлы: ${progress}%` : status.ready ? "Обновить офлайн-файлы" : "Подготовить офлайн"}
    </button>
    <p className="mt-2 text-xs text-mut">Камера работает, пока этот экран открыт. Для связи с панелью нужен интернет. После очистки данных Safari подготовку нужно повторить.</p>
  </Card>;
}
