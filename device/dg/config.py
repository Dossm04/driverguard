"""Конфигурация устройства: config.yaml + переменные окружения + пороги с backend (DEV-24)."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import yaml


@dataclass
class Thresholds:
    EYE_BS: float = 0.5
    MICROSLEEP_MS: int = 1500
    BLINK_MIN_MS: int = 60
    BLINK_MAX_MS: int = 500
    PERCLOS_WIN_MS: int = 60000
    PERCLOS_WARN: float = 0.20
    PERCLOS_COOLDOWN_MS: int = 30000
    JAW: float = 0.5
    YAWN_MS: int = 1200
    YAWNS_PER_10MIN: int = 3
    NOD_DELTA: float = 0.13
    NOD_MS: int = 2000
    NOFACE_MS: int = 3000
    SABOTAGE_MS: int = 300000
    YAW_DELTA: float = 0.35
    DISTRACTION_MS: int = 8000
    DISTRACTION_CRIT_MS: int = 15000
    DISTRACTION_MIN_KMH: float = 20
    SPEEDING_MS: int = 10000
    speed_limit_highway: float = 90
    speed_limit_city: float = 60
    CALIB_FRAMES: int = 60
    CONFIRM_FRAMES: int = 3
    COOLDOWN_MS: int = 30000
    MIN_CONFIDENCE: float = 0.6
    # детектор нарушений (DEV-8…DEV-10): телефон, курение, ремень
    PHONE_CONF: float = 0.6
    PHONE_MS: int = 2000
    SMOKE_CONF: float = 0.5
    SMOKING_MS: int = 3000
    SMOKE_PUFFS: int = 3  # затяжек за окно → курение (жест рука-ко-рту)
    PUFF_MIN_MS: int = 600
    PUFF_WINDOW_MS: int = 60000
    SEATBELT_CONF: float = 0.5
    SEATBELT_MS: int = 30000
    SEATBELT_MIN_KMH: float = 20

    def update(self, values: dict) -> list[str]:
        """Применяет известные ключи (например, из GET /devices/{id}/config); возвращает изменённые."""
        changed = []
        known = {f.name: f.type for f in fields(self)}
        for key, value in (values or {}).items():
            if key in known and value is not None and getattr(self, key) != value:
                setattr(self, key, type(getattr(self, key))(value))
                changed.append(key)
        return changed


@dataclass
class Config:
    serial: str = "DG-0001"
    secret: str = "device-secret-1"
    api_url: str = "http://localhost:8000/api/v1"
    fw_version: str = "0.2.0"
    model_version: str = "coco-yolov8n"  # версия детектора нарушений (ML-4); на запуске — из ONNX-метаданных
    profile: str = "highway"
    camera_width: int = 640
    camera_height: int = 480
    camera_fps: int = 30
    thresholds: Thresholds = field(default_factory=Thresholds)
    clip_buffer_s: int = 20
    clip_pre_s: int = 10
    clip_post_s: int = 5
    clip_dir: str = "clips"
    db_path: str = "dg.sqlite"
    sync_check_s: int = 30
    sync_batch: int = 100
    backoff_min_s: int = 30
    backoff_max_s: int = 600
    heartbeat_s: int = 600
    volume_day: float = 0.8
    volume_night: float = 0.5
    # детектор нарушений: YOLOv8-ONNX через onnxruntime (device/dg/detector.py)
    detector_enabled: str = "auto"  # auto | on | off
    detector_model: str = "models/yolov8n-coco.onnx"  # относительно device/; DG_YOLO_MODEL переопределяет
    detector_interval_ms: int = 250
    detector_conf: float = 0.35
    detector_near_face: float = 1.8
    detector_threads: int = 2

    @property
    def speed_limit(self) -> float:
        t = self.thresholds
        return t.speed_limit_city if self.profile == "city" else t.speed_limit_highway

    def to_dict(self) -> dict:
        return asdict(self)


def load(path: str | os.PathLike | None = None) -> Config:
    """Читает config.yaml (если есть), затем DG_SERIAL / DG_SECRET / DG_API_URL из окружения."""
    cfg = Config()
    if path is None:
        candidate = Path(__file__).resolve().parent.parent / "config.yaml"
        path = candidate if candidate.is_file() else None
    if path is not None:
        raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
        dev = raw.get("device", {})
        for key in ("serial", "secret", "api_url", "fw_version", "model_version", "profile"):
            if dev.get(key) is not None:
                setattr(cfg, key, dev[key])
        cam = raw.get("camera", {})
        cfg.camera_width = int(cam.get("width", cfg.camera_width))
        cfg.camera_height = int(cam.get("height", cfg.camera_height))
        cfg.camera_fps = int(cam.get("fps", cfg.camera_fps))
        cfg.thresholds.update(raw.get("thresholds", {}))
        clip = raw.get("clip", {})
        cfg.clip_buffer_s = int(clip.get("buffer_s", cfg.clip_buffer_s))
        cfg.clip_pre_s = int(clip.get("pre_s", cfg.clip_pre_s))
        cfg.clip_post_s = int(clip.get("post_s", cfg.clip_post_s))
        cfg.clip_dir = str(clip.get("dir", cfg.clip_dir))
        cfg.db_path = str(raw.get("storage", {}).get("db_path", cfg.db_path))
        sync = raw.get("sync", {})
        cfg.sync_check_s = int(sync.get("check_s", cfg.sync_check_s))
        cfg.sync_batch = int(sync.get("batch", cfg.sync_batch))
        cfg.backoff_min_s = int(sync.get("backoff_min_s", cfg.backoff_min_s))
        cfg.backoff_max_s = int(sync.get("backoff_max_s", cfg.backoff_max_s))
        cfg.heartbeat_s = int(raw.get("heartbeat_s", cfg.heartbeat_s))
        alerts = raw.get("alerts", {})
        cfg.volume_day = float(alerts.get("volume_day", cfg.volume_day))
        cfg.volume_night = float(alerts.get("volume_night", cfg.volume_night))
        det = raw.get("detector", {}) or {}
        enabled = det.get("enabled", cfg.detector_enabled)
        if isinstance(enabled, bool):  # YAML читает on/off как булевы
            enabled = "on" if enabled else "off"
        cfg.detector_enabled = str(enabled).lower()
        cfg.detector_model = str(det.get("model", cfg.detector_model))
        cfg.detector_interval_ms = int(det.get("interval_ms", cfg.detector_interval_ms))
        cfg.detector_conf = float(det.get("conf", cfg.detector_conf))
        cfg.detector_near_face = float(det.get("near_face", cfg.detector_near_face))
        cfg.detector_threads = int(det.get("threads", cfg.detector_threads))
    cfg.serial = os.environ.get("DG_SERIAL", cfg.serial)
    cfg.secret = os.environ.get("DG_SECRET", cfg.secret)
    cfg.api_url = os.environ.get("DG_API_URL", cfg.api_url).rstrip("/")
    return cfg
