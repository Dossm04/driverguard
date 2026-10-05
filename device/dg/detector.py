"""Детектор нарушений (DEV-8…DEV-10, ML-4): YOLOv8-ONNX через onnxruntime на CPU в отдельном потоке.

До своей модели — COCO yolov8n (класс «cell phone»); после `ml/scripts/registry.py promote vN` —
своя модель с классами phone / cigarette / seatbelt_on / seatbelt_off. Главный цикл (MediaPipe, 30 FPS)
не ждёт детектор: submit() оставляет последний кадр, поток считает не чаще interval_ms, latest() отдаёт
последние сигналы. Телефон и сигарета засчитываются только в зоне «у лица» (Приложение Г: телефон на
панели — не событие), поэтому без лица в кадре они равны 0.
"""

from __future__ import annotations

import ast
import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

log = logging.getLogger("dg.detector")

DEVICE_DIR = Path(__file__).resolve().parent.parent
CLASS_ALIASES: dict[str, set[str]] = {
    "phone": {"phone", "cell phone", "cellphone", "cell_phone", "mobile phone", "mobile_phone", "smartphone"},
    "cigarette": {"cigarette", "cigar", "smoking", "vape", "e-cigarette"},
    "seatbelt_on": {"seatbelt_on", "seatbelt", "seat belt", "seat_belt", "belt_on"},
    "seatbelt_off": {"seatbelt_off", "no_seatbelt", "no seatbelt", "no seat belt", "belt_off"},
}
MAX_VERSION_LEN = 20  # devices.model_version в backend — String(20)


@dataclass
class Box:
    cls: str  # наш класс: phone | cigarette | seatbelt_on | seatbelt_off
    conf: float
    x1: float  # нормированные координаты 0..1
    y1: float
    x2: float
    y2: float

    @property
    def center(self) -> tuple[float, float]:
        return (self.x1 + self.x2) / 2, (self.y1 + self.y2) / 2


@dataclass
class DetectorSignals:
    t_ms: int = 0
    phone_conf: float = 0.0
    smoke_conf: float = 0.0
    seatbelt_off_conf: float = 0.0
    seatbelt_on_conf: float = 0.0
    boxes: list[Box] = field(default_factory=list)


# ── чистая математика (та же, что в ml/dgml/onnx_infer.py) ──
def letterbox(img: np.ndarray, size: int, color: int = 114) -> tuple[np.ndarray, float, tuple[int, int]]:
    import cv2  # slim-образ симулятора без OpenCV импортирует dg.app — cv2 нужен только детектору

    h, w = img.shape[:2]
    ratio = min(size / h, size / w)
    nw, nh = int(round(w * ratio)), int(round(h * ratio))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR) if (nw, nh) != (w, h) else img
    dw, dh = (size - nw) // 2, (size - nh) // 2
    canvas = np.full((size, size, 3), color, dtype=np.uint8)
    canvas[dh : dh + nh, dw : dw + nw] = resized
    return canvas, ratio, (dw, dh)


def nms(boxes: np.ndarray, scores: np.ndarray, iou_thr: float = 0.45) -> list[int]:
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes.T
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep: list[int] = []
    while order.size:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        rest = order[1:]
        xx1, yy1 = np.maximum(x1[i], x1[rest]), np.maximum(y1[i], y1[rest])
        xx2, yy2 = np.minimum(x2[i], x2[rest]), np.minimum(y2[i], y2[rest])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        order = rest[inter / (areas[i] + areas[rest] - inter + 1e-9) <= iou_thr]
    return keep


def decode(
    output: np.ndarray,
    ratio: float,
    pad: tuple[int, int],
    shape: tuple[int, int],
    conf_thr: float,
    iou_thr: float,
    nc: int,
) -> list[tuple[int, float, float, float, float, float]]:
    """Выход YOLOv8 (1, 4+nc, N) → [(cls_id, conf, x1, y1, x2, y2)] в пикселях кадра."""
    out = output[0] if output.ndim == 3 else output
    if out.shape[0] == 4 + nc:
        out = out.T
    scores = out[:, 4:]
    cls_ids = scores.argmax(axis=1)
    confs = scores[np.arange(len(cls_ids)), cls_ids]
    mask = confs >= conf_thr
    if not mask.any():
        return []
    b, c, s = out[mask, :4], cls_ids[mask], confs[mask]
    xyxy = np.stack([b[:, 0] - b[:, 2] / 2, b[:, 1] - b[:, 3] / 2, b[:, 0] + b[:, 2] / 2, b[:, 1] + b[:, 3] / 2], 1)
    h, w = shape
    dets = []
    for ci in np.unique(c):
        idx = np.where(c == ci)[0]
        for k in nms(xyxy[idx], s[idx], iou_thr):
            x1, y1, x2, y2 = xyxy[idx[k]]
            dets.append(
                (
                    int(ci),
                    float(s[idx[k]]),
                    float(np.clip((x1 - pad[0]) / ratio, 0, w)),
                    float(np.clip((y1 - pad[1]) / ratio, 0, h)),
                    float(np.clip((x2 - pad[0]) / ratio, 0, w)),
                    float(np.clip((y2 - pad[1]) / ratio, 0, h)),
                )
            )
    return dets


