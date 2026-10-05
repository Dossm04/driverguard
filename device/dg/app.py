"""Сборка устройства: камера → DMS → правила → события/клипы/алерты; фоновая синхронизация."""

from __future__ import annotations

import logging
import os
import shutil
import signal
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from dg import __version__
from dg.alerts import Alerts
from dg.config import Config
from dg.detector import load_detector
from dg.gps import Odometer, make_gps
from dg.rules import LEVEL1_TYPES, LEVEL2_TYPES, Detection, RuleEngine
from dg.store import Store
from dg.sync import Sync

log = logging.getLogger("dg")
ORANGE = (60, 130, 246)  # BGR акцента панели (--accent) для боксов детектора на HUD


def cpu_temp() -> float | None:
    for p in ("/sys/class/thermal/thermal_zone0/temp",):
        try:
            return round(int(Path(p).read_text().strip()) / 1000, 1)
        except (OSError, ValueError):
            continue
    return None


class Device:
    def __init__(
        self, cfg: Config, gps_mode: str = "none", sync: bool = True, sound: bool = True, speedup: float = 1.0
    ):
        self.cfg = cfg
        self.store = Store(cfg.db_path)
        self.gps = make_gps(gps_mode, speedup)
        self.alerts = Alerts(cfg.volume_day, cfg.volume_night, enabled=sound)
        self.engine = RuleEngine(th=cfg.thresholds, speed_limit=cfg.speed_limit)
        self._apply_saved_thresholds()
        self.engine.speed_limit = self.cfg.speed_limit  # лимит из кэша backend, не из yaml
        self.sync = Sync(cfg, self.store, on_thresholds=self.apply_thresholds, on_reboot=self.reboot) if sync else None
        self.stop_event = threading.Event()
        self.fps = 0.0
        self.reboot_requested = False
        self.odometer = Odometer()
        self.last_fix = self.gps.read()

    def _apply_saved_thresholds(self) -> None:
        saved = self.store.get_config("thresholds")
        if saved:
            changed = self.cfg.thresholds.update(saved)
            if changed:
                log.info("Пороги из локального кэша backend: %s", ", ".join(changed))

    def apply_thresholds(self, values: dict) -> None:
        changed = self.cfg.thresholds.update(values)
        self.engine.speed_limit = self.cfg.speed_limit
        if changed:
            log.info("Применены пороги: %s", ", ".join(changed))

    def reboot(self) -> None:
        self.reboot_requested = True
        self.stop_event.set()

    def update_fix(self) -> None:
        """Читает GPS и накапливает пробег (haversine между валидными фиксами)."""
        self.last_fix = self.gps.read()
        self.odometer.update(self.last_fix)

    def heartbeat(self, extra: dict | None = None) -> None:
        usage = shutil.disk_usage(os.getcwd())
        payload = {
            "fw_version": self.cfg.fw_version,
            "model_version": self.cfg.model_version[:20],  # ML-4: версия детектора на устройстве
            "temp_c": cpu_temp(),
            "fps": round(self.fps, 1),
            "disk_free": round(usage.free / 1e9, 2),
            "gps_fix": bool(self.last_fix.valid),
            "net": "online" if (self.sync and self.sync.online) else "offline",
            "trip_km_delta": self.odometer.take_delta(),  # backend прибавит к активному рейсу
            **(extra or {}),
        }
        self.store.add_heartbeat(payload)

    def record_detection(self, det: Detection, on_clip_uuid=None) -> dict:
        fix = self.last_fix
        event = {
            "uuid": str(uuid.uuid4()),
            "type": det.type,
            "severity": det.severity,
            "ts": datetime.now(UTC).isoformat(),
            "lat": fix.lat,
            "lon": fix.lon,
            "gps_valid": fix.valid,
            "speed_kmh": fix.speed_kmh,
            "speed_source": fix.source,
            "confidence": det.confidence,
            "value": det.value,
            "context": {"note": det.note, "fw": __version__, **(det.extra or {})},
        }
        self.store.add_event(event)
        if on_clip_uuid:
            on_clip_uuid(event["uuid"], det.t_ms)
        if det.type in LEVEL2_TYPES:
            self.alerts.siren_on()
        elif det.type in LEVEL1_TYPES:
            self.alerts.level1(det.type)
        log.warning(
            "СОБЫТИЕ %s (%s, conf %.2f)%s", det.type, det.severity, det.confidence, f" · {det.note}" if det.note else ""
        )
        return event

    def start_background(self) -> None:
        if self.sync:
            self.sync.start()
        signal.signal(signal.SIGTERM, lambda *_: self.stop_event.set())
        signal.signal(signal.SIGINT, lambda *_: self.stop_event.set())

    def shutdown(self) -> None:
        self.alerts.stop()
        if self.sync:
            self.sync.stop()  # ждёт поток, затем последний цикл — без гонки двух cycle()
            self.sync.cycle()
        self.store.close()


