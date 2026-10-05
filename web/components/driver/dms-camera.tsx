"use client";

/* DMS в браузере телефона (пакет 6): MediaPipe Face Landmarker → сигналы → те же правила,
   что на устройстве (lib/dms/rules.ts) → события в панель (POST /drivers/me/camera-events),
   heartbeat с позицией телефона раз в 15 с (Live-карта), звук/вибрация на critical.
   Опциональная YOLO-модель работает локально; без неё остаётся явно обозначенный режим жестов. */

import { Camera, CameraOff, Gauge, MapPin, Satellite, Volume2, VolumeX } from "lucide-react";
import { useCallback, useEffect, useRef, useState } from "react";

import { cameraAvailable } from "@/components/driver/camera-capture";
import { BigButton, Card } from "@/components/driver/shell";
import { StatusPill, type PillTone } from "@/components/ui/status-pill";
import { api, saveBlob } from "@/lib/api";
import { CAMERA_QUEUE_CHANGED, cameraOwner, flushCameraEvents, listCameraEvents, saveCameraEvents, type CameraEventBody } from "@/lib/camera-queue";
import { OfflineCamera } from "./offline-camera";
import { NO_GESTURE, gesturesFromHands, type HandGesture } from "@/lib/dms/gestures";
import { RuleEngine, type Detection } from "@/lib/dms/rules";
import { signalsFromResult, type Point3 } from "@/lib/dms/signals";
import { loadPublishedDetector, type ObjectDetector } from "@/lib/dms/object-runtime";
import { objectSignals, OBJECT_LABELS, type ObjectBox } from "@/lib/dms/objects";
import { EVENT_LABELS } from "@/lib/events";
import { t, localeTag, perLang } from "@/lib/i18n";
import { useLangVersion } from "@/lib/i18n/react";
import { cn } from "@/lib/utils";

// Пустые Docker build-args означают стандартный локальный путь, а не корень сайта.
// Оператор ?? не подставляет путь для пустой строки: загрузчик тогда получает 404.
const WASM_URL = process.env.NEXT_PUBLIC_MP_WASM_URL?.trim() || "/mediapipe/wasm";
const MODEL_URL =
  process.env.NEXT_PUBLIC_MP_MODEL_URL?.trim() ||
  "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task";
// Руки (телефон у уха, сигарета у рта — DEV-8/DEV-9): Hand Landmarker, 7,5 МБ, считается на
// каждом третьем кадре; без него страница работает как раньше (только лицо)
const HAND_MODEL_URL =
  process.env.NEXT_PUBLIC_MP_HAND_MODEL_URL?.trim() ||
  "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task";
// Копии моделей со своего сервера (Docker-сборка скачивает их в public/models): работает без
// доступа к Google Storage и в локальной сети без интернета
const LOCAL_MODEL_URL = "/models/face_landmarker.task";
const LOCAL_HAND_MODEL_URL = "/models/hand_landmarker.task";
const HAND_EVERY_N_FRAMES = 3;

async function pickModelUrl(local: string, remote: string, forced?: string): Promise<string> {
  if (forced) return forced;
  try {
    // GET can be served by the offline cache; a HEAD probe cannot.
    const head = await fetch(local, { signal: AbortSignal.timeout(4000) });
    const available = head.ok && Number(head.headers.get("content-length") ?? 0) > 100_000;
    void head.body?.cancel();
    if (available) return local;
  } catch {
    /* локальной копии нет — берём с Google Storage */
  }
  return remote;
}
const TARGET_FRAME_MS = 66; // ~15 к/с — как на устройстве, бережём батарею
const HEARTBEAT_MS = 15_000;
const FLUSH_MS = 2000;
const MODEL_TIMEOUT_MS = 45_000; // WASM ~10 МБ + модель ~4 МБ через туннель/CDN
const SIM_SPEED_KMH = 60;
const MAX_LOG = 12;

type Stage = "idle" | "loading" | "running" | "error";
type SpeedSource = "gps" | "sim";

interface Coords {
  lat: number;
  lon: number;
  speedKmh: number | null;
  valid: boolean;
}

interface LogItem {
  id: string;
  type: string;
  severity: Detection["severity"];
  note: string;
  at: number;
  sent: boolean;
}

// Минимальные типы MediaPipe: сам пакет грузим динамически, чтобы не тянуть его в общий бандл
interface Landmarker {
  detectForVideo(video: HTMLVideoElement, ts: number): {
    faceLandmarks: Point3[][];
    faceBlendshapes: { categories: { categoryName: string; score: number }[] }[];
  };
  close(): void;
}

interface HandLandmarkerLike {
  detectForVideo(video: HTMLVideoElement, ts: number): { landmarks: Point3[][] };
  close(): void;
}

