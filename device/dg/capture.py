"""Захват видео (DEV-1): камера по индексу или файл. Для файла время кадра — из позиции в записи,
чтобы пороги (1.5 с и т.п.) считались по времени видео, а не по скорости обработки."""

from __future__ import annotations

import time
from collections.abc import Iterator

import cv2
import numpy as np


class Capture:
    def __init__(self, source: str | int, width: int = 640, height: int = 480, fps: int = 30):
        self.is_file = isinstance(source, str) and not source.isdigit()
        self.cap = cv2.VideoCapture(source if self.is_file else int(source))
        if not self.cap.isOpened():
            raise RuntimeError(f"Не удалось открыть источник видео: {source}")
        if not self.is_file:
            self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, width)
            self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, height)
            self.cap.set(cv2.CAP_PROP_FPS, fps)
        self.fps = self.cap.get(cv2.CAP_PROP_FPS) or fps
        self._t0 = time.monotonic()
        self._n = 0

    def frames(self) -> Iterator[tuple[np.ndarray, int]]:
        """(кадр BGR, метка времени, мс)."""
        while True:
            ok, frame = self.cap.read()
            if not ok:
                return
            if self.is_file:
                t_ms = int(self.cap.get(cv2.CAP_PROP_POS_MSEC) or self._n * 1000 / self.fps)
            else:
                t_ms = int((time.monotonic() - self._t0) * 1000)
            self._n += 1
            yield frame, t_ms

    def release(self) -> None:
        self.cap.release()