def parse_names(meta: dict) -> dict[int, str]:
    raw = meta.get("names")
    if not raw:
        return {}
    try:
        names = ast.literal_eval(raw)
    except (ValueError, SyntaxError):
        try:
            names = json.loads(raw)
        except json.JSONDecodeError:
            return {}
    if isinstance(names, list):
        return dict(enumerate(str(n) for n in names))
    return {int(k): str(v) for k, v in names.items()}


def map_classes(names: dict[int, str]) -> dict[int, str]:
    """id класса модели → наш класс; лишние классы (COCO person, car…) не попадают в карту."""
    out: dict[int, str] = {}
    for idx, name in names.items():
        key = name.strip().lower().replace("-", " ")
        for ours, aliases in CLASS_ALIASES.items():
            if key == ours or key in aliases or key.replace(" ", "_") in aliases:
                out[idx] = ours
                break
    return out


def near_face(box: Box, face: tuple[float, float, float, float] | None, scale: float) -> bool:
    """Центр бокса в зоне «у лица»: бокс лица, расширенный в scale раз и сдвинутый вниз (ухо, рот, рука)."""
    if face is None:
        return False
    fx1, fy1, fx2, fy2 = face
    fw, fh = fx2 - fx1, fy2 - fy1
    if fw <= 0 or fh <= 0:
        return False
    cx, cy = (fx1 + fx2) / 2, (fy1 + fy2) / 2 + fh * 0.25
    zx1, zx2 = cx - fw * scale / 2, cx + fw * scale / 2
    zy1, zy2 = cy - fh * scale / 2, cy + fh * scale / 2
    bx, by = box.center
    return zx1 <= bx <= zx2 and zy1 <= by <= zy2


def summarize(boxes: list[Box], face: tuple | None, near_face_scale: float, t_ms: int) -> DetectorSignals:
    sig = DetectorSignals(t_ms=t_ms, boxes=boxes)
    for b in boxes:
        if b.cls == "phone" and near_face(b, face, near_face_scale):
            sig.phone_conf = max(sig.phone_conf, b.conf)
        elif b.cls == "cigarette" and near_face(b, face, near_face_scale):
            sig.smoke_conf = max(sig.smoke_conf, b.conf)
        elif b.cls == "seatbelt_off":
            sig.seatbelt_off_conf = max(sig.seatbelt_off_conf, b.conf)
        elif b.cls == "seatbelt_on":
            sig.seatbelt_on_conf = max(sig.seatbelt_on_conf, b.conf)
    return sig


