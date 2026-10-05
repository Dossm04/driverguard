/* Машина состояний DMS в браузере — порт device/dg/rules.py (DEV-3…DEV-7, DEV-12, DEV-14).
   Те же пороги, подтверждение по времени, cooldown на тип. Телефон и курение получают
   сигналы предметного детектора либо явно обозначенных жестов. Ремень — только YOLO. */

import type { FrameSignals } from "./signals";

export interface Thresholds {
  EYE_BS: number;
  MICROSLEEP_MS: number;
  BLINK_MIN_MS: number;
  BLINK_MAX_MS: number;
  PERCLOS_WIN_MS: number;
  PERCLOS_WARN: number;
  PERCLOS_COOLDOWN_MS: number;
  JAW: number;
  YAWN_MS: number;
  YAWNS_PER_10MIN: number;
  NOD_DELTA: number;
  NOD_MS: number;
  NOFACE_MS: number;
  SABOTAGE_MS: number;
  YAW_DELTA: number;
  DISTRACTION_MS: number;
  DISTRACTION_CRIT_MS: number;
  DISTRACTION_MIN_KMH: number;
  CALIB_FRAMES: number;
  CONFIRM_FRAMES: number;
  COOLDOWN_MS: number;
  MIN_CONFIDENCE: number;
  PHONE_CONF: number;
  PHONE_MS: number;
  SMOKE_CONF: number;
  SMOKING_MS: number;
  SMOKE_PUFFS: number; // «затяжек» (рука ко рту ≥ PUFF_MIN_MS) за PUFF_WINDOW_MS → курение
  PUFF_MIN_MS: number;
  PUFF_WINDOW_MS: number;
}

export const DEFAULT_THRESHOLDS: Thresholds = {
  EYE_BS: 0.5,
  MICROSLEEP_MS: 1500,
  BLINK_MIN_MS: 60,
  BLINK_MAX_MS: 500,
  PERCLOS_WIN_MS: 60_000,
  PERCLOS_WARN: 0.2,
  PERCLOS_COOLDOWN_MS: 30_000,
  JAW: 0.5,
  YAWN_MS: 1200,
  YAWNS_PER_10MIN: 3,
  NOD_DELTA: 0.13,
  NOD_MS: 2000,
  NOFACE_MS: 3000,
  SABOTAGE_MS: 300_000,
  YAW_DELTA: 0.35,
  DISTRACTION_MS: 8000,
  DISTRACTION_CRIT_MS: 15_000,
  DISTRACTION_MIN_KMH: 20,
  CALIB_FRAMES: 60,
  CONFIRM_FRAMES: 3,
  COOLDOWN_MS: 30_000,
  MIN_CONFIDENCE: 0.6,
  PHONE_CONF: 0.6,
  PHONE_MS: 2000,
  SMOKE_CONF: 0.6,
  SMOKING_MS: 3000,
  SMOKE_PUFFS: 3,
  PUFF_MIN_MS: 600,
  PUFF_WINDOW_MS: 60_000,
};

export type DetectionType =
  | "microsleep"
  | "fatigue"
  | "head_nod"
  | "distraction"
  | "camera_sabotage"
  | "phone"
  | "smoking"
  | "seatbelt";

export interface Detection {
  type: DetectionType;
  severity: "critical" | "warning";
  confidence: number;
  tMs: number;
  value: number | null;
  note: string;
}

/** DEV-15: уровень тревоги — 2 сирена (микросон), 1 предупреждение, 0 тихо. */
export type AlertLevel = 0 | 1 | 2;

