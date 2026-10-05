"""Очередь дообучения (ML-5): нарезка кадров вокруг момента события из клипа устройства."""

import importlib.util
from pathlib import Path

import cv2
import numpy as np

SCRIPT = Path(__file__).resolve().parent.parent / "scripts" / "retrain_queue.py"


def _load():
    spec = importlib.util.spec_from_file_location("retrain_queue", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_cut_frames_around_event(tmp_path: Path):
    mod = _load()
    clip = tmp_path / "clip.avi"
    w = cv2.VideoWriter(str(clip), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (64, 48))
    for i in range(150):  # 15 с: 10 до события + 5 после
        w.write(np.full((48, 64, 3), i, dtype=np.uint8))
    w.release()
    out = tmp_path / "phone"
    n = mod.cut_frames(clip, out, "abcd1234", offset_s=10.0, window_s=1.0, step_s=0.5)
    files = sorted(out.glob("*.jpg"))
    assert n == len(files) == 5  # 9.0, 9.5, 10.0, 10.5, 11.0 с
    assert files[0].name == "retrain__abcd1234__00.jpg"
    assert mod.cut_frames(tmp_path / "нет.avi", out, "x", 10, 1, 0.5) == 0
    assert mod.LABEL_BY_EVENT == {"phone": "phone", "smoking": "cigarette", "seatbelt": "seatbelt_off"}