class OnnxYolo:
    """YOLOv8-ONNX через onnxruntime (CPUExecutionProvider). Имена классов и размер входа — из модели."""

    def __init__(self, path: str | Path, conf: float = 0.35, iou: float = 0.45, threads: int = 2):
        import onnxruntime as ort  # тяжёлый импорт — только здесь

        opts = ort.SessionOptions()
        opts.intra_op_num_threads = max(1, threads)
        opts.inter_op_num_threads = 1
        self.path = Path(path)
        self.session = ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])
        inp = self.session.get_inputs()[0]
        self.input_name = inp.name
        self.size = int(inp.shape[-1]) if isinstance(inp.shape[-1], int) else 640
        meta = self.session.get_modelmeta().custom_metadata_map or {}
        self.names = parse_names(meta)
        self.class_map = map_classes(self.names)
        self.version = (meta.get("dg_version") or self.path.stem)[:MAX_VERSION_LEN]
        self.conf, self.iou = conf, iou
        if not self.class_map:
            raise RuntimeError(f"В модели {self.path.name} нет классов phone/cigarette/seatbelt — не та модель")

    def detect(self, frame_bgr: np.ndarray) -> list[Box]:
        canvas, ratio, pad = letterbox(frame_bgr, self.size)
        blob = np.ascontiguousarray(canvas[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0)
        output = self.session.run(None, {self.input_name: blob})[0]
        h, w = frame_bgr.shape[:2]
        boxes = []
        for cls_id, conf, x1, y1, x2, y2 in decode(output, ratio, pad, (h, w), self.conf, self.iou, len(self.names)):
            ours = self.class_map.get(cls_id)
            if ours:
                boxes.append(Box(ours, round(conf, 3), x1 / w, y1 / h, x2 / w, y2 / h))
        return boxes


class ViolationDetector:
    """Фоновый поток над моделью: последний кадр → сигналы; главный цикл не блокируется."""

    def __init__(self, model, interval_ms: int = 250, near_face_scale: float = 1.8, stale_ms: int = 1500):
        self.model = model
        self.interval_ms = interval_ms
        self.near_face_scale = near_face_scale
        self.stale_ms = stale_ms
        self.version = getattr(model, "version", "unknown")
        self._lock = threading.Lock()
        self._new = threading.Event()
        self._stop = threading.Event()
        self._pending: tuple[np.ndarray, int, tuple | None] | None = None
        self._latest = DetectorSignals()
        self._thread = threading.Thread(target=self._run, name="dg-detector", daemon=True)
        self.stats = {"frames": 0, "infer_ms": 0.0, "errors": 0}

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        self._new.set()
        if self._thread.is_alive():
            self._thread.join(timeout=3)

    def submit(self, frame: np.ndarray, t_ms: int, face_box: tuple | None) -> None:
        with self._lock:
            self._pending = (frame, t_ms, face_box)  # только последний кадр; старый — в мусор
        self._new.set()

    def latest(self, t_ms: int) -> DetectorSignals:
        with self._lock:
            sig = self._latest
        if not sig.boxes and sig.t_ms == 0:
            return sig
        return sig if t_ms - sig.t_ms <= self.stale_ms else DetectorSignals(t_ms=sig.t_ms)

    def process(self, frame: np.ndarray, t_ms: int, face_box: tuple | None) -> DetectorSignals:
        """Синхронный вариант (тесты, прогон видеофайла)."""
        sig = summarize(self.model.detect(frame), face_box, self.near_face_scale, t_ms)
        with self._lock:
            self._latest = sig
        return sig

    def _run(self) -> None:
        while not self._stop.is_set():
            self._new.wait(timeout=1.0)
            self._new.clear()
            if self._stop.is_set():
                break
            with self._lock:
                job, self._pending = self._pending, None
            if job is None:
                continue
            frame, t_ms, face_box = job
            started = time.monotonic()
            try:
                self.process(frame.copy(), t_ms, face_box)
            except Exception as exc:  # noqa: BLE001 — детектор не должен ронять DMS
                self.stats["errors"] += 1
                if self.stats["errors"] <= 3:
                    log.warning("Детектор: %s", exc)
            took = (time.monotonic() - started) * 1000
            self.stats["frames"] += 1
            self.stats["infer_ms"] += (took - self.stats["infer_ms"]) * 0.2
            rest = self.interval_ms / 1000 - (time.monotonic() - started)
            if rest > 0:
                self._stop.wait(rest)


def resolve_model_path(model: str) -> Path:
    custom = os.environ.get("DG_YOLO_MODEL")
    path = Path(custom) if custom else Path(model)
    return path if path.is_absolute() else DEVICE_DIR / path


def load_detector(cfg, mode: str | None = None) -> ViolationDetector | None:
    """auto — включить, если есть onnxruntime и файл модели; on — обязательно (иначе ошибка); off — нет."""
    mode = (mode or os.environ.get("DG_DETECTOR") or cfg.detector_enabled or "auto").lower()
    if mode == "off":
        log.info("Детектор нарушений выключен (detector.enabled=off)")
        return None
    path = resolve_model_path(cfg.detector_model)
    if not path.is_file():
        msg = f"Модель детектора не найдена: {path} (ml/scripts/export.py --coco или registry.py promote vN)"
        if mode == "on":
            raise RuntimeError(msg)
        log.info("%s — работаем без детектора телефона/курения/ремня", msg)
        return None
    try:
        model = OnnxYolo(path, conf=cfg.detector_conf, threads=cfg.detector_threads)
    except ImportError:
        msg = 'onnxruntime не установлен: pip install -e ".[yolo]"'
        if mode == "on":
            raise RuntimeError(msg) from None
        log.info("%s — работаем без детектора", msg)
        return None
    det = ViolationDetector(model, interval_ms=cfg.detector_interval_ms, near_face_scale=cfg.detector_near_face)
    log.info(
        "Детектор нарушений: %s (%s), классы %s, вход %d, каждые %d мс",
        model.version,
        path.name,
        sorted(set(model.class_map.values())),
        model.size,
        cfg.detector_interval_ms,
    )
    return det
