/* Сигналы кадра для DMS в браузере: порт device/dg/signals.py (DEV-2, DEV-14).
   Чистая математика по 478 точкам MediaPipe Face Landmarker + blendshapes. */

export interface Point3 {
  x: number;
  y: number;
  z: number;
}

export interface FrameSignals {
  tMs: number;
  face: boolean;
  eyeClose: number; // среднее blendshape eyeBlinkLeft/Right, 0..1
  ear: number; // Eye Aspect Ratio (подтверждение закрытых глаз)
  jaw: number; // blendshape jawOpen, 0..1
  pitch: number; // прокси наклона головы: z(подбородок 152) − z(лоб 10)
  yaw: number; // прокси поворота головы: −1 (влево) … +1 (вправо)
  speedKmh: number | null;
  phoneConf: number; // жест «телефон у уха» (lib/dms/gestures.ts), 0 — нет
  smokeConf: number; // жест «сигарета у рта», 0 — нет
  seatbeltOnConf?: number;
  seatbeltOffConf?: number;
}

const L_EYE = [33, 160, 158, 133, 153, 144] as const;
const R_EYE = [362, 385, 387, 263, 373, 380] as const;
const CHIN = 152;
const FOREHEAD = 10;
const NOSE = 1;
const CHEEK_L = 234;
const CHEEK_R = 454;

const dist = (a: Point3, b: Point3) => Math.hypot(a.x - b.x, a.y - b.y);

/** Классический EAR: (|p2p6| + |p3p5|) / (2·|p1p4|). */
export function ear(lm: Point3[], idx: readonly number[] = L_EYE): number {
  const [p1, p2, p3, p4, p5, p6] = idx.map((i) => lm[i]);
  return (dist(p2, p6) + dist(p3, p5)) / (2 * dist(p1, p4) || 1e-6);
}

export const meanEar = (lm: Point3[]) => (ear(lm, L_EYE) + ear(lm, R_EYE)) / 2;

/** Кивок вниз: подбородок уходит вглубь относительно лба (растёт z-разница). */
export const pitchProxy = (lm: Point3[]) => lm[CHIN].z - lm[FOREHEAD].z;

/** Поворот головы: смещение носа между щеками, −1…+1 (0 — смотрит в камеру). */
export function yawProxy(lm: Point3[]): number {
  const left = dist(lm[NOSE], lm[CHEEK_L]);
  const right = dist(lm[NOSE], lm[CHEEK_R]);
  const width = dist(lm[CHEEK_L], lm[CHEEK_R]) || 1e-6;
  return (left - right) / width;
}

export function emptySignals(tMs: number, speedKmh: number | null = null): FrameSignals {
  return { tMs, face: false, eyeClose: 0, ear: 0, jaw: 0, pitch: 0, yaw: 0, speedKmh, phoneConf: 0, smokeConf: 0 };
}

export function signalsFromResult(
  tMs: number,
  landmarks: Point3[] | undefined,
  blendshapes: Record<string, number> | undefined,
  speedKmh: number | null = null,
  gesture: { phoneConf: number; smokeConf: number } = { phoneConf: 0, smokeConf: 0 },
): FrameSignals {
  if (!landmarks || landmarks.length < 478) return emptySignals(tMs, speedKmh);
  const bs = blendshapes ?? {};
  return {
    tMs,
    face: true,
    eyeClose: ((bs.eyeBlinkLeft ?? 0) + (bs.eyeBlinkRight ?? 0)) / 2,
    ear: meanEar(landmarks),
    jaw: bs.jawOpen ?? 0,
    pitch: pitchProxy(landmarks),
    yaw: yawProxy(landmarks),
    speedKmh,
    phoneConf: gesture.phoneConf,
    smokeConf: gesture.smokeConf,
  };
}