def run_camera(
    cfg: Config,
    source: str,
    gps_mode: str,
    sync: bool,
    sound: bool,
    display: bool,
    duration_s: float | None = None,
    detector_mode: str | None = None,
) -> int:
    from dg.capture import Capture
    from dg.dms import FaceAnalyzer, HandAnalyzer
    from dg.gestures import NO_GESTURE, gestures_from_hands
    from dg.recorder import Recorder

    detector = load_detector(cfg, detector_mode)  # DEV-8…DEV-10; None — только DMS
    cfg.model_version = (detector.version if detector else "dms-only")[:20]
    dev = Device(cfg, gps_mode=gps_mode, sync=sync, sound=sound)
    cap = Capture(source, cfg.camera_width, cfg.camera_height, cfg.camera_fps)
    analyzer = FaceAnalyzer()
    # Жесты рук (телефон у уха, сигарета у рта) — без обученного детектора; DG_GESTURES=off отключает
    hands: HandAnalyzer | None = None
    if os.environ.get("DG_GESTURES", "on").lower() not in ("off", "0", "false"):
        try:
            hands = HandAnalyzer()
        except Exception as exc:  # noqa: BLE001 — без модели рук устройство работает по лицу
            log.warning("Hand Landmarker недоступен (%s) — телефон/курение только через детектор", exc)
    gesture = NO_GESTURE
    frame_no = 0
    if detector:
        detector.start()
    recorder = Recorder(
        cfg.clip_dir,
        fps=cap.fps,
        buffer_s=cfg.clip_buffer_s,
        pre_s=cfg.clip_pre_s,
        post_s=cfg.clip_post_s,
        on_clip=dev.store.set_clip_path,
    )
    dev.start_background()
    log.info("DriverGuard device %s · %s · источник %s · backend %s", __version__, cfg.serial, source, cfg.api_url)
    last_hb = time.monotonic()
    fps_times: list[float] = []
    started = time.monotonic()
    dev.heartbeat({"event": "start"})
    try:
        for frame, t_ms in cap.frames():
            if dev.stop_event.is_set() or (duration_s and time.monotonic() - started > duration_s):
                break
            now = time.monotonic()
            fps_times.append(now)
            fps_times[:] = [t for t in fps_times if t > now - 2]
            dev.fps = len(fps_times) / 2
            dev.update_fix()
            signals = analyzer.analyze(frame, t_ms, dev.last_fix.speed_kmh)
            det_sig = None
            if detector:
                detector.submit(frame, t_ms, signals.face_box)
                det_sig = detector.latest(t_ms)
                signals.phone_conf, signals.smoke_conf = det_sig.phone_conf, det_sig.smoke_conf
                signals.seatbelt_off_conf = det_sig.seatbelt_off_conf
                signals.seatbelt_on_conf = det_sig.seatbelt_on_conf
            frame_no += 1
            if hands and frame_no % 3 == 0:  # руки — каждый третий кадр, между замерами держим жест
                try:
                    gesture = gestures_from_hands(analyzer.last_landmarks, hands.detect(frame, t_ms))
                except Exception:  # noqa: BLE001 — кадр пропускаем
                    pass
            if hands:
                signals.phone_conf = max(signals.phone_conf, gesture.phone_conf)
                signals.smoke_conf = max(signals.smoke_conf, gesture.smoke_conf)
            detections = dev.engine.process(signals)
            recorder.push(t_ms, frame)
            for det in detections:
                dev.record_detection(det, on_clip_uuid=recorder.on_event)
            if dev.engine.alert_level < 2:
                dev.alerts.siren_off()
            if display:
                import cv2

                hud = frame.copy()  # плашка — только на экране, в клипы не попадает
                _draw(hud, signals, dev, det_sig)
                cv2.imshow("DriverGuard DMS", hud)
                key = cv2.waitKey(1) & 0xFF
                if key == ord("q"):
                    break
                if key == ord("c"):  # DEV-14: повторная калибровка по команде
                    dev.engine.recalibrate()
                    log.info("Калибровка перезапущена по команде")
            if now - last_hb >= cfg.heartbeat_s:
                dev.heartbeat()
                last_hb = now
    finally:
        recorder.flush()
        cap.release()
        analyzer.close()
        if hands:
            hands.close()
        if detector:
            detector.stop()
            st = detector.stats
            log.info("Детектор: кадров %d, среднее %.0f мс, ошибок %d", st["frames"], st["infer_ms"], st["errors"])
        dev.shutdown()
    return 3 if dev.reboot_requested else 0


