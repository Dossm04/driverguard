"""Нарезка кадров из видео кабины (ML-1): шаг по времени + отсев почти одинаковых кадров (dHash).

Имя файла несёт источник и сессию: `<source>__<session>__<кадр>.jpg` — по сессии потом делается
сплит без утечки кадров одного человека/поездки между train и val (см. split.py).
"""

from __future__ import annotations

import re
from pathlib import Path

import cv2
import numpy as np

_SAFE = re.compile(r"[^A-Za-z0-9._-]+")


def safe_token(value: str) -> str:
    """Имя источника/сессии без пробелов и `__` (разделитель имени файла)."""
    token = _SAFE.sub("-", value.strip()).strip("-")
    return token.replace("__", "-") or "x"


def dhash(image_bgr: np.ndarray, size: int = 8) -> int:
    """Перцептивный хэш: сравнение соседних пикселей уменьшенной серой картинки."""
    gray = cv2.cvtColor(image_bgr, cv2.COLOR_BGR2GRAY) if image_bgr.ndim == 3 else image_bgr
    small = cv2.resize(gray, (size + 1, size), interpolation=cv2.INTER_AREA)
    diff = small[:, 1:] > small[:, :-1]
    return int("".join("1" if b else "0" for b in diff.flatten()), 2)


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def frame_name(source: str, session: str, index: int) -> str:
    return f"{safe_token(source)}__{safe_token(session)}__{index:06d}.jpg"


def extract_frames(
    video: str | Path,
    out_dir: str | Path,
    session: str,
    source: str = "cabin",
    every_ms: int = 500,
    min_hamming: int = 6,
    max_frames: int | None = None,
    gray: bool = False,
    jpeg_quality: int = 92,
) -> int:
    """Пишет кадры в out_dir; возвращает число сохранённых. Похожие подряд кадры (hamming < min) пропускаются."""
    cap = cv2.VideoCapture(str(video))
    if not cap.isOpened():
        raise RuntimeError(f"Не удалось открыть видео: {video}")
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    step = max(1, int(round(every_ms / 1000 * fps)))
    saved = 0
    n = 0
    last_hash: int | None = None
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if n % step == 0:
            h = dhash(frame)
            if last_hash is None or hamming(h, last_hash) >= min_hamming:
                if gray:
                    frame = cv2.cvtColor(cv2.cvtColor(frame, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
                target = out / frame_name(source, session, saved)
                cv2.imwrite(str(target), frame, [cv2.IMWRITE_JPEG_QUALITY, jpeg_quality])
                saved += 1
                last_hash = h
                if max_frames and saved >= max_frames:
                    break
        n += 1
    cap.release()
    return saved
