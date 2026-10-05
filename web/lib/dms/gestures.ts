/* Жесты по точкам руки (MediaPipe Hand Landmarker) относительно лица: «телефон у уха» и
   «сигарета у рта» без обученного детектора — порт device/dg/gestures.py (DEV-8, DEV-9).
   Чистая математика: расстояния нормируются на ширину лица, поэтому не зависят от дистанции
   до камеры. Ремень (DEV-10) жестами не определить — только YOLO-модель из ml/. */

import type { Point3 } from "./signals";

export interface HandGesture {
  phoneConf: number; // ладонь у уха → телефон у лица, 0 или 0.55…0.95
  smokeConf: number; // кончик пальца у рта → сигарета/вейп, 0 или 0.55…0.95
}

const EAR_L = 234;
const EAR_R = 454;
const LIP_TOP = 13;
const LIP_BOTTOM = 14;
const PALM = [0, 5, 9, 13, 17] as const; // запястье и основания пальцев
const TIPS = [4, 8, 12] as const; // большой, указательный, средний
export const PHONE_REACH = 0.8; // доля ширины лица, ближе которой ладонь считается «у уха»
export const SMOKE_REACH = 0.3; // доля ширины лица от кончика пальца до рта

const dist = (a: Point3, b: Point3) => Math.hypot(a.x - b.x, a.y - b.y);
const clamp01 = (v: number) => Math.min(1, Math.max(0, v));
const conf = (closeness: number) => (closeness > 0 ? Math.round((0.55 + 0.4 * closeness) * 100) / 100 : 0);

function centroid(points: Point3[]): Point3 {
  const n = points.length || 1;
  return {
    x: points.reduce((a, p) => a + p.x, 0) / n,
    y: points.reduce((a, p) => a + p.y, 0) / n,
    z: points.reduce((a, p) => a + p.z, 0) / n,
  };
}

export const NO_GESTURE: HandGesture = { phoneConf: 0, smokeConf: 0 };

/** face — 478 точек лица, hands — по 21 точке на руку (те же нормированные координаты кадра). */
export function gesturesFromHands(face: Point3[] | undefined, hands: Point3[][]): HandGesture {
  if (!face || face.length < 478 || !hands.length) return NO_GESTURE;
  const width = dist(face[EAR_L], face[EAR_R]) || 1e-6;
  const mouth = centroid([face[LIP_TOP], face[LIP_BOTTOM]]);
  const ears = [face[EAR_L], face[EAR_R]];
  let phone = 0;
  let smoke = 0;
  for (const hand of hands) {
    if (hand.length < 21) continue;
    const palm = centroid(PALM.map((i) => hand[i]));
    for (const ear of ears) {
      const d = dist(palm, ear) / width;
      const dy = Math.abs(palm.y - ear.y) / width;
      if (d < PHONE_REACH && dy < 0.6) phone = Math.max(phone, clamp01(1 - d / PHONE_REACH));
    }
    const tip = Math.min(...TIPS.map((i) => dist(hand[i], mouth))) / width;
    if (tip < SMOKE_REACH) smoke = Math.max(smoke, clamp01(1 - tip / SMOKE_REACH));
  }
  // одна рука не может быть и у уха, и у рта: побеждает более уверенный жест
  if (phone > 0 && smoke > 0) {
    if (smoke >= phone) phone = 0;
    else smoke = 0;
  }
  return { phoneConf: conf(phone), smokeConf: conf(smoke) };
}