export class RuleEngine {
  th: Thresholds;
  calibrated = false;
  basePitch = 0;
  baseYaw = 0;
  baseEar = 0;
  eyesClosed = false;
  microsleepActive = false;
  noFaceWarning = false;
  perclos = 0;
  distractionLevel = 0;
  phoneActive = false;
  phoneSpeedKmh = 0;
  smokingActive = false;
  seatbeltActive = false;
  private seatbeltSince = 0;
  private phoneSince = 0;
  private smokeSince = 0;
  private puffCounted = false;
  private puffs: number[] = [];
  counters: Record<string, number> = {};
  private calib: [number, number, number][] = [];
  private closedFrames = 0;
  private openFrames = 0;
  private closedSince = 0;
  private closedConf: number[] = [];
  private blinks: number[] = [];
  private perclosWin: [number, boolean][] = [];
  private yawnSince = 0;
  private yawnCounted = false;
  private yawns: number[] = [];
  private nodSince = 0;
  private nodCounted = false;
  private noFaceSince = 0;
  private noFaceFrames = 0;
  private sabotageCounted = false;
  private yawSince = 0;
  private lastEmit: Partial<Record<DetectionType, number>> = {};

  constructor(th: Partial<Thresholds> = {}) {
    this.th = { ...DEFAULT_THRESHOLDS, ...th };
  }

  get calibrationProgress(): number {
    return this.calibrated ? 1 : this.calib.length / this.th.CALIB_FRAMES;
  }

  alertLevel(): AlertLevel {
    if (this.microsleepActive || this.distractionLevel >= 2 || (this.phoneActive && this.phoneSpeedKmh > 60)) return 2;
    if (this.eyesClosed || this.noFaceWarning || this.distractionLevel >= 1 || this.phoneActive || this.smokingActive || this.seatbeltActive) return 1;
    return 0;
  }

  recalibrate(): void {
    this.calibrated = false;
    this.calib = [];
  }

  private emit(out: Detection[], det: Detection, cooldownMs?: number): boolean {
    const cd = cooldownMs ?? this.th.COOLDOWN_MS;
    const last = this.lastEmit[det.type];
    if (last !== undefined && det.tMs - last < cd) return false;
    if (det.confidence < this.th.MIN_CONFIDENCE) return false;
    this.lastEmit[det.type] = det.tMs;
    this.counters[det.type] = (this.counters[det.type] ?? 0) + 1;
    out.push(det);
    return true;
  }

