"""Детектор нарушений (DEV-8…DEV-10): декодер YOLOv8, зона «у лица», фоновый поток, загрузка по конфигу."""

import os
import time
from pathlib import Path

import numpy as np
import pytest

from dg.config import Config
from dg.detector import (
    DEVICE_DIR,
    Box,
    ViolationDetector,
    decode,
    letterbox,
    load_detector,
    map_classes,
    near_face,
    nms,
    parse_names,
    summarize,
)

FACE = (0.4, 0.2, 0.6, 0.5)  # бокс лица 0..1


def test_letterbox_decode_nms():
    img = np.zeros((240, 320, 3), dtype=np.uint8)
    canvas, ratio, (dw, dh) = letterbox(img, 160)
    assert canvas.shape == (160, 160, 3) and ratio == 0.5 and (dw, dh) == (0, 20)
    nc = 4
    out = np.zeros((1, 4 + nc, 3), dtype=np.float32)
    out[0, :4, 0] = [80, 80, 40, 60]
    out[0, 4, 0] = 0.9  # phone
    out[0, :4, 1] = [82, 81, 40, 60]
    out[0, 4, 1] = 0.7  # дубль → NMS
    out[0, :4, 2] = [20, 100, 10, 10]
    out[0, 5, 2] = 0.1  # ниже порога
    dets = decode(out, ratio, (dw, dh), (240, 320), 0.25, 0.45, nc)
    assert len(dets) == 1 and dets[0][0] == 0 and abs(dets[0][1] - 0.9) < 1e-6
    cx, cy = (dets[0][2] + dets[0][4]) / 2, (dets[0][3] + dets[0][5]) / 2
    assert abs(cx - 160) < 1 and abs(cy - 120) < 1  # (80-0)/0.5, (80-20)/0.5
    assert nms(np.zeros((0, 4)), np.zeros(0)) == []
    boxes = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], dtype=np.float32)
    assert sorted(nms(boxes, np.array([0.9, 0.8, 0.7]))) == [0, 2]


def test_class_mapping_coco_and_own():
    names = parse_names({"names": "{0: 'person', 67: 'cell phone', 68: 'microwave'}"})
    assert map_classes(names) == {67: "phone"}
    own = parse_names({"names": '["phone", "cigarette", "seatbelt_on", "seatbelt_off"]'})
    assert map_classes(own) == {0: "phone", 1: "cigarette", 2: "seatbelt_on", 3: "seatbelt_off"}
    assert parse_names({}) == {} and parse_names({"names": "???"}) == {}


def test_near_face_zone_and_summarize():
    at_ear = Box("phone", 0.8, 0.58, 0.3, 0.66, 0.45)  # справа у уха
    on_dash = Box("phone", 0.9, 0.05, 0.85, 0.15, 0.95)  # телефон на панели (сценарий Г-10)
    cig = Box("cigarette", 0.7, 0.47, 0.5, 0.53, 0.54)  # у рта
    belt_off = Box("seatbelt_off", 0.6, 0.3, 0.5, 0.7, 0.95)
    assert near_face(at_ear, FACE, 1.8) and not near_face(on_dash, FACE, 1.8)
    assert not near_face(at_ear, None, 1.8)
    sig = summarize([at_ear, on_dash, cig, belt_off], FACE, 1.8, t_ms=1000)
    assert sig.phone_conf == 0.8 and sig.smoke_conf == 0.7 and sig.seatbelt_off_conf == 0.6
    assert sig.seatbelt_on_conf == 0.0 and sig.t_ms == 1000 and len(sig.boxes) == 4
    no_face = summarize([at_ear, on_dash], None, 1.8, t_ms=1)
    assert no_face.phone_conf == 0.0  # без лица телефон не засчитывается (водитель вышел — нет ложных)


class FakeModel:
    version = "fake-v1"

    def __init__(self, boxes):
        self.boxes = boxes
        self.calls = 0

    def detect(self, frame):
        self.calls += 1
        time.sleep(0.01)
        return self.boxes


def test_background_detector_keeps_last_frame_and_expires():
    model = FakeModel([Box("phone", 0.9, 0.58, 0.3, 0.66, 0.45)])
    det = ViolationDetector(model, interval_ms=20, near_face_scale=1.8, stale_ms=500)
    frame = np.zeros((120, 160, 3), dtype=np.uint8)
    assert det.latest(0).phone_conf == 0.0  # до первого результата — нули
    det.start()
    for t in range(0, 400, 33):
        det.submit(frame, t, FACE)
        time.sleep(0.005)
    deadline = time.time() + 2
    while det.latest(400).phone_conf == 0.0 and time.time() < deadline:
        time.sleep(0.02)
    sig = det.latest(400)
    assert sig.phone_conf == 0.9 and sig.t_ms <= 400
    assert det.latest(sig.t_ms + 400).phone_conf == 0.9  # ещё свежий
    assert det.latest(sig.t_ms + 600).phone_conf == 0.0  # устарел → нули (детектор молчит)
    det.stop()
    assert 1 <= model.calls <= 13 and det.stats["frames"] == model.calls  # не каждый кадр, а последний из очереди
    assert det.version == "fake-v1"


def test_load_detector_modes(tmp_path):
    cfg = Config()
    cfg.detector_model = str(tmp_path / "нет.onnx")
    cfg.detector_enabled = "off"
    assert load_detector(cfg) is None
    cfg.detector_enabled = "auto"
    assert load_detector(cfg) is None  # файла нет — тихо без детектора
    with pytest.raises(RuntimeError):
        load_detector(cfg, "on")
    os.environ["DG_YOLO_MODEL"] = str(tmp_path / "env.onnx")
    try:
        with pytest.raises(RuntimeError, match="env.onnx"):
            load_detector(cfg, "on")
    finally:
        del os.environ["DG_YOLO_MODEL"]


COCO = DEVICE_DIR / "models" / "yolov8n-coco.onnx"


@pytest.mark.skipif(not COCO.is_file(), reason="нет device/models/yolov8n-coco.onnx (ml/scripts/export.py --coco)")
def test_real_coco_model_runs_on_cpu():
    pytest.importorskip("onnxruntime")
    cfg = Config()
    cfg.detector_model = str(COCO)
    det = load_detector(cfg, "on")
    assert det is not None and det.version == "coco-yolov8n" and det.model.class_map == {67: "phone"}
    frame = np.full((480, 640, 3), 114, dtype=np.uint8)
    sig = det.process(frame, 100, FACE)
    assert sig.t_ms == 100 and sig.phone_conf == 0.0 and not sig.boxes  # серый кадр — ничего
    assert Path(det.model.path).name == "yolov8n-coco.onnx"
