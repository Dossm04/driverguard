/* Юнит-тесты машины состояний DMS в браузере (без браузера и backend):
   npm run test:unit. Сценарии повторяют device/tests/test_rules.py. */

import { expect, test } from "@playwright/test";

import { gesturesFromHands } from "../../lib/dms/gestures";
import { RuleEngine, type Detection } from "../../lib/dms/rules";
import { signalsFromResult, type FrameSignals, type Point3 } from "../../lib/dms/signals";

const FRAME = 33;

for (const [kind, over, before] of [
  ["phone", { phoneConf: 0.9 }, 1000],
  ["smoking", { smokeConf: 0.9 }, 2000],
  ["head_nod", { pitch: 0.2 }, 1000],
  ["distraction", { yaw: 0.6 }, 7000],
] as const) {
  test(`потеря лица разрывает непрерывный эпизод ${kind}`, () => {
    const out = run(new RuleEngine(), [
      { ms: before, over },
      { ms: 1500, over: { face: false } },
      { ms: 150, over },
    ]);
    expect(out.filter((d) => d.type === kind)).toHaveLength(0);
  });
}

test("потеря лица снимает устаревшую тревогу телефона", () => {
  const e = new RuleEngine();
  run(e, [{ ms: 2500, over: { phoneConf: 0.9 } }, { ms: 100, over: { face: false } }], 70);
  expect(e.phoneActive).toBe(false);
  expect(e.alertLevel()).toBe(0);
});

function frame(tMs: number, over: Partial<FrameSignals> = {}): FrameSignals {
  return { tMs, face: true, eyeClose: 0.05, ear: 0.3, jaw: 0.05, pitch: 0.02, yaw: 0, speedKmh: 60, phoneConf: 0, smokeConf: 0, ...over };
}

/** Прогоняет движок: калибровка (60 кадров), затем «сцена» из кадров с переопределениями. */
function run(engine: RuleEngine, scene: { ms: number; over?: Partial<FrameSignals> }[], speed = 60) {
  const out: Detection[] = [];
  let t = 0;
  for (let i = 0; i < engine.th.CALIB_FRAMES; i++, t += FRAME) engine.process(frame(t, { speedKmh: speed }));
  for (const step of scene) {
    const end = t + step.ms;
    for (; t < end; t += FRAME) out.push(...engine.process(frame(t, { speedKmh: speed, ...step.over })));
  }
  return out;
}

test("микросон: глаза закрыты ≥1,5 с → critical, моргание — нет", () => {
  const e = new RuleEngine();
  const blink = run(e, [{ ms: 200, over: { eyeClose: 0.9 } }, { ms: 500 }]);
  expect(blink).toHaveLength(0);
  const sleep = run(new RuleEngine(), [{ ms: 2000, over: { eyeClose: 0.9 } }, { ms: 500 }]);
  expect(sleep.map((d) => d.type)).toEqual(["microsleep"]);
  expect(sleep[0].severity).toBe("critical");
  expect(sleep[0].confidence).toBeGreaterThanOrEqual(0.9);
});

test("PERCLOS ≥20% за окно → fatigue с cooldown 30 с", () => {
  const e = new RuleEngine();
  // 40 с: чередуем 1 с закрытых (с открытием, чтобы не срабатывал микросон) и 2 с открытых
  const scene = [];
  for (let i = 0; i < 14; i++) scene.push({ ms: 1000, over: { eyeClose: 0.9 } }, { ms: 2000 });
  const out = run(e, scene);
  const fatigue = out.filter((d) => d.type === "fatigue");
  expect(fatigue.length).toBeGreaterThanOrEqual(1);
  expect(fatigue.length).toBeLessThanOrEqual(2); // cooldown 30 с на ~42 с сцены
  expect(e.perclos).toBeGreaterThanOrEqual(0.2);
});

test("зевота: три зевка за 10 минут → fatigue один раз", () => {
  const e = new RuleEngine();
  const scene = [];
  for (let i = 0; i < 3; i++) scene.push({ ms: 1500, over: { jaw: 0.8 } }, { ms: 1000 });
  const out = run(e, scene);
  expect(out.filter((d) => d.type === "fatigue" && d.note.includes("зевота"))).toHaveLength(1);
  expect(e.counters.yawn).toBe(3);
});

test("клевок головой: наклон > 0,13 дольше 2 с → head_nod", () => {
  const out = run(new RuleEngine(), [{ ms: 2500, over: { pitch: 0.2 } }, { ms: 300 }]);
  expect(out.map((d) => d.type)).toEqual(["head_nod"]);
});