function uuid(): string {
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) return crypto.randomUUID();
  return "xxxxxxxx-xxxx-4xxx-yxxx-xxxxxxxxxxxx".replace(/[xy]/g, (c) => {
    const r = (Math.random() * 16) | 0;
    return (c === "x" ? r : (r & 0x3) | 0x8).toString(16);
  });
}

/** Звуковой сигнал (DEV-15): уровень 2 — сирена (три коротких), 1 — один тон. */
function beep(ctxRef: React.MutableRefObject<AudioContext | null>, level: 1 | 2) {
  try {
    const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
    if (!Ctx) return;
    ctxRef.current ??= new Ctx();
    const ctx = ctxRef.current;
    const pulses = level === 2 ? 3 : 1;
    for (let i = 0; i < pulses; i++) {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "square";
      osc.frequency.value = level === 2 ? 880 : 520;
      gain.gain.value = 0.15;
      osc.connect(gain).connect(ctx.destination);
      const t = ctx.currentTime + i * 0.25;
      osc.start(t);
      osc.stop(t + 0.15);
    }
  } catch {
    /* без звука тоже работает */
  }
  if (navigator.vibrate) navigator.vibrate(level === 2 ? [200, 100, 200, 100, 200] : 150);
}

// Классы перечислены явно: Tailwind не собирает динамические имена вроде text-${tone}
const STATUS: Record<string, { text: string; tone: PillTone; cls: string }> = perLang(() => ({
  calibrating: { text: t("Калибровка — смотрите в камеру"), tone: "accent", cls: "border-accent/40 bg-accent/10 text-accent" },
  ok: { text: t("Слежу за дорогой"), tone: "ok", cls: "border-ok/40 bg-ok/10 text-ok" },
  eyes: { text: t("Глаза закрыты"), tone: "warn", cls: "border-warn/50 bg-warn/15 text-warn" },
  microsleep: { text: t("МИКРОСОН — проснитесь!"), tone: "danger", cls: "border-danger bg-danger/20 text-danger" },
  noface: { text: t("Лицо не видно"), tone: "warn", cls: "border-warn/50 bg-warn/15 text-warn" },
  distraction: { text: t("Взгляд от дороги"), tone: "warn", cls: "border-warn/50 bg-warn/15 text-warn" },
  distraction2: { text: t("ОТВЛЕЧЕНИЕ — смотрите на дорогу"), tone: "danger", cls: "border-danger bg-danger/20 text-danger" },
  phone: { text: t("ТЕЛЕФОН — уберите телефон"), tone: "danger", cls: "border-danger bg-danger/20 text-danger" },
  seatbelt: { text: "Пристегните ремень", tone: "warn", cls: "border-warn/50 bg-warn/15 text-warn" },
  smoking: { text: t("Курение за рулём"), tone: "warn", cls: "border-warn/50 bg-warn/15 text-warn" },
}));

function statusKey(e: RuleEngine): keyof typeof STATUS {
  if (e.noFaceWarning) return "noface";
  if (!e.calibrated) return "calibrating";
  if (e.microsleepActive) return "microsleep";
  if (e.phoneActive) return "phone";
  if (e.distractionLevel >= 2) return "distraction2";
  if (e.smokingActive) return "smoking";
  if (e.seatbeltActive) return "seatbelt";
  if (e.eyesClosed) return "eyes";
  if (e.noFaceWarning) return "noface";
  if (e.distractionLevel >= 1) return "distraction";
  return "ok";
}

