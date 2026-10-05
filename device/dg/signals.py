"""Сигналы кадра: EAR, прокси наклона/поворота головы по 478 точкам MediaPipe (DEV-2, DEV-14).

Чистая математика без зависимости от MediaPipe — та же, что в reference/driverguard_demo.html.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Protocol


class Point(Protocol):
    x: float
    y: float
    z: float


@dataclass
class FrameSignals:
    """Что машина состояний получает на каждый кадр."""

    t_ms: int
    face: bool
    eye_close: float = 0.0  # среднее blendshape eyeBlinkLeft/Right, 0..1
    ear: float = 0.0  # Eye Aspect Ratio (справочно/резерв)
    jaw: float = 0.0  # blendshape jawOpen, 0..1
    pitch: float = 0.0  # прокси наклона головы: z(подбородок 152) − z(лоб 10)
    yaw: float = 0.0  # прокси поворота головы: −1 (влево) … +1 (вправо)
    speed_kmh: float | None = None
    phone_conf: float = 0.0  # детектор (dg.detector): телефон у лица
    smoke_conf: float = 0.0  # сигарета/вейп у лица
    seatbelt_off_conf: float = 0.0  # ремень не пристёгнут (beta)
    seatbelt_on_conf: float = 0.0  # ремень виден пристёгнутым
    face_box: tuple[float, float, float, float] | None = None  # бокс лица 0..1 — зона «у лица» для детектора


L_EYE = (33, 160, 158, 133, 153, 144)
R_EYE = (362, 385, 387, 263, 373, 380)
CHIN, FOREHEAD, NOSE, CHEEK_L, CHEEK_R = 152, 10, 1, 234, 454


def _dist(a: Point, b: Point) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def ear(lm: list, idx: tuple[int, ...] = L_EYE) -> float:
    """Классический EAR: (|p2p6| + |p3p5|) / (2·|p1p4|)."""
    p1, p2, p3, p4, p5, p6 = (lm[i] for i in idx)
    return (_dist(p2, p6) + _dist(p3, p5)) / (2 * _dist(p1, p4) or 1e-6)


def mean_ear(lm: list) -> float:
    return (ear(lm, L_EYE) + ear(lm, R_EYE)) / 2


def pitch_proxy(lm: list) -> float:
    """Кивок вниз: подбородок уходит вглубь относительно лба (растёт z-разница)."""
    return lm[CHIN].z - lm[FOREHEAD].z


def yaw_proxy(lm: list) -> float:
    """Поворот головы: смещение носа между щеками, −1…+1 (0 — смотрит в камеру)."""
    left, right = _dist(lm[NOSE], lm[CHEEK_L]), _dist(lm[NOSE], lm[CHEEK_R])
    width = _dist(lm[CHEEK_L], lm[CHEEK_R]) or 1e-6
    return (left - right) / width


def blendshape_scores(categories) -> dict[str, float]:
    return {c.category_name: float(c.score) for c in categories}


def signals_from_result(
    t_ms: int, landmarks: list | None, blendshapes: dict[str, float] | None, speed_kmh: float | None = None
) -> FrameSignals:
    if not landmarks:
        return FrameSignals(t_ms=t_ms, face=False, speed_kmh=speed_kmh)
    bs = blendshapes or {}
    xs = [p.x for p in landmarks]
    ys = [p.y for p in landmarks]
    face_box = (max(0.0, min(xs)), max(0.0, min(ys)), min(1.0, max(xs)), min(1.0, max(ys)))
    return FrameSignals(
        t_ms=t_ms,
        face=True,
        eye_close=(bs.get("eyeBlinkLeft", 0.0) + bs.get("eyeBlinkRight", 0.0)) / 2,
        ear=mean_ear(landmarks),
        jaw=bs.get("jawOpen", 0.0),
        pitch=pitch_proxy(landmarks),
        yaw=yaw_proxy(landmarks),
        speed_kmh=speed_kmh,
        face_box=face_box,
    )