  process(s: FrameSignals): Detection[] {
    const out: Detection[] = [];
    const th = this.th;
    const now = s.tMs;
    const speed = s.speedKmh ?? 0;
    const moving = speed > 5;

    if (!s.face) {
      this.noFaceFrames += 1;
      if (this.noFaceFrames >= th.CONFIRM_FRAMES) {
        if (!this.noFaceSince) this.noFaceSince = now;
        if (now - this.noFaceSince >= th.NOFACE_MS) this.noFaceWarning = true;
        if (moving && now - this.noFaceSince >= th.SABOTAGE_MS && !this.sabotageCounted) {
          this.sabotageCounted = true;
          this.emit(out, {
            type: "camera_sabotage",
            severity: "critical",
            confidence: 0.9,
            tMs: now,
            value: (now - this.noFaceSince) / 1000,
            note: "лицо не обнаружено при движении",
          });
        }
      }
      this.microsleepActive = false;
      this.eyesClosed = false;
      this.closedFrames = 0;
      // Отсутствие наблюдений разрывает непрерывный эпизод.
      this.openFrames = 0;
      this.phoneSince = this.smokeSince = this.yawnSince = this.nodSince = this.yawSince = 0;
      this.phoneActive = this.smokingActive = this.puffCounted = this.yawnCounted = this.nodCounted = false;
      this.distractionLevel = 0;
      this.seatbeltSince = 0;
      this.seatbeltActive = false;
      return out;
    }
    if (this.noFaceWarning && this.calibrated) this.recalibrate(); // DEV-14
    this.noFaceFrames = 0;
    this.noFaceSince = 0;
    this.noFaceWarning = false;
    this.sabotageCounted = false;

    // калибровка персональной базы (DEV-14)
    if (!this.calibrated) {
      this.calib.push([s.pitch, s.yaw, s.ear]);
      if (this.calib.length >= th.CALIB_FRAMES) {
        const n = this.calib.length;
        this.basePitch = this.calib.reduce((a, c) => a + c[0], 0) / n;
        this.baseYaw = this.calib.reduce((a, c) => a + c[1], 0) / n;
        this.baseEar = this.calib.reduce((a, c) => a + c[2], 0) / n;
        this.calibrated = true;
        this.calib = [];
      }
      return out;
    }

    // глаза: закрыты по blendshape, EAR — подтверждение (DEV-3)
    const closedNow = s.eyeClose >= th.EYE_BS || (this.baseEar > 0 && s.ear < this.baseEar * 0.55);
    if (closedNow) {
      this.closedFrames += 1;
      this.openFrames = 0;
    } else {
      this.openFrames += 1;
      this.closedFrames = 0;
    }
    if (closedNow && !this.eyesClosed && this.closedFrames >= th.CONFIRM_FRAMES) {
      this.eyesClosed = true;
      this.closedSince = now - (th.CONFIRM_FRAMES - 1) * 33;
      this.closedConf = [];
    }
    if (this.eyesClosed) this.closedConf.push(s.eyeClose);
    if (!closedNow && this.eyesClosed && this.openFrames >= th.CONFIRM_FRAMES) {
      const duration = now - this.closedSince;
      this.eyesClosed = false;
      if (duration >= th.BLINK_MIN_MS && duration <= th.BLINK_MAX_MS) this.blinks.push(now);
      this.microsleepActive = false; // водитель отреагировал — сирена выключается
    }
    if (this.eyesClosed && !this.microsleepActive && now - this.closedSince >= th.MICROSLEEP_MS) {
      this.microsleepActive = true;
      const mean = this.closedConf.reduce((a, b) => a + b, 0) / Math.max(this.closedConf.length, 1);
      this.emit(
        out,
        {
          type: "microsleep",
          severity: "critical",
          confidence: Math.round(Math.min(1, 0.6 + 0.4 * mean) * 100) / 100,
          tMs: now,
          value: (now - this.closedSince) / 1000,
          note: "глаза закрыты дольше порога",
        },
        5000,
      );
    }
    while (this.blinks.length && this.blinks[0] < now - 60_000) this.blinks.shift();

    // PERCLOS за 60 с (DEV-4)
    this.perclosWin.push([now, closedNow]);
    while (this.perclosWin.length && this.perclosWin[0][0] < now - th.PERCLOS_WIN_MS) this.perclosWin.shift();
    if (this.perclosWin.length > 30 && now - this.perclosWin[0][0] > 15_000) {
      this.perclos = this.perclosWin.filter((p) => p[1]).length / this.perclosWin.length;
      if (this.perclos >= th.PERCLOS_WARN) {
        this.emit(
          out,
          {
            type: "fatigue",
            severity: "warning",
            confidence: 0.8,
            tMs: now,
            value: Math.round(this.perclos * 100),
            note: `PERCLOS ${Math.round(this.perclos * 100)}%`,
          },
          th.PERCLOS_COOLDOWN_MS,
        );
      }
    }

    // зевота (DEV-5): ≥3 за 10 минут → fatigue
    if (s.jaw >= th.JAW) {
      if (!this.yawnSince) this.yawnSince = now;
      if (now - this.yawnSince >= th.YAWN_MS && !this.yawnCounted) {
        this.yawnCounted = true;
        this.yawns.push(now);
        this.counters.yawn = (this.counters.yawn ?? 0) + 1;
      }
    } else {
      this.yawnSince = 0;
      if (s.jaw < 0.3) this.yawnCounted = false;
    }
    while (this.yawns.length && this.yawns[0] < now - 600_000) this.yawns.shift();
    if (this.yawns.length >= th.YAWNS_PER_10MIN) {
      const emitted = this.emit(out, {
        type: "fatigue",
        severity: "warning",
        confidence: 0.75,
        tMs: now,
        value: this.yawns.length,
        note: "зевота ≥3 за 10 минут",
      });
      if (emitted) this.yawns = [];
    }

    // клевок головой (DEV-6)
    const nodDev = s.pitch - this.basePitch;
    if (nodDev > th.NOD_DELTA) {
      if (!this.nodSince) this.nodSince = now;
      if (now - this.nodSince >= th.NOD_MS && !this.nodCounted) {
        this.nodCounted = true;
        this.emit(out, {
          type: "head_nod",
          severity: "warning",
          confidence: 0.8,
          tMs: now,
          value: Math.round(nodDev * 1000) / 1000,
          note: "голова опущена",
        });
      }
    } else {
      this.nodSince = 0;
      this.nodCounted = false;
    }

    // отвлечение (DEV-7): голова повёрнута от дороги при скорости > 20 км/ч
    const yawDev = Math.abs(s.yaw - this.baseYaw);
    if (yawDev > th.YAW_DELTA && speed > th.DISTRACTION_MIN_KMH) {
      if (!this.yawSince) this.yawSince = now;
      const held = now - this.yawSince;
      if (held >= th.DISTRACTION_CRIT_MS && this.distractionLevel < 2) {
        this.distractionLevel = 2;
        this.emit(
          out,
          {
            type: "distraction",
            severity: "critical",
            confidence: 0.85,
            tMs: now,
            value: Math.round(held / 1000),
            note: "взгляд от дороги",
          },
          0,
        );
      } else if (held >= th.DISTRACTION_MS && this.distractionLevel < 1) {
        this.distractionLevel = 1;
        this.emit(out, {
          type: "distraction",
          severity: "warning",
          confidence: 0.8,
          tMs: now,
          value: Math.round(held / 1000),
          note: "взгляд от дороги",
        });
      }
    } else {
      this.yawSince = 0;
      this.distractionLevel = 0;
    }

    // Explicit no-seatbelt prediction only, sustained 3 s while moving.
    // Neither an absent detection nor conflicting on/off predictions are evidence.
    if ((s.seatbeltOffConf ?? 0) >= 0.65 && (s.seatbeltOnConf ?? 0) < 0.35 && moving) {
      if (!this.seatbeltSince) this.seatbeltSince = now;
      if (now - this.seatbeltSince >= 3000) {
        this.seatbeltActive = true;
        this.emit(out, { type: "seatbelt", severity: "warning", confidence: s.seatbeltOffConf!,
          tMs: now, value: (now - this.seatbeltSince) / 1000, note: "модель: ремень не пристёгнут" });
      }
    } else { this.seatbeltSince = 0; this.seatbeltActive = false; }

    // телефон у уха (DEV-8): ≥ 2 с при движении > 5 км/ч → critical; сирена — > 60 км/ч
    this.phoneSpeedKmh = speed;
    if (s.phoneConf >= th.PHONE_CONF && moving) {
      if (!this.phoneSince) this.phoneSince = now;
      if (now - this.phoneSince >= th.PHONE_MS) {
        this.phoneActive = true;
        this.emit(out, {
          type: "phone",
          severity: "critical",
          confidence: Math.round(s.phoneConf * 100) / 100,
          tMs: now,
          value: Math.round(speed),
          note: "телефон у уха",
        });
      }
    } else {
      this.phoneSince = 0;
      this.phoneActive = false;
    }

    // курение (DEV-9): рука с сигаретой у рта ≥ 3 с подряд ИЛИ ≥ 3 «затяжки» за минуту → warning
    if (s.smokeConf >= th.SMOKE_CONF) {
      if (!this.smokeSince) this.smokeSince = now;
      const held = now - this.smokeSince;
      if (held >= th.PUFF_MIN_MS && !this.puffCounted) {
        this.puffCounted = true;
        this.puffs.push(now);
      }
      while (this.puffs.length && this.puffs[0] < now - th.PUFF_WINDOW_MS) this.puffs.shift();
      if (held >= th.SMOKING_MS || this.puffs.length >= th.SMOKE_PUFFS) {
        this.smokingActive = true;
        const emitted = this.emit(out, {
          type: "smoking",
          severity: "warning",
          confidence: Math.round(s.smokeConf * 100) / 100,
          tMs: now,
          value: held >= th.SMOKING_MS ? Math.round(held / 1000) : this.puffs.length,
          note: held >= th.SMOKING_MS ? "сигарета у рта" : "повторные затяжки",
        });
        if (emitted) this.puffs = [];
      }
    } else {
      this.smokeSince = 0;
      this.puffCounted = false;
      this.smokingActive = false;
    }
    return out;
  }
}