export function DmsCamera({ vehiclePlate }: { vehiclePlate: string | null }) {
  useLangVersion();
  const videoRef = useRef<HTMLVideoElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const streamRef = useRef<MediaStream | null>(null);
  const landmarkerRef = useRef<Landmarker | null>(null);
  const objectRef = useRef<ObjectDetector | null>(null);
  const objectJobRef = useRef(false);
  const objectEpochRef = useRef(0);
  const objectResultRef = useRef<{ at: number; boxes: ObjectBox[] }>({ at: 0, boxes: [] });
  const objectLastRef = useRef(0);
  const [objectStatus, setObjectStatus] = useState("Модель предметов не загружена");
  const handRef = useRef<HandLandmarkerLike | null>(null);
  const gestureRef = useRef<HandGesture>(NO_GESTURE);
  const handPointsRef = useRef<Point3[][]>([]);
  const frameCountRef = useRef(0);
  const engineRef = useRef(new RuleEngine());
  const rafRef = useRef(0);
  const lastFrameRef = useRef(0);
  const fpsRef = useRef<{ t: number; n: number; last: number }>({ t: 0, n: 0, last: 0 });
  const audioRef = useRef<AudioContext | null>(null);
  const pendingRef = useRef<{ owner: string; body: CameraEventBody }[]>([]);
  const ownerRef = useRef<string | null>(null);
  const inFlightRef = useRef(false);
  const coordsRef = useRef<Coords | null>(null);
  const speedSourceRef = useRef<SpeedSource>("gps");
  const soundRef = useRef(true);
  const lastLevelRef = useRef(0);

  const [stage, setStage] = useState<Stage>("idle");
  const [error, setError] = useState("");
  const [errorDetail, setErrorDetail] = useState("");
  const [handsReady, setHandsReady] = useState(false);
  const [status, setStatus] = useState<keyof typeof STATUS>("calibrating");
  const [calib, setCalib] = useState(0);
  const [perclos, setPerclos] = useState(0);
  const [fps, setFps] = useState(0);
  const [face, setFace] = useState(false);
  const [coords, setCoords] = useState<Coords | null>(null);
  const [speedSource, setSpeedSource] = useState<SpeedSource>("gps");
  const [sound, setSound] = useState(true);
  const [log, setLog] = useState<LogItem[]>([]);
  const [sent, setSent] = useState(0);
  const [heartbeatOk, setHeartbeatOk] = useState<boolean | null>(null);
  const [supported, setSupported] = useState(true);
  const [queued, setQueued] = useState(0);
  const [rejected, setRejected] = useState(0);
  const [storageError, setStorageError] = useState("");

  useEffect(() => setSupported(cameraAvailable()), []);
  useEffect(() => {
    speedSourceRef.current = speedSource;
  }, [speedSource]);
  useEffect(() => {
    soundRef.current = sound;
  }, [sound]);

  const currentSpeed = useCallback((): number | null => {
    if (speedSourceRef.current === "sim") return SIM_SPEED_KMH;
    return coordsRef.current?.speedKmh ?? null;
  }, []);

  // First commit to IndexedDB, then send. A write failure remains visible and is
  // retried from RAM while this tab stays open; it is never described as saved.
  const flush = useCallback(async () => {
    if (inFlightRef.current) return;
    inFlightRef.current = true;
    try {
      const batch = [...pendingRef.current];
      for (const owner of new Set(batch.map((row) => row.owner))) {
        const rows = batch.filter((row) => row.owner === owner);
        await saveCameraEvents(owner, rows.map((row) => row.body));
        const ids = new Set(rows.map((row) => row.body.uuid));
        pendingRef.current = pendingRef.current.filter((row) => !ids.has(row.body.uuid));
      }
      setStorageError("");
      await flushCameraEvents();
    } catch {
      setStorageError("Не удалось сохранить события на телефон. Не закрывайте вкладку; освободите память устройства и повторите.");
    } finally {
      inFlightRef.current = false;
    }
  }, []);

  useEffect(() => {
    let alive = true;
    const update = (event?: Event) => {
      const detail = (event as CustomEvent<{ owner: string; synced: string[] }> | undefined)?.detail;
      if (detail && detail.owner !== cameraOwner()) return;
      if (detail?.synced.length) {
        const ids = new Set(detail.synced);
        setLog((items) => items.map((item) => ids.has(item.id) ? { ...item, sent: true } : item));
        setSent((n) => n + ids.size);
      }
      void listCameraEvents().then((rows) => {
        if (!alive) return;
        setQueued(rows.filter((row) => !row.rejected).length);
        setRejected(rows.filter((row) => row.rejected).length);
        setLog((items) => {
          const known = new Set(items.map((item) => item.id));
          return [...rows.filter((row) => !known.has(row.body.uuid)).map((row) => ({
            id: row.body.uuid, type: row.body.type, severity: row.body.severity, note: row.body.note,
            at: Date.parse(row.body.ts), sent: false,
          })), ...items].sort((a, b) => b.at - a.at).slice(0, MAX_LOG);
        });
      }).catch(() => { if (alive) setStorageError("Хранилище телефона недоступно. События не будут сохранены после закрытия вкладки."); });
    };
    update();
    window.addEventListener(CAMERA_QUEUE_CHANGED, update);
    window.addEventListener("online", flush);
    const timer = setInterval(() => void flush(), FLUSH_MS);
    return () => { alive = false; clearInterval(timer); window.removeEventListener(CAMERA_QUEUE_CHANGED, update); window.removeEventListener("online", flush); };
  }, [flush]);

  const stop = useCallback(() => {
    cancelAnimationFrame(rafRef.current);
    objectEpochRef.current += 1;
    objectRef.current?.close();
    objectRef.current = null;
    objectJobRef.current = false;
    objectResultRef.current = { at: 0, boxes: [] };
    streamRef.current?.getTracks().forEach((t) => t.stop());
    streamRef.current = null;
    landmarkerRef.current?.close();
    landmarkerRef.current = null;
    handRef.current?.close();
    handRef.current = null;
    gestureRef.current = NO_GESTURE;
    handPointsRef.current = [];
    engineRef.current = new RuleEngine();
    setStage("idle");
    setFace(false);
    setStatus("calibrating");
    setCalib(0);
    void flush();
  }, [flush]);

  const onDetections = useCallback(
    (dets: Detection[]) => {
      if (!dets.length) return;
      const c = coordsRef.current;
      const speed = currentSpeed();
      const bodies = dets.map<CameraEventBody>((d) => ({
        uuid: uuid(),
        type: d.type,
        severity: d.severity,
        confidence: d.confidence,
        ts: new Date(performance.timeOrigin + d.tMs).toISOString(),
        lat: c?.lat ?? null,
        lon: c?.lon ?? null,
        gps_valid: Boolean(c?.valid),
        speed_kmh: speed,
        value: d.value,
        note: `${d.note}${["phone", "smoking", "seatbelt"].includes(d.type) ? (objectRef.current ? ` · модель ${objectRef.current.manifest.run_id}` : " · предположение по жесту, предмет не подтверждён") : ""}${speedSourceRef.current === "sim" ? " · скорость имитируется" : ""}`.slice(0, 512),
        detector: ["phone", "smoking", "seatbelt"].includes(d.type) ? (objectRef.current ? "object_model" : "hand_gesture") : "face_rules",
        ...(["phone", "smoking", "seatbelt"].includes(d.type) && objectRef.current ? {
          model_run_id: objectRef.current.manifest.run_id,
          model_sha256: objectRef.current.manifest.sha256,
        } : {}),
      }));
      const owner = ownerRef.current;
      if (!owner) return;
      pendingRef.current.push(...bodies.map((body) => ({ owner, body })));
      setLog((items) =>
        [
          ...bodies.map<LogItem>((b) => ({
            id: b.uuid,
            type: b.type,
            severity: b.severity,
            note: b.note,
            at: Date.now(),
            sent: false,
          })),
          ...items,
        ].slice(0, MAX_LOG),
      );
      void flush();
    },
    [currentSpeed, flush],
  );

  const loop = useCallback(() => {
    const video = videoRef.current;
    const lm = landmarkerRef.current;
    if (!video || !lm) return;
    const now = performance.now();
    if (now - lastFrameRef.current >= TARGET_FRAME_MS && video.readyState >= 2) {
      lastFrameRef.current = now;
      let landmarks: Point3[] | undefined;
      let blend: Record<string, number> | undefined;
      try {
        const result = lm.detectForVideo(video, now);
        landmarks = result.faceLandmarks[0];
        const cats = result.faceBlendshapes[0]?.categories;
        if (cats) blend = Object.fromEntries(cats.map((c) => [c.categoryName, c.score]));
      } catch {
        /* кадр пропускаем */
      }
      // руки — реже лица (дорого на телефоне); между замерами держим последний жест
      frameCountRef.current += 1;
      const hands = handRef.current;
      if (hands && frameCountRef.current % HAND_EVERY_N_FRAMES === 0) {
        try {
          handPointsRef.current = hands.detectForVideo(video, now).landmarks ?? [];
          gestureRef.current = gesturesFromHands(landmarks, handPointsRef.current);
        } catch {
          gestureRef.current = NO_GESTURE;
          handPointsRef.current = [];
        }
      }
      const detector = objectRef.current;
      if (detector && !objectJobRef.current && now - objectLastRef.current >= 500) {
        objectJobRef.current = true;
        objectLastRef.current = now;
        const epoch = objectEpochRef.current;
        void detector.detect(video).then((boxes) => {
          if (epoch === objectEpochRef.current) objectResultRef.current = { at: now, boxes };
        }).catch(() => {
          if (epoch === objectEpochRef.current) {
            objectResultRef.current = { at: 0, boxes: [] };
            setObjectStatus("Ошибка распознавания предметов; предупреждения по предметам приостановлены");
          }
        }).finally(() => { if (epoch === objectEpochRef.current) objectJobRef.current = false; });
      }
      const engine = engineRef.current;
      const objects = objectSignals(objectResultRef.current.boxes, landmarks, now - objectResultRef.current.at <= 1500);
      const signals = signalsFromResult(now, landmarks, blend, currentSpeed(), detector ? objects : gestureRef.current);
      if (detector) Object.assign(signals, objects);
      const dets = engine.process(signals);
      onDetections(dets);
      const level = engine.alertLevel();
      if (level > lastLevelRef.current && level >= 1 && soundRef.current && engine.calibrated) {
        beep(audioRef, level === 2 ? 2 : 1);
      }
      lastLevelRef.current = level;

      // HUD: точки глаз и рта поверх видео
      const canvas = canvasRef.current;
      if (canvas && video.videoWidth) {
        if (canvas.width !== video.videoWidth) {
          canvas.width = video.videoWidth;
          canvas.height = video.videoHeight;
        }
        const ctx = canvas.getContext("2d");
        if (ctx) {
          ctx.clearRect(0, 0, canvas.width, canvas.height);
          if (detector && now - objectResultRef.current.at <= 1500) {
            ctx.strokeStyle = "#60a5fa"; ctx.lineWidth = 3;
            for (const b of objectResultRef.current.boxes) {
              ctx.strokeRect(b.x1 * canvas.width, b.y1 * canvas.height, (b.x2-b.x1)*canvas.width, (b.y2-b.y1)*canvas.height);
              // Canvas/video are mirrored; invert text alone to preserve readability.
              ctx.save(); ctx.translate(b.x2*canvas.width, b.y1*canvas.height); ctx.scale(-1,1);
              ctx.fillStyle = "#60a5fa"; ctx.font = "14px sans-serif";
              ctx.fillText(`${OBJECT_LABELS[b.cls]} ${Math.round(b.conf*100)}%`, 0, -4); ctx.restore();
            }
          }
          if (landmarks) {
            ctx.fillStyle = level >= 2 ? "rgb(239 68 68)" : level === 1 ? "rgb(245 158 11)" : "rgb(34 197 94)";
            for (const i of [33, 160, 158, 133, 153, 144, 362, 385, 387, 263, 373, 380, 13, 14, 1, 152, 10]) {
              const p = landmarks[i];
              ctx.beginPath();
              ctx.arc(p.x * canvas.width, p.y * canvas.height, 3, 0, Math.PI * 2);
              ctx.fill();
            }
            // точки руки — синим, чтобы было видно, что жест распознан
            ctx.fillStyle = "rgb(59 130 246)";
            for (const hand of handPointsRef.current) {
              for (const p of hand) {
                ctx.beginPath();
                ctx.arc(p.x * canvas.width, p.y * canvas.height, 2.5, 0, Math.PI * 2);
                ctx.fill();
              }
            }
          }
        }
      }
      setFace(signals.face);
      setStatus(statusKey(engine));
      setCalib(engine.calibrationProgress);
      setPerclos(engine.perclos);
      const f = fpsRef.current;
      f.n += 1;
      if (now - f.t >= 1000) {
        setFps(f.n);
        f.last = f.n;
        f.n = 0;
        f.t = now;
      }
    }
    rafRef.current = requestAnimationFrame(loop);
  }, [currentSpeed, onDetections]);

  const start = useCallback(async () => {
    setError("");
    setErrorDetail("");
    setStage("loading");
    // iOS: AudioContext создаётся и «разбуживается» только из жеста пользователя — иначе сирены не будет
    try {
      const Ctx = window.AudioContext ?? (window as unknown as { webkitAudioContext?: typeof AudioContext }).webkitAudioContext;
      if (Ctx) {
        audioRef.current ??= new Ctx();
        void audioRef.current.resume();
      }
    } catch {
      /* без звука тоже работает */
    }
    try {
      ownerRef.current = cameraOwner();
      if (!ownerRef.current) throw new Error("Войдите в учётную запись водителя перед запуском камеры.");
      const stream = await navigator.mediaDevices.getUserMedia({
        video: { facingMode: { ideal: "user" }, width: { ideal: 640 }, height: { ideal: 480 } },
        audio: false,
      });
      streamRef.current = stream;
      const video = videoRef.current;
      if (!video) throw new Error("no video element");
      video.srcObject = stream;
      await video.play();

      // Загрузка WASM и модели с таймаутом: зависший CDN/туннель не оставляет экран «Загружаю…» навсегда
      const withTimeout = <T,>(p: Promise<T>, ms: number, what: string) =>
        Promise.race<T>([
          p,
          new Promise<T>((_, reject) => setTimeout(() => reject(new Error(`timeout:${what}`)), ms)),
        ]);
      const vision = await withTimeout(import("@mediapipe/tasks-vision"), MODEL_TIMEOUT_MS, "js");
      const fileset = await withTimeout(vision.FilesetResolver.forVisionTasks(WASM_URL), MODEL_TIMEOUT_MS, "wasm");
      const modelUrl = await pickModelUrl(LOCAL_MODEL_URL, MODEL_URL, process.env.NEXT_PUBLIC_MP_MODEL_URL);
      const make = (delegate: "GPU" | "CPU") =>
        vision.FaceLandmarker.createFromOptions(fileset, {
          baseOptions: { modelAssetPath: modelUrl, delegate },
          runningMode: "VIDEO",
          numFaces: 1,
          outputFaceBlendshapes: true,
        });
      landmarkerRef.current = (await withTimeout(
        make("GPU").catch(() => make("CPU")),
        MODEL_TIMEOUT_MS,
        "model",
      )) as unknown as Landmarker;
      // Hand Landmarker — не обязателен: при ошибке загрузки работаем только по лицу
      try {
        const handUrl = await pickModelUrl(LOCAL_HAND_MODEL_URL, HAND_MODEL_URL, process.env.NEXT_PUBLIC_MP_HAND_MODEL_URL);
        const makeHands = (delegate: "GPU" | "CPU") =>
          vision.HandLandmarker.createFromOptions(fileset, {
            baseOptions: { modelAssetPath: handUrl, delegate },
            runningMode: "VIDEO",
            numHands: 2,
          });
        handRef.current = (await withTimeout(
          makeHands("GPU").catch(() => makeHands("CPU")),
          MODEL_TIMEOUT_MS,
          "hand-model",
        )) as unknown as HandLandmarkerLike;
        setHandsReady(true);
      } catch {
        handRef.current = null;
        setHandsReady(false);
      }
      setObjectStatus("Проверяю модель предметов…");
      const objectEpoch = ++objectEpochRef.current;
      // Load independently: camera does not wait for the optional 12 MB candidate.
      void loadPublishedDetector().then((detector) => {
        if (objectEpoch !== objectEpochRef.current) { detector?.close(); return; }
        objectRef.current = detector;
        // Do not mix old gesture episodes with object predictions.
        engineRef.current = new RuleEngine();
        setObjectStatus(detector ? `Модель предметов: ${detector.manifest.run_id} · проверка кандидата` : "Режим жестов: предметы не подтверждаются, ремень не оценивается");
      }).catch(() => {
        if (objectEpoch === objectEpochRef.current) setObjectStatus("Модель предметов не загрузилась; доступен только режим жестов");
      });
      // камера могла отвалиться (другое приложение забрало её) — останавливаемся честно
      stream.getVideoTracks()[0]?.addEventListener("ended", () => {
        stop();
        setError(t("Камера отключилась (её занял другой экран или приложение). Нажмите «Включить камеру» ещё раз."));
        setStage("error");
      });
      engineRef.current = new RuleEngine();
      lastLevelRef.current = 0;
      setStage("running");
      rafRef.current = requestAnimationFrame(loop);
    } catch (e: unknown) {
      const name = e instanceof Error ? e.name : "";
      const message = e instanceof Error ? e.message : String(e);
      // техническая причина — отдельной строкой, чтобы её можно было прислать разработчику
      setErrorDetail(`${name || "Error"}: ${message}`.slice(0, 300));
      setError(
        name === "NotAllowedError" || name === "SecurityError"
          ? t("Нет доступа к камере. Разрешите её в настройках браузера и попробуйте снова.")
          : name === "NotFoundError" || name === "OverconstrainedError"
            ? t("Камера не найдена на этом устройстве.")
            : name === "NotReadableError" || name === "AbortError"
              ? t("Камера занята другим приложением или вкладкой. Закройте их и попробуйте снова.")
              : message.startsWith("timeout:")
                ? t("Модель распознавания грузится слишком долго (медленная сеть). Попробуйте снова.")
                : t("Не удалось загрузить модель распознавания лица. Проверьте интернет и попробуйте снова."),
      );
      setStage("error");
      streamRef.current?.getTracks().forEach((t) => t.stop());
      streamRef.current = null;
    }
  }, [loop, stop]);

  // Геолокация телефона: позиция и скорость (м/с → км/ч) для событий, heartbeat и карты
  useEffect(() => {
    if (stage !== "running" || !navigator.geolocation) return;
    const id = navigator.geolocation.watchPosition(
      (pos) => {
        const c: Coords = {
          lat: pos.coords.latitude,
          lon: pos.coords.longitude,
          speedKmh: pos.coords.speed == null || Number.isNaN(pos.coords.speed) ? null : Math.round(pos.coords.speed * 3.6),
          valid: pos.coords.accuracy < 200,
        };
        coordsRef.current = c;
        setCoords(c);
      },
      () => {
        coordsRef.current = null;
        setCoords(null);
      },
      { enableHighAccuracy: true, maximumAge: 5000, timeout: 15_000 },
    );
    return () => navigator.geolocation.clearWatch(id);
  }, [stage]);

  // Heartbeat каждые 15 с + периодическая отправка очереди
  useEffect(() => {
    if (stage !== "running") return;
    const beat = async () => {
      const c = coordsRef.current;
      try {
        await api("/drivers/me/camera-heartbeat", {
          method: "POST",
          body: JSON.stringify({
            lat: c?.lat ?? null,
            lon: c?.lon ?? null,
            gps_valid: Boolean(c?.valid),
            speed_kmh: currentSpeed(),
            fps: fpsRef.current.last || null,
          }),
        });
        setHeartbeatOk(true);
      } catch {
        setHeartbeatOk(false);
      }
    };
    void beat();
    const hb = setInterval(beat, HEARTBEAT_MS);
    return () => {
      clearInterval(hb);
    };
  }, [stage, currentSpeed, flush]);

  // Уход в фон (iOS выключает камеру, кадры замирают): ставим цикл на паузу, при возврате
  // сбрасываем машину состояний, чтобы не получить ложный «Саботаж камеры» за время в фоне
  useEffect(() => {
    if (stage !== "running") return;
    const onVisibility = () => {
      if (document.hidden) {
        cancelAnimationFrame(rafRef.current);
      } else {
        engineRef.current = new RuleEngine();
        lastLevelRef.current = 0;
        void videoRef.current?.play().catch(() => undefined);
        rafRef.current = requestAnimationFrame(loop);
      }
    };
    document.addEventListener("visibilitychange", onVisibility);
    return () => document.removeEventListener("visibilitychange", onVisibility);
  }, [stage, loop]);

  useEffect(() => () => stop(), [stop]);

  const st = STATUS[status];
  const speedShown = speedSource === "sim" ? SIM_SPEED_KMH : (coords?.speedKmh ?? null);

  return (
    <div className="flex flex-col gap-3">
      {!supported && (
        <Card role="alert" className="border-warn/50 bg-warn/10 text-sm">
          {t("Камера в браузере работает только по HTTPS (или localhost). Откройте приложение по https-ссылке — на демо её даёт")}{" "}<b>make tunnel</b>.{" "}
          {t("Если ссылка открыта внутри Telegram/Instagram — откройте её в Safari или Chrome.")}
        </Card>
      )}

      <Card
        data-testid="dms-status"
        data-status={status}
        className={cn("border-2 text-center transition-colors", stage === "running" ? st.cls : "border-line")}
      >
        <div className="text-xs font-bold uppercase tracking-wide text-mut">{t("Состояние")}</div>
        <div className="mt-1 text-xl font-extrabold">
          {stage === "running"
            ? st.text
            : stage === "loading"
              ? t("Загружаю модель распознавания…")
              : stage === "error"
                ? t("Камера не запущена")
                : t("Камера выключена")}
        </div>
        {stage === "running" && !engineRef.current.calibrated && (
          <div className="mx-auto mt-2 h-2 w-40 overflow-hidden rounded-full bg-cardh">
            <div className="h-full bg-accent transition-all" style={{ width: `${Math.round(calib * 100)}%` }} />
          </div>
        )}
        {error && (
          <p role="alert" className="mt-2 text-sm font-semibold text-danger">
            {error}
            {errorDetail && (
              <span className="mt-1 block break-all font-mono text-[11px] text-mut">{errorDetail}</span>
            )}
          </p>
        )}
      </Card>

      <div className="relative overflow-hidden rounded-card border border-line bg-black" style={{ aspectRatio: "4 / 3" }}>
        {/* eslint-disable-next-line jsx-a11y/media-has-caption */}
        <video ref={videoRef} playsInline muted autoPlay className="h-full w-full -scale-x-100 object-cover" />
        <canvas ref={canvasRef} className="pointer-events-none absolute inset-0 h-full w-full -scale-x-100" />
        {stage !== "running" && (
          <div className="absolute inset-0 grid place-items-center text-white/60">
            <CameraOff size={40} />
          </div>
        )}
        {stage === "running" && (
          <div className="absolute inset-x-2 top-2 flex flex-wrap gap-1 text-[11px] font-bold">
            <span className="rounded-full bg-black/60 px-2 py-0.5 text-white">{face ? t("лицо ✓") : t("лица нет")}</span>
            <span className="num rounded-full bg-black/60 px-2 py-0.5 text-white">PERCLOS {Math.round(perclos * 100)}%</span>
            <span className="num rounded-full bg-black/60 px-2 py-0.5 text-white">{fps} {t("к/с")}</span>
          </div>
        )}
      </div>

      {stage === "running" ? (
        <BigButton tone="outline" onClick={stop} data-testid="dms-stop">
          <CameraOff /> {t("Остановить")}
        </BigButton>
      ) : (
        <BigButton onClick={start} disabled={stage === "loading" || !supported} data-testid="dms-start">
          <Camera /> {stage === "error" ? t("Попробовать снова") : t("Включить камеру")}
        </BigButton>
      )}

      <Card className="flex flex-col gap-3 text-sm">
        <div className="flex items-center justify-between gap-2">
          <span className="flex items-center gap-2 font-bold">
            <Gauge size={18} className="text-mut" /> {t("Скорость")}
          </span>
          <div className="flex rounded-btn border border-line p-0.5" role="radiogroup" aria-label={t("Источник скорости")}>
            {(
              [
                ["gps", "GPS"],
                ["sim", t("Имитация {0}", SIM_SPEED_KMH)],
              ] as const
            ).map(([v, label]) => (
              <button
                key={v}
                type="button"
                role="radio"
                aria-checked={speedSource === v}
                onClick={() => setSpeedSource(v)}
                className={cn(
                  "rounded-[10px] px-3 py-1.5 text-xs font-bold text-mut",
                  speedSource === v && "bg-accent/15 text-accent",
                )}
              >
                {label}
              </button>
            ))}
          </div>
        </div>
        <p className="text-xs text-mut">
          {t("Отвлечение считается только в движении (>20 км/ч). Для показа за столом включите имитацию скорости.")}
        </p>
        <div className="grid grid-cols-2 gap-2 text-xs">
          <div className="rounded-btn bg-cardh p-2">
            <div className="flex items-center gap-1 text-mut">
              <Satellite size={14} /> GPS
            </div>
            <div className="num font-bold">
              {coords ? `${coords.lat.toFixed(4)}, ${coords.lon.toFixed(4)}` : t("нет позиции")}
            </div>
          </div>
          <div className="rounded-btn bg-cardh p-2">
            <div className="flex items-center gap-1 text-mut">
              <MapPin size={14} /> {t("На карте")}
            </div>
            <div className="num font-bold">
              {speedShown != null ? t("{0} км/ч · ", speedShown) : ""}
              {vehiclePlate ?? t("машина не закреплена")}
              {heartbeatOk === false && <span className="text-danger"> {t("· нет связи")}</span>}
            </div>
          </div>
        </div>
        <button
          type="button"
          onClick={() => setSound((s) => !s)}
          className="flex min-h-11 items-center gap-2 self-start rounded-btn border border-line px-3 text-xs font-bold text-mut"
          aria-pressed={sound}
        >
          {sound ? <Volume2 size={16} /> : <VolumeX size={16} />}
          {sound ? t("Звук и вибрация включены") : t("Звук выключен")}
        </button>
      </Card>

      <OfflineCamera />

      <Card>
        <div className="mb-2 flex items-center justify-between">
          <b>{t("События с камеры")}</b>
          <span className="num text-xs text-mut">{t("отправлено")}{" "}{sent}</span>
        </div>
        <p className="mb-2 text-xs text-mut" data-testid="camera-queue-count">Сохранено на телефоне, ожидает отправки: {queued}</p>
        {storageError && <p role="alert" className="mb-2 text-xs text-danger">{storageError}</p>}
        {rejected > 0 && <p role="alert" className="mb-2 text-xs text-warn">Сервер отклонил {rejected} событий. Они сохранены для проверки.</p>}
        {(queued > 0 || rejected > 0) && <button type="button" className="mb-2 text-xs text-accent underline" onClick={() => {
          void listCameraEvents().then((rows) => saveBlob(new Blob([JSON.stringify(rows, null, 2)], { type: "application/json" }), "driverguard-events.json"));
        }}>Скачать сохранённые события</button>}
        {log.length === 0 ? (
          <p className="text-sm text-mut">
            {t("Пока пусто. Закройте глаза на 2 секунды — придёт «Засыпание за рулём»; зевните трижды — «Усталость»; опустите голову — «Клевок»; отвернитесь при имитации скорости — «Отвлечение».")}
          </p>
        ) : (
          <ul className="flex flex-col divide-y divide-line" data-testid="dms-log">
            {log.map((item) => (
              <li key={item.id} className="flex items-center gap-2 py-2 text-sm">
                <StatusPill tone={item.severity === "critical" ? "danger" : "warn"}>
                  {item.severity === "critical" ? t("Критично") : t("Внимание")}
                </StatusPill>
                <span className="min-w-0 flex-1 truncate font-semibold">{EVENT_LABELS[item.type] ?? item.type}</span>
                <span className="num text-xs text-mut">
                  {new Date(item.at).toLocaleTimeString(localeTag(), { hour: "2-digit", minute: "2-digit", second: "2-digit" })}
                </span>
                <span className={cn("text-xs font-bold", item.sent ? "text-ok" : "text-mut")}>{item.sent ? "✓" : "…"}</span>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <Card className="text-xs text-mut">
        <p className="mb-2 font-semibold" data-testid="object-model-status">{objectStatus}</p>
        <a href="/driver/verify" className="mb-2 block text-accent underline">Проверить модель на видео и сохранить отчёт</a>
        {t("Распознаётся в браузере: засыпание (глаза закрыты ≥1,5 с), усталость (PERCLOS ≥20 %, зевота ≥3 за 10 мин), клевок головой, отвлечение (взгляд от дороги 8/15 с), саботаж камеры, телефон у уха (≥2 с в движении) и курение (рука с сигаретой у рта 3 с или 3 затяжки за минуту) — по точкам руки. При подключённой модели предметов телефон и сигарета подтверждаются отдельным детектором; ремень оценивается только по явному результату модели. Если ремень не виден, это не означает нарушение. Видео никуда не отправляется — только события.")}
        {handsReady ? ` ${t("Жесты рук включены.")}` : ""}
      </Card>
    </div>
  );
}