def _draw(frame, s, dev: Device, det_sig=None) -> None:
    import cv2

    level = dev.engine.alert_level
    color = (68, 68, 239) if level == 2 else (11, 158, 245) if level == 1 else (94, 197, 34)
    text = "МИКРОСОН" if level == 2 else "ВНИМАНИЕ" if level == 1 else "НОРМА"
    if not dev.engine.calibrated:
        text, color = "КАЛИБРОВКА", (248, 189, 56)
    cv2.rectangle(frame, (0, 0), (frame.shape[1], 28), (20, 20, 20), -1)
    info = (
        f"{text}  eye {s.eye_close:.2f} EAR {s.ear:.2f} jaw {s.jaw:.2f} yaw {s.yaw:+.2f} "
        f"perclos {dev.engine.perclos:.0%} fps {dev.fps:.0f}"
    )
    cv2.putText(frame, info, (6, 19), cv2.FONT_HERSHEY_SIMPLEX, 0.5, color, 1, cv2.LINE_AA)
    if det_sig is not None:
        h, w = frame.shape[:2]
        for b in det_sig.boxes:
            x1, y1, x2, y2 = int(b.x1 * w), int(b.y1 * h), int(b.x2 * w), int(b.y2 * h)
            cv2.rectangle(frame, (x1, y1), (x2, y2), ORANGE, 2)
            label = f"{b.cls} {b.conf:.2f}"
            cv2.putText(frame, label, (x1, max(12, y1 - 4)), cv2.FONT_HERSHEY_SIMPLEX, 0.45, ORANGE, 1, cv2.LINE_AA)
        det_info = f"phone {s.phone_conf:.2f} cig {s.smoke_conf:.2f} belt-off {s.seatbelt_off_conf:.2f}"
        cv2.putText(frame, det_info, (6, h - 8), cv2.FONT_HERSHEY_SIMPLEX, 0.45, ORANGE, 1, cv2.LINE_AA)


def run_simulate(cfg: Config, sync: bool, speedup: float, duration_s: float | None, seed: int | None) -> int:
    from dg.simulate import Simulator

    dev = Device(cfg, gps_mode="sim", sync=sync, sound=False, speedup=speedup)
    sim = Simulator(cfg, dev.store, speedup=speedup, seed=seed)
    sim.gps = dev.gps  # один источник позиции для событий и одометра
    dev.start_background()
    log.info("DriverGuard device %s · %s · СИМУЛЯЦИЯ x%.0f · backend %s", __version__, cfg.serial, speedup, cfg.api_url)
    started = time.monotonic()
    last_hb = started
    dev.heartbeat({"event": "start", "mode": "simulate"})
    tick_s = 1.0
    try:
        while not dev.stop_event.is_set():
            dev.update_fix()
            sim.tick(tick_s * speedup)
            now = time.monotonic()
            if now - last_hb >= min(cfg.heartbeat_s, 60) / speedup:  # км доезжают до PWA во время демо
                dev.fps = 29.0
                dev.heartbeat()
                last_hb = now
            if duration_s and now - started >= duration_s:
                break
            dev.stop_event.wait(tick_s)
    finally:
        dev.shutdown()
    log.info("Симуляция завершена: сгенерировано %d событий", sim.generated)
    return 3 if dev.reboot_requested else 0
