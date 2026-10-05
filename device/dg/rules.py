"""Машина состояний DMS (DEV-3…DEV-16): из сигналов кадра — события с подтверждением и cooldown.

Логика и пороги повторяют reference/driverguard_demo.html, плюс требования ТЗ:
подтверждение по N кадрам (антидребезг), cooldown на тип, фильтр confidence, уровни алертов.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

from dg.config import Thresholds
from dg.signals import FrameSignals

LEVEL2_TYPES = {"microsleep", "phone", "camera_sabotage"}  # DEV-15: сирена
LEVEL1_TYPES = {"fatigue", "head_nod", "distraction", "speeding", "smoking", "seatbelt"}


@dataclass
class Detection:
    type: str
    severity: str
    confidence: float
    t_ms: int
    value: float | None = None
    note: str = ""
    extra: dict | None = None  # дополнительные поля context события (например, beta)


@dataclass
class RuleEngine:
    th: Thresholds
    speed_limit: float = 90.0
    calibrated: bool = False
    base_pitch: float = 0.0
    base_yaw: float = 0.0
    base_ear: float = 0.0
    _calib: list[tuple[float, float, float]] = field(default_factory=list)
    # глаза / микросон
    _closed_frames: int = 0
    _open_frames: int = 0
    eyes_closed: bool = False
    _closed_since: int = 0
    _closed_conf: list[float] = field(default_factory=list)
    microsleep_active: bool = False
    _blinks: deque = field(default_factory=deque)
    _perclos: deque = field(default_factory=deque)
    perclos: float = 0.0
    # зевота / клевок / лицо / отвлечение / скорость
    _yawn_since: int = 0
    _yawn_counted: bool = False
    _yawns: deque = field(default_factory=deque)
    _nod_since: int = 0
    _nod_counted: bool = False
    _noface_since: int = 0
    _noface_frames: int = 0
    no_face_warning: bool = False
    _sabotage_counted: bool = False
    _yaw_since: int = 0
    _distraction_level: int = 0
    _speeding_since: int = 0
    _phone_since: int = 0
    phone_active: bool = False
    phone_speed_kmh: float = 0.0
    _smoke_since: int = 0
    _puff_counted: bool = False
    _puffs: deque = field(default_factory=deque)
    smoking_active: bool = False
    _belt_off_since: int = 0
    _belt_on_frames: int = 0
    seatbelt_emitted: bool = False
    _last_emit: dict[str, int] = field(default_factory=dict)
    counters: dict[str, int] = field(default_factory=dict)

    # ── служебное ──
    def _emit(self, out: list[Detection], det: Detection, cooldown_ms: int | None = None) -> bool:
        cd = self.th.COOLDOWN_MS if cooldown_ms is None else cooldown_ms
        last = self._last_emit.get(det.type)
        if last is not None and det.t_ms - last < cd:
            return False
        if det.confidence < self.th.MIN_CONFIDENCE:
            return False
        self._last_emit[det.type] = det.t_ms
        self.counters[det.type] = self.counters.get(det.type, 0) + 1
        out.append(det)
        return True

    @property
    def alert_level(self) -> int:
        """0 — норма, 1 — мягкое предупреждение, 2 — сирена (DEV-15)."""
        if self.microsleep_active or (self.phone_active and self.phone_speed_kmh > 60):
            return 2
        if (
            self.no_face_warning
            or self.phone_active
            or self.smoking_active
            or self._distraction_level
            or self._nod_since
            or self.perclos > self.th.PERCLOS_WARN
        ):
            return 1
        return 0

    def recalibrate(self) -> None:
        self.calibrated = False
        self._calib.clear()

    # ── основной шаг ──
    def process(self, s: FrameSignals) -> list[Detection]:
        out: list[Detection] = []
        th = self.th
        now = s.t_ms
        moving = (s.speed_kmh or 0.0) > 5
        self.phone_speed_kmh = s.speed_kmh or 0.0

        if not s.face:
            self._noface_frames += 1
            if self._noface_frames >= th.CONFIRM_FRAMES:
                if not self._noface_since:
                    self._noface_since = now
                if now - self._noface_since >= th.NOFACE_MS:
                    self.no_face_warning = True
                if moving and now - self._noface_since >= th.SABOTAGE_MS and not self._sabotage_counted:
                    self._sabotage_counted = True
                    self._emit(
                        out,
                        Detection(
                            "camera_sabotage",
                            "critical",
                            0.9,
                            now,
                            value=(now - self._noface_since) / 1000,
                            note="лицо не обнаружено при движении",
                        ),
                    )
            if self.microsleep_active:
                self.microsleep_active = False
            self.eyes_closed = False
            self._closed_frames = 0
            # Не засчитываем время без наблюдений в непрерывный эпизод.
            self._open_frames = 0
            self._phone_since = self._smoke_since = self._yawn_since = self._nod_since = self._yaw_since = 0
            self.phone_active = self.smoking_active = False
            self._puff_counted = self._yawn_counted = self._nod_counted = False
            self.distraction_level = 0
            self._belt_off_since = self._belt_on_frames = 0
            self.seatbelt_emitted = False
            self._check_speeding(out, s)
            return out
        if self.no_face_warning and self.calibrated:
            self.recalibrate()  # DEV-14: лицо вернулось после долгого отсутствия — база могла сдвинуться
        self._noface_frames = 0
        self._noface_since = 0
        self.no_face_warning = False
        self._sabotage_counted = False

        # калибровка персональной базы (DEV-14)
        if not self.calibrated:
            self._calib.append((s.pitch, s.yaw, s.ear))
            if len(self._calib) >= th.CALIB_FRAMES:
                n = len(self._calib)
                self.base_pitch = sum(c[0] for c in self._calib) / n
                self.base_yaw = sum(c[1] for c in self._calib) / n
                self.base_ear = sum(c[2] for c in self._calib) / n
                self.calibrated = True
                self._calib.clear()
            self._check_speeding(out, s)
            return out

        # глаза: закрыты по blendshape, EAR — подтверждение (DEV-3)
        closed_now = s.eye_close >= th.EYE_BS or (self.base_ear > 0 and s.ear < self.base_ear * 0.55)
        if closed_now:
            self._closed_frames += 1
            self._open_frames = 0
        else:
            self._open_frames += 1
            self._closed_frames = 0
        if closed_now and not self.eyes_closed and self._closed_frames >= th.CONFIRM_FRAMES:
            self.eyes_closed = True
            self._closed_since = now - (th.CONFIRM_FRAMES - 1) * 33
            self._closed_conf = []
        if self.eyes_closed:
            self._closed_conf.append(s.eye_close)
        if not closed_now and self.eyes_closed and self._open_frames >= th.CONFIRM_FRAMES:
            duration = now - self._closed_since
            self.eyes_closed = False
            if th.BLINK_MIN_MS <= duration <= th.BLINK_MAX_MS:
                self._blinks.append(now)
            if self.microsleep_active:
                self.microsleep_active = False  # водитель отреагировал, сирена выключается
        if self.eyes_closed and not self.microsleep_active and now - self._closed_since >= th.MICROSLEEP_MS:
            self.microsleep_active = True
            conf = min(1.0, 0.6 + 0.4 * (sum(self._closed_conf) / max(len(self._closed_conf), 1)))
            self._emit(
                out,
                Detection(
                    "microsleep",
                    "critical",
                    round(conf, 2),
                    now,
                    value=(now - self._closed_since) / 1000,
                    note="глаза закрыты дольше порога",
                ),
                cooldown_ms=5000,
            )
        while self._blinks and self._blinks[0] < now - 60000:
            self._blinks.popleft()

        # PERCLOS за 60 с (DEV-4)
        self._perclos.append((now, closed_now))
        while self._perclos and self._perclos[0][0] < now - th.PERCLOS_WIN_MS:
            self._perclos.popleft()
        if len(self._perclos) > 30 and now - self._perclos[0][0] > 15000:
            self.perclos = sum(1 for _, c in self._perclos if c) / len(self._perclos)
            if self.perclos >= th.PERCLOS_WARN:
                self._emit(
                    out,
                    Detection(
                        "fatigue",
                        "warning",
                        0.8,
                        now,
                        value=round(self.perclos * 100),
                        note=f"PERCLOS {self.perclos:.0%}",
                    ),
                    cooldown_ms=th.PERCLOS_COOLDOWN_MS,
                )

        # зевота (DEV-5): ≥3 за 10 минут → fatigue
        if s.jaw >= th.JAW:
            if not self._yawn_since:
                self._yawn_since = now
            if now - self._yawn_since >= th.YAWN_MS and not self._yawn_counted:
                self._yawn_counted = True
                self._yawns.append(now)
                self.counters["yawn"] = self.counters.get("yawn", 0) + 1
        else:
            self._yawn_since = 0
            if s.jaw < 0.3:
                self._yawn_counted = False
        while self._yawns and self._yawns[0] < now - 600000:
            self._yawns.popleft()
        if len(self._yawns) >= th.YAWNS_PER_10MIN:
            emitted = self._emit(
                out, Detection("fatigue", "warning", 0.75, now, value=len(self._yawns), note="зевота ≥3 за 10 минут")
            )
            if emitted:
                self._yawns.clear()  # иначе зевоты пропадают в cooldown fatigue по PERCLOS

        # клевок головой (DEV-6)
        nod_dev = s.pitch - self.base_pitch
        if nod_dev > th.NOD_DELTA:
            if not self._nod_since:
                self._nod_since = now
            if now - self._nod_since >= th.NOD_MS and not self._nod_counted:
                self._nod_counted = True
                self._emit(
                    out, Detection("head_nod", "warning", 0.8, now, value=round(nod_dev, 3), note="голова опущена")
                )
        else:
            self._nod_since = 0
            self._nod_counted = False

        # отвлечение (DEV-7): голова повёрнута от дороги при скорости > 20 км/ч
        yaw_dev = abs(s.yaw - self.base_yaw)
        if yaw_dev > th.YAW_DELTA and (s.speed_kmh or 0.0) > th.DISTRACTION_MIN_KMH:
            if not self._yaw_since:
                self._yaw_since = now
            held = now - self._yaw_since
            if held >= th.DISTRACTION_CRIT_MS and self._distraction_level < 2:
                self._distraction_level = 2
                self._emit(
                    out,
                    Detection("distraction", "critical", 0.85, now, value=round(held / 1000), note="взгляд от дороги"),
                    cooldown_ms=0,
                )
            elif held >= th.DISTRACTION_MS and self._distraction_level < 1:
                self._distraction_level = 1
                self._emit(
                    out,
                    Detection("distraction", "warning", 0.8, now, value=round(held / 1000), note="взгляд от дороги"),
                )
        else:
            self._yaw_since = 0
            self._distraction_level = 0

        # телефон (DEV-8/DEV-15) — детектор подключается внешним модулем; подтверждение ≥ 2 с,
        # при > 5 км/ч событие critical, сирена — только на скорости > 60 км/ч
        if s.phone_conf >= th.PHONE_CONF and (s.speed_kmh or 0.0) > 5:
            if not self._phone_since:
                self._phone_since = now
            if now - self._phone_since >= th.PHONE_MS:
                self.phone_active = True
                self._emit(
                    out,
                    Detection(
                        "phone",
                        "critical",
                        round(s.phone_conf, 2),
                        now,
                        value=round(s.speed_kmh or 0.0),
                        note="телефон у лица",
                    ),
                )
        else:
            self._phone_since = 0
            self.phone_active = False

        # курение (DEV-9): сигарета/вейп у лица ≥ 3 с подряд ИЛИ ≥ SMOKE_PUFFS «затяжек»
        # (рука ко рту ≥ PUFF_MIN_MS) за PUFF_WINDOW_MS → smoking (warning)
        if s.smoke_conf >= th.SMOKE_CONF:
            if not self._smoke_since:
                self._smoke_since = now
            held = now - self._smoke_since
            if held >= th.PUFF_MIN_MS and not self._puff_counted:
                self._puff_counted = True
                self._puffs.append(now)
            while self._puffs and self._puffs[0] < now - th.PUFF_WINDOW_MS:
                self._puffs.popleft()
            if held >= th.SMOKING_MS or len(self._puffs) >= th.SMOKE_PUFFS:
                self.smoking_active = True
                by_hold = held >= th.SMOKING_MS
                emitted = self._emit(
                    out,
                    Detection(
                        "smoking",
                        "warning",
                        round(s.smoke_conf, 2),
                        now,
                        value=round(held / 1000) if by_hold else len(self._puffs),
                        note="сигарета у лица" if by_hold else "повторные затяжки",
                    ),
                )
                if emitted:
                    self._puffs.clear()
        else:
            self._smoke_since = 0
            self._puff_counted = False
            self.smoking_active = False

        # ремень (DEV-10, beta): не пристёгнут ≥ 30 с при > 20 км/ч → seatbelt (warning), один раз до пристёгивания
        belt_on = s.seatbelt_on_conf >= th.SEATBELT_CONF and s.seatbelt_on_conf >= s.seatbelt_off_conf
        belt_off = s.seatbelt_off_conf >= th.SEATBELT_CONF and s.seatbelt_off_conf > s.seatbelt_on_conf
        if belt_on:
            self._belt_on_frames += 1
            if self._belt_on_frames >= th.CONFIRM_FRAMES:
                self.seatbelt_emitted = False  # пристегнулся — следующий эпизод снова даст событие
            self._belt_off_since = 0
        elif belt_off and (s.speed_kmh or 0.0) > th.SEATBELT_MIN_KMH:
            self._belt_on_frames = 0
            if not self._belt_off_since:
                self._belt_off_since = now
            held = now - self._belt_off_since
            if held >= th.SEATBELT_MS and not self.seatbelt_emitted:
                self.seatbelt_emitted = True
                self._emit(
                    out,
                    Detection(
                        "seatbelt",
                        "warning",
                        round(s.seatbelt_off_conf, 2),
                        now,
                        value=round(held / 1000),
                        note="ремень не пристёгнут",
                        extra={"beta": True},
                    ),
                )
        else:
            self._belt_on_frames = 0
            self._belt_off_since = 0

        self._check_speeding(out, s)
        return out

    def _check_speeding(self, out: list[Detection], s: FrameSignals) -> None:
        """DEV-11: скорость выше лимита профиля дольше SPEEDING_MS → speeding с величиной превышения."""
        speed = s.speed_kmh
        if speed is not None and speed > self.speed_limit:
            if not self._speeding_since:
                self._speeding_since = s.t_ms
            if s.t_ms - self._speeding_since >= self.th.SPEEDING_MS:
                over = speed - self.speed_limit
                self._emit(
                    out,
                    Detection(
                        "speeding",
                        "critical" if over >= 30 else "warning",
                        0.95,
                        s.t_ms,
                        value=round(over),
                        note=f"лимит {self.speed_limit:.0f}",
                    ),
                    cooldown_ms=60000,
                )
        else:
            self._speeding_since = 0
