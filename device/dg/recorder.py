"""Клипы событий (DEV-17): кольцевой буфер 20 с в памяти; при событии — 10 с до / 5 с после,
640×480, H.264 через ffmpeg (libx264 ultrafast), без ffmpeg — mp4v средствами OpenCV."""

from __future__ import annotations

import logging
import shutil
import subprocess
import threading
from collections import deque
from collections.abc import Callable
from pathlib import Path

import cv2
import numpy as np

log = logging.getLogger("dg.recorder")


class RingBuffer:
    def __init__(self, seconds: float, fps: float):
        self.maxlen = int(seconds * fps)
        self.frames: deque[tuple[int, np.ndarray]] = deque(maxlen=self.maxlen)

    def push(self, t_ms: int, frame: np.ndarray) -> None:
        self.frames.append((t_ms, frame))

    def between(self, t_from: int, t_to: int) -> list[np.ndarray]:
        return [f for t, f in self.frames if t_from <= t <= t_to]


def encode(frames: list[np.ndarray], path: Path, fps: float, size: tuple[int, int] = (640, 480)) -> Path:
    """H.264 (libx264 ultrafast) через ffmpeg; иначе OpenCV mp4v. Возвращает путь к файлу."""
    path.parent.mkdir(parents=True, exist_ok=True)
    resized = [cv2.resize(f, size) if (f.shape[1], f.shape[0]) != size else f for f in frames]
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg and resized:
        cmd = [
            ffmpeg,
            "-y",
            "-loglevel",
            "error",
            "-f",
            "rawvideo",
            "-pix_fmt",
            "bgr24",
            "-s",
            f"{size[0]}x{size[1]}",
            "-r",
            f"{fps:.2f}",
            "-i",
            "-",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-crf",
            "28",
            "-pix_fmt",
            "yuv420p",
            str(path),
        ]
        try:
            proc = subprocess.run(cmd, input=b"".join(f.tobytes() for f in resized), check=True, capture_output=True)
            if proc.returncode == 0 and path.is_file():
                return path
        except (subprocess.CalledProcessError, OSError) as exc:
            log.warning("ffmpeg не справился (%s) — кодируем через OpenCV", exc)
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    for f in resized:
        writer.write(f)
    writer.release()
    return path


class Recorder:
    """Собирает кадры, по on_event через post_s секунд пишет клип и зовёт on_clip(uuid, path)."""

    def __init__(
        self,
        out_dir: str | Path,
        fps: float = 30,
        buffer_s: int = 20,
        pre_s: int = 10,
        post_s: int = 5,
        on_clip: Callable[[str, str], None] | None = None,
    ):
        self.out_dir = Path(out_dir)
        self.fps = fps
        self.pre_ms, self.post_ms = pre_s * 1000, post_s * 1000
        self.ring = RingBuffer(buffer_s, fps)
        self.pending: list[tuple[str, int]] = []  # (uuid, t_ms события)
        self.on_clip = on_clip
        self.written: list[Path] = []

    def push(self, t_ms: int, frame: np.ndarray) -> None:
        self.ring.push(t_ms, frame)
        due = [p for p in self.pending if t_ms - p[1] >= self.post_ms]
        for uuid, t_event in due:
            self.pending.remove((uuid, t_event))
            frames = self.ring.between(t_event - self.pre_ms, t_event + self.post_ms)
            threading.Thread(target=self._write, args=(uuid, frames), daemon=True).start()

    def on_event(self, uuid: str, t_ms: int) -> None:
        self.pending.append((uuid, t_ms))

    def flush(self) -> None:
        """Дописать ожидающие клипы тем, что есть (остановка программы)."""
        for uuid, t_event in list(self.pending):
            self.pending.remove((uuid, t_event))
            self._write(uuid, self.ring.between(t_event - self.pre_ms, t_event + self.post_ms))

    def _write(self, uuid: str, frames: list[np.ndarray]) -> None:
        if not frames:
            return
        path = encode(frames, self.out_dir / f"{uuid}.mp4", self.fps)
        self.written.append(path)
        log.info("Клип %s: %d кадров → %s", uuid, len(frames), path.name)
        if self.on_clip:
            self.on_clip(uuid, str(path))
