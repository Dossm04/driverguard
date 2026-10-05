"""Детекция лица и blendshapes (DEV-2): MediaPipe Face Landmarker (tasks API, режим VIDEO).

Модель face_landmarker.task скачивается один раз в ~/.cache/driverguard (или DG_MODEL_PATH).
"""

from __future__ import annotations

import logging
import os
import urllib.request
from pathlib import Path

import numpy as np

from dg.signals import FrameSignals, blendshape_scores, signals_from_result

log = logging.getLogger("dg.dms")
MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/face_landmarker/face_landmarker/float16/1/face_landmarker.task"
)
HAND_MODEL_URL = (
    "https://storage.googleapis.com/mediapipe-models/hand_landmarker/hand_landmarker/float16/1/hand_landmarker.task"
)


def model_path(name: str = "face_landmarker.task", env: str = "DG_MODEL_PATH") -> Path:
    custom = os.environ.get(env)
    if custom:
        return Path(custom)
    return Path.home() / ".cache" / "driverguard" / name


def _ensure(path: Path, url: str, label: str, env: str) -> Path:
    if path.is_file():
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    log.info("Скачиваю модель %s → %s", label, path)
    try:
        urllib.request.urlretrieve(url, path)  # noqa: S310 — фиксированный https-URL Google
    except OSError as exc:
        raise RuntimeError(
            f"Не удалось скачать модель {label} ({exc}). Положите {path.name} в {path} или задайте {env} (см. README)"
        ) from exc
    return path


def ensure_model() -> Path:
    return _ensure(model_path(), MODEL_URL, "Face Landmarker", "DG_MODEL_PATH")


def ensure_hand_model() -> Path:
    path = model_path("hand_landmarker.task", "DG_HAND_MODEL_PATH")
    return _ensure(path, HAND_MODEL_URL, "Hand Landmarker", "DG_HAND_MODEL_PATH")


class HandAnalyzer:
    """Hand Landmarker (до двух рук): кадр BGR + время → список рук по 21 точке. Считается реже
    лица (каждый N-й кадр, см. app.py); при недоступности модели устройство работает без жестов."""

    def __init__(self, path: str | Path | None = None):
        import mediapipe as mp
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        self._mp = mp
        options = vision.HandLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(path or ensure_hand_model())),
            running_mode=vision.RunningMode.VIDEO,
            num_hands=2,
            min_hand_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._landmarker = vision.HandLandmarker.create_from_options(options)
        self._last_t = -1

    def detect(self, frame_bgr: np.ndarray, t_ms: int) -> list[list]:
        if t_ms <= self._last_t:
            t_ms = self._last_t + 1
        self._last_t = t_ms
        rgb = frame_bgr[:, :, ::-1].copy()
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect_for_video(image, t_ms)
        return list(result.hand_landmarks or [])

    def close(self) -> None:
        self._landmarker.close()


class FaceAnalyzer:
    """Оборачивает FaceLandmarker: кадр BGR + время → FrameSignals (одно лицо, ближайшее к центру)."""

    def __init__(self, path: str | Path | None = None):
        import mediapipe as mp  # тяжёлый импорт — только здесь
        from mediapipe.tasks import python as mp_python
        from mediapipe.tasks.python import vision

        self._mp = mp
        options = vision.FaceLandmarkerOptions(
            base_options=mp_python.BaseOptions(model_asset_path=str(path or ensure_model())),
            running_mode=vision.RunningMode.VIDEO,
            num_faces=1,
            output_face_blendshapes=True,
            min_face_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        self._landmarker = vision.FaceLandmarker.create_from_options(options)
        self._last_t = -1
        self.last_landmarks = None

    def analyze(self, frame_bgr: np.ndarray, t_ms: int, speed_kmh: float | None = None) -> FrameSignals:
        if t_ms <= self._last_t:  # MediaPipe требует монотонное время
            t_ms = self._last_t + 1
        self._last_t = t_ms
        rgb = frame_bgr[:, :, ::-1].copy()
        image = self._mp.Image(image_format=self._mp.ImageFormat.SRGB, data=rgb)
        result = self._landmarker.detect_for_video(image, t_ms)
        landmarks = result.face_landmarks[0] if result.face_landmarks else None
        blendshapes = blendshape_scores(result.face_blendshapes[0]) if result.face_blendshapes else None
        self.last_landmarks = landmarks  # для жестов рук (dg.gestures)
        return signals_from_result(t_ms, landmarks, blendshapes, speed_kmh)

    def close(self) -> None:
        self._landmarker.close()