test("отвлечение: поворот головы 8 с → warning, 15 с → critical; стоя — ничего", () => {
  const moving = run(new RuleEngine(), [{ ms: 16_000, over: { yaw: 0.6 } }]);
  expect(moving.map((d) => [d.type, d.severity])).toEqual([
    ["distraction", "warning"],
    ["distraction", "critical"],
  ]);
  const parked = run(new RuleEngine(), [{ ms: 16_000, over: { yaw: 0.6 } }], 0);
  expect(parked).toHaveLength(0);
});

test("нет лица: 3 с → предупреждение, 5 минут в движении → camera_sabotage", () => {
  const e = new RuleEngine();
  run(e, [{ ms: 4000, over: { face: false } }]);
  expect(e.noFaceWarning).toBe(true);
  expect(e.alertLevel()).toBe(1);
  const out = run(new RuleEngine(), [{ ms: 301_000, over: { face: false } }]);
  expect(out.map((d) => d.type)).toEqual(["camera_sabotage"]);
});

test("signalsFromResult: без лица — пусто, с точками — EAR и blendshapes", () => {
  expect(signalsFromResult(0, undefined, undefined).face).toBe(false);
  const lm: Point3[] = Array.from({ length: 478 }, (_, i) => ({ x: i / 478, y: 0.5, z: 0 }));
  const s = signalsFromResult(10, lm, { eyeBlinkLeft: 0.8, eyeBlinkRight: 0.6, jawOpen: 0.2 }, 30);
  expect(s.face).toBe(true);
  expect(s.eyeClose).toBeCloseTo(0.7);
  expect(s.jaw).toBe(0.2);
  expect(s.speedKmh).toBe(30);
});

test("телефон у уха: жест ≥ 2 с в движении → critical; стоя — ничего", () => {
  const e = new RuleEngine();
  const out = run(e, [{ ms: 2500, over: { phoneConf: 0.9 } }]);
  expect(out.map((d) => [d.type, d.severity])).toEqual([["phone", "critical"]]);
  expect(e.alertLevel()).toBe(1); // 60 км/ч — ещё не сирена
  const fast = new RuleEngine();
  run(fast, [{ ms: 2500, over: { phoneConf: 0.9, speedKmh: 90 } }]);
  expect(fast.alertLevel()).toBe(2);
  expect(run(new RuleEngine(), [{ ms: 2500, over: { phoneConf: 0.9 } }], 0)).toHaveLength(0);
});

test("курение: рука у рта 3 с подряд или 3 затяжки за минуту → warning", () => {
  const held = run(new RuleEngine(), [{ ms: 3500, over: { smokeConf: 0.8 } }]);
  expect(held.map((d) => d.type)).toEqual(["smoking"]);
  const e = new RuleEngine();
  const puffs = run(e, [
    { ms: 800, over: { smokeConf: 0.8 } },
    { ms: 5000 },
    { ms: 800, over: { smokeConf: 0.8 } },
    { ms: 5000 },
    { ms: 800, over: { smokeConf: 0.8 } },
  ]);
  expect(puffs.map((d) => [d.type, d.note])).toEqual([["smoking", "повторные затяжки"]]);
  expect(run(new RuleEngine(), [{ ms: 1500, over: { smokeConf: 0.8 } }])).toHaveLength(0);
});

test("gesturesFromHands: ладонь у уха → телефон, палец у рта → сигарета, рука внизу — ничего", () => {
  // лицо: уши в x=0.3 и 0.7 на y=0.5, рот в (0.5, 0.65)
  const face: Point3[] = Array.from({ length: 478 }, () => ({ x: 0.5, y: 0.5, z: 0 }));
  face[234] = { x: 0.3, y: 0.5, z: 0 };
  face[454] = { x: 0.7, y: 0.5, z: 0 };
  face[13] = { x: 0.5, y: 0.64, z: 0 };
  face[14] = { x: 0.5, y: 0.66, z: 0 };
  const hand = (cx: number, cy: number): Point3[] => Array.from({ length: 21 }, () => ({ x: cx, y: cy, z: 0 }));
  expect(gesturesFromHands(face, [hand(0.72, 0.52)]).phoneConf).toBeGreaterThanOrEqual(0.8);
  expect(gesturesFromHands(face, [hand(0.72, 0.52)]).smokeConf).toBe(0);
  const smoke = gesturesFromHands(face, [hand(0.5, 0.66)]);
  expect(smoke.smokeConf).toBeGreaterThanOrEqual(0.8);
  expect(smoke.phoneConf).toBe(0);
  expect(gesturesFromHands(face, [hand(0.5, 0.95)])).toEqual({ phoneConf: 0, smokeConf: 0 });
  expect(gesturesFromHands(undefined, [hand(0.5, 0.66)])).toEqual({ phoneConf: 0, smokeConf: 0 });
});
