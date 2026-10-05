"""Синтетический датасет для smoke-прогонов и тестов: цветные фигуры вместо телефона/сигареты/ремня.

Не заменяет реальные данные (ML-1), но позволяет проверить весь конвейер
prepare → train → evaluate → export → детектор устройства без GPU и без датасета.
"""

from __future__ import annotations

import random
from pathlib import Path

import cv2
import numpy as np

from dgml.classes import CLASSES
from dgml.frames import frame_name
from dgml.labels import write_labels

SCENES = ["phone", "cigarette", "seatbelt_on", "seatbelt_off", "negative"]


def _yolo(x1: int, y1: int, x2: int, y2: int, w: int, h: int) -> tuple[float, float, float, float]:
    return ((x1 + x2) / 2 / w, (y1 + y2) / 2 / h, (x2 - x1) / w, (y2 - y1) / h)


def render(scene: str, rng: random.Random, size: tuple[int, int] = (320, 240)) -> tuple[np.ndarray, list]:
    """Кадр «кабины»: фон, голова, торс и один объект сцены; возвращает (BGR, YOLO-боксы)."""
    w, h = size
    img = np.full((h, w, 3), rng.randint(40, 90), dtype=np.uint8)
    noise = rng.randint(0, 25)
    if noise:
        img = cv2.add(img, np.random.default_rng(rng.randint(0, 10**6)).integers(0, noise, (h, w, 3), dtype=np.uint8))
    cx, cy, r = w // 2 + rng.randint(-30, 30), h // 3 + rng.randint(-15, 15), rng.randint(28, 40)
    cv2.circle(img, (cx, cy), r, (150, 180, 220), -1)  # голова (тон кожи, BGR)
    torso = (cx - int(r * 1.8), cy + r, cx + int(r * 1.8), h - 5)
    cv2.rectangle(img, torso[:2], torso[2:], (70, 60, 55), -1)  # куртка
    boxes = []
    if scene == "phone":
        pw, ph = rng.randint(18, 26), rng.randint(36, 50)
        x1 = cx + r - rng.randint(0, 8)
        y1 = cy - ph // 2 + rng.randint(-6, 6)
        cv2.rectangle(img, (x1, y1), (x1 + pw, y1 + ph), (200, 60, 20), -1)
        cv2.rectangle(img, (x1 + 3, y1 + 4), (x1 + pw - 3, y1 + ph - 6), (240, 230, 200), -1)
        boxes.append((CLASSES.index("phone"), *_yolo(x1, y1, x1 + pw, y1 + ph, w, h)))
    elif scene == "cigarette":
        cw, ch = rng.randint(26, 36), rng.randint(5, 7)
        x1, y1 = cx + rng.randint(-4, 4), cy + r // 2 + rng.randint(-3, 3)
        cv2.rectangle(img, (x1, y1), (x1 + cw, y1 + ch), (245, 245, 245), -1)
        cv2.rectangle(img, (x1 + cw - 6, y1), (x1 + cw, y1 + ch), (40, 90, 230), -1)
        boxes.append((CLASSES.index("cigarette"), *_yolo(x1, y1, x1 + cw, y1 + ch, w, h)))
    elif scene == "seatbelt_on":
        x1, y1, x2, y2 = torso
        pts = np.array([[x1 + 5, y1], [x1 + 25, y1], [x2 - 5, y2], [x2 - 25, y2]], dtype=np.int32)
        cv2.fillPoly(img, [pts], (40, 160, 60))
        boxes.append((CLASSES.index("seatbelt_on"), *_yolo(x1, y1, x2, y2, w, h)))
    elif scene == "seatbelt_off":
        x1, y1, x2, y2 = torso
        cv2.rectangle(img, (x1, y1), (x2, y2), (40, 40, 200), 3)
        boxes.append((CLASSES.index("seatbelt_off"), *_yolo(x1, y1, x2, y2, w, h)))
    return img, boxes


def make_dataset(
    root: Path, sessions: int = 6, per_session: int = 20, seed: int = 0, size: tuple[int, int] = (320, 240)
) -> int:
    """Пишет root/images/*.jpg, root/labels/*.txt и root/classes.txt; возвращает число изображений."""
    rng = random.Random(seed)
    root = Path(root)
    (root / "images").mkdir(parents=True, exist_ok=True)
    (root / "labels").mkdir(parents=True, exist_ok=True)
    (root / "classes.txt").write_text("\n".join(CLASSES) + "\n", encoding="utf-8")
    n = 0
    for s in range(sessions):
        source = "cabin" if s % 2 == 0 else "roboflow"
        session = f"s{s:02d}"
        for i in range(per_session):
            scene = SCENES[i % len(SCENES)] if i % 7 else "negative"
            img, boxes = render(scene, rng, size)
            name = frame_name(source, session, i)
            cv2.imwrite(str(root / "images" / name), img)
            write_labels(root / "labels" / Path(name).with_suffix(".txt").name, boxes)
            n += 1
    return n
