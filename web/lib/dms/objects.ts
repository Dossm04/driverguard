// Four-class YOLOv8 output, shared by the live camera and recorded-video checks.
import type { Point3 } from "./signals";

export const OBJECT_CLASSES = ["phone", "cigarette", "seatbelt_on", "seatbelt_off"] as const;
export type ObjectClass = typeof OBJECT_CLASSES[number];
export type ObjectBox = { cls: ObjectClass; conf: number; x1: number; y1: number; x2: number; y2: number };
export const OBJECT_LABELS: Record<ObjectClass, string> = {
  phone: "Телефон", cigarette: "Сигарета", seatbelt_on: "Ремень виден", seatbelt_off: "Без ремня",
};
export interface ObjectManifest {
  schema: 1; classes: string[]; input_size: 640; sha256: string; run_id: string;
  status: "candidate"; model_url?: string;
}
export function validateManifest(value: unknown): ObjectManifest {
  const m = value as ObjectManifest;
  if (!m || m.schema !== 1 || m.input_size !== 640 || m.status !== "candidate" ||
      JSON.stringify(m.classes) !== JSON.stringify(OBJECT_CLASSES) ||
      !/^[a-f0-9]{64}$/.test(m.sha256) || typeof m.run_id !== "string" || !m.run_id) {
    throw new Error("Нужен browser-model.json из проверенного экспорта DriverGuard (4 класса, 640×640).");
  }
  return m;
}
export function letterboxGeometry(width: number, height: number, size = 640) {
  if (!(width > 0 && height > 0)) throw new Error("Пустой кадр");
  const ratio = Math.min(size / width, size / height);
  const w = Math.round(width * ratio), h = Math.round(height * ratio);
  return { ratio, w, h, dx: Math.floor((size - w) / 2), dy: Math.floor((size - h) / 2) };
}
function iou(a: ObjectBox, b: ObjectBox): number {
  const area = (v: ObjectBox) => (v.x2 - v.x1) * (v.y2 - v.y1);
  const intersection = Math.max(0, Math.min(a.x2, b.x2) - Math.max(a.x1, b.x1)) *
    Math.max(0, Math.min(a.y2, b.y2) - Math.max(a.y1, b.y1));
  return intersection / (area(a) + area(b) - intersection + 1e-9);
}
export function decodeObjects(data: ArrayLike<number>, dims: readonly number[], width: number, height: number, threshold = 0.35): ObjectBox[] {
  if (dims.length !== 3 || dims[0] !== 1 || dims[1] !== 8 || !Number.isInteger(dims[2]) || dims[2] < 1 || data.length !== 8 * dims[2]) {
    throw new Error("Несовместимая модель: ожидается выход YOLOv8 [1, 8, N] без встроенного NMS.");
  }
  const { ratio, dx, dy } = letterboxGeometry(width, height);
  const n = dims[2], candidates: ObjectBox[] = [];
  const clamp = (v: number) => Math.max(0, Math.min(1, v));
  for (let k = 0; k < n; k++) {
    let cls = 0, conf = data[4 * n + k];
    for (let c = 1; c < 4; c++) if (data[(4 + c) * n + k] > conf) { cls = c; conf = data[(4 + c) * n + k]; }
    const x = data[k], y = data[n + k], w = data[2 * n + k], h = data[3 * n + k];
    if (![conf, x, y, w, h].every(Number.isFinite) || conf < threshold || conf > 1 || w <= 0 || h <= 0) continue;
    const box = { cls: OBJECT_CLASSES[cls], conf,
      x1: clamp((x - w / 2 - dx) / ratio / width), y1: clamp((y - h / 2 - dy) / ratio / height),
      x2: clamp((x + w / 2 - dx) / ratio / width), y2: clamp((y + h / 2 - dy) / ratio / height) };
    if (box.x2 > box.x1 && box.y2 > box.y1) candidates.push(box);
  }
  const kept: ObjectBox[] = [];
  for (const box of candidates.sort((a, b) => b.conf - a.conf).slice(0, 1000)) {
    if (!kept.some((other) => other.cls === box.cls && iou(box, other) > 0.45)) kept.push(box);
    if (kept.length >= 100) break;
  }
  return kept;
}
export function objectSignals(boxes: ObjectBox[], face: Point3[] | undefined, fresh: boolean) {
  const out = { phoneConf: 0, smokeConf: 0, seatbeltOnConf: 0, seatbeltOffConf: 0 };
  if (!fresh || !face?.length) return out;
  const xs = face.map((p) => p.x), ys = face.map((p) => p.y);
  const x1 = Math.min(...xs), x2 = Math.max(...xs), y1 = Math.min(...ys), y2 = Math.max(...ys);
  const cx = (x1 + x2) / 2, cy = (y1 + y2) / 2 + (y2 - y1) * 0.25;
  for (const b of boxes) {
    const near = Math.abs((b.x1 + b.x2) / 2 - cx) <= (x2 - x1) * 0.9 &&
      Math.abs((b.y1 + b.y2) / 2 - cy) <= (y2 - y1) * 0.9;
    if (b.cls === "phone" && near) out.phoneConf = Math.max(out.phoneConf, b.conf);
    if (b.cls === "cigarette" && near) out.smokeConf = Math.max(out.smokeConf, b.conf);
    // Never infer unfastened from an absent belt. Ambiguous on/off stays unknown.
    if (b.cls === "seatbelt_on") out.seatbeltOnConf = Math.max(out.seatbeltOnConf, b.conf);
    if (b.cls === "seatbelt_off") out.seatbeltOffConf = Math.max(out.seatbeltOffConf, b.conf);
  }
  return out;
}
