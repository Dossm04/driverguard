"""Жесты по точкам руки (MediaPipe Hand Landmarker) относительно лица: «телефон у уха» и
«сигарета у рта» без обученного детектора (DEV-8, DEV-9). Та же математика, что в
web/lib/dms/gestures.ts. Расстояния нормируются на ширину лица — не зависят от дистанции до камеры.
Ремень (DEV-10) жестами не определить — только YOLO-модель (dg/detector.py, ml/).
"""

from __future__ import annotations

import math
from dataclasses import dataclass

EAR_L, EAR_R = 234, 454
LIP_TOP, LIP_BOTTOM = 13, 14
PALM = (0, 5, 9, 13, 17)  # запястье и основания пальцев
TIPS = (4, 8, 12)  # большой, указательный, средний
PHONE_REACH = 0.8  # доля ширины лица, ближе которой ладонь считается «у уха»
SMOKE_REACH = 0.3  # доля ширины лица от кончика пальца до рта


@dataclass(frozen=True)
class HandGesture:
    phone_conf: float = 0.0  # 0 или 0.55…0.95
    smoke_conf: float = 0.0


NO_GESTURE = HandGesture()


def _dist(a, b) -> float:
    return math.hypot(a.x - b.x, a.y - b.y)


def _centroid(points):
    n = len(points) or 1
    return _P(sum(p.x for p in points) / n, sum(p.y for p in points) / n)


class _P:
    __slots__ = ("x", "y")

    def __init__(self, x: float, y: float) -> None:
        self.x, self.y = x, y


def _conf(closeness: float) -> float:
    return round(0.55 + 0.4 * closeness, 2) if closeness > 0 else 0.0


def gestures_from_hands(face: list | None, hands: list[list]) -> HandGesture:
    """face — 478 точек лица, hands — по 21 точке на руку (нормированные координаты кадра)."""
    if not face or len(face) < 478 or not hands:
        return NO_GESTURE
    width = _dist(face[EAR_L], face[EAR_R]) or 1e-6
    mouth = _centroid([face[LIP_TOP], face[LIP_BOTTOM]])
    ears = (face[EAR_L], face[EAR_R])
    phone = smoke = 0.0
    for hand in hands:
        if len(hand) < 21:
            continue
        palm = _centroid([hand[i] for i in PALM])
        for ear in ears:
            d = _dist(palm, ear) / width
            dy = abs(palm.y - ear.y) / width
            if d < PHONE_REACH and dy < 0.6:
                phone = max(phone, min(1.0, max(0.0, 1 - d / PHONE_REACH)))
        tip = min(_dist(hand[i], mouth) for i in TIPS) / width
        if tip < SMOKE_REACH:
            smoke = max(smoke, min(1.0, max(0.0, 1 - tip / SMOKE_REACH)))
    if phone > 0 and smoke > 0:  # одна рука не может быть и у уха, и у рта
        if smoke >= phone:
            phone = 0.0
        else:
            smoke = 0.0
    return HandGesture(_conf(phone), _conf(smoke))
