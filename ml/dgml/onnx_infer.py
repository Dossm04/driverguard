"""Инференс YOLOv8-ONNX без torch (проверка экспорта, оценка ONNX на видео). Та же математика,
что в device/dg/detector.py — letterbox, декодирование (1, 4+nc, N), NMS на numpy."""

from __future__ import annotations

import ast
import json
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np


@dataclass
class Det:
    cls: int
    conf: float
    x1: float
    y1: float
    x2: float
    y2: float


def letterbox(img: np.ndarray, size: int = 640, color: int = 114) -> tuple[np.ndarray, float, tuple[int, int]]:
    h, w = img.shape[:2]
    ratio = min(size / h, size / w)
    nw, nh = int(round(w * ratio)), int(round(h * ratio))
    resized = cv2.resize(img, (nw, nh), interpolation=cv2.INTER_LINEAR) if (nw, nh) != (w, h) else img
    dw, dh = (size - nw) // 2, (size - nh) // 2
    canvas = np.full((size, size, 3), color, dtype=np.uint8)
    canvas[dh : dh + nh, dw : dw + nw] = resized
    return canvas, ratio, (dw, dh)


def preprocess(img_bgr: np.ndarray, size: int = 640) -> tuple[np.ndarray, float, tuple[int, int]]:
    canvas, ratio, pad = letterbox(img_bgr, size)
    blob = canvas[:, :, ::-1].transpose(2, 0, 1)[None].astype(np.float32) / 255.0
    return np.ascontiguousarray(blob), ratio, pad


def nms(boxes: np.ndarray, scores: np.ndarray, iou_thr: float = 0.45) -> list[int]:
    if len(boxes) == 0:
        return []
    x1, y1, x2, y2 = boxes.T
    areas = (x2 - x1) * (y2 - y1)
    order = scores.argsort()[::-1]
    keep = []
    while order.size:
        i = int(order[0])
        keep.append(i)
        if order.size == 1:
            break
        rest = order[1:]
        xx1 = np.maximum(x1[i], x1[rest])
        yy1 = np.maximum(y1[i], y1[rest])
        xx2 = np.minimum(x2[i], x2[rest])
        yy2 = np.minimum(y2[i], y2[rest])
        inter = np.clip(xx2 - xx1, 0, None) * np.clip(yy2 - yy1, 0, None)
        iou = inter / (areas[i] + areas[rest] - inter + 1e-9)
        order = rest[iou <= iou_thr]
    return keep


def decode(
    output: np.ndarray,
    ratio: float,
    pad: tuple[int, int],
    orig_shape: tuple[int, int],
    conf_thr: float = 0.25,
    iou_thr: float = 0.45,
    nc: int | None = None,
) -> list[Det]:
    """Выход YOLOv8 (1, 4+nc, N) или (1, N, 4+nc) → детекции в координатах исходного кадра.

    nc — число классов, если известно (снимает неоднозначность при малом N); иначе считаем,
    что меньшая размерность — каналы (у ultralytics N = 8400 ≫ 4 + nc).
    """
    out = output[0] if output.ndim == 3 else output
    channels_first = out.shape[0] == 4 + nc if nc else out.shape[0] < out.shape[1]
    if channels_first:  # (4+nc, N) → (N, 4+nc)
        out = out.T
    boxes_cxcywh, cls_scores = out[:, :4], out[:, 4:]
    cls_ids = cls_scores.argmax(axis=1)
    confs = cls_scores[np.arange(len(cls_ids)), cls_ids]
    mask = confs >= conf_thr
    if not mask.any():
        return []
    b, c, s = boxes_cxcywh[mask], cls_ids[mask], confs[mask]
    xyxy = np.stack([b[:, 0] - b[:, 2] / 2, b[:, 1] - b[:, 3] / 2, b[:, 0] + b[:, 2] / 2, b[:, 1] + b[:, 3] / 2], 1)
    dets: list[Det] = []
    h, w = orig_shape
    for ci in np.unique(c):  # NMS по классам
        idx = np.where(c == ci)[0]
        for k in nms(xyxy[idx], s[idx], iou_thr):
            x1, y1, x2, y2 = xyxy[idx[k]]
            x1, x2 = (x1 - pad[0]) / ratio, (x2 - pad[0]) / ratio
            y1, y2 = (y1 - pad[1]) / ratio, (y2 - pad[1]) / ratio
            dets.append(
                Det(int(ci), float(s[idx[k]]), float(np.clip(x1, 0, w)), float(np.clip(y1, 0, h)),
                    float(np.clip(x2, 0, w)), float(np.clip(y2, 0, h)))
            )
    dets.sort(key=lambda d: -d.conf)
    return dets


def parse_names(meta: dict) -> dict[int, str]:
    """Имена классов из metadata ONNX ultralytics (строка-словарь Python или JSON)."""
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


class OnnxDetector:
    """YOLOv8 ONNX через onnxruntime (CPU). Имена классов и imgsz — из метаданных модели."""

    def __init__(self, path: str | Path, conf: float = 0.25, iou: float = 0.45, threads: int | None = None):
        import onnxruntime as ort  # тяжёлый импорт — только здесь

        opts = ort.SessionOptions()
        if threads:
            opts.intra_op_num_threads = threads
        self.session = ort.InferenceSession(str(path), opts, providers=["CPUExecutionProvider"])
        inp = self.session.get_inputs()[0]
        self.input_name = inp.name
        self.size = int(inp.shape[-1]) if isinstance(inp.shape[-1], int) else 640
        meta = self.session.get_modelmeta().custom_metadata_map or {}
        self.names = parse_names(meta)
        self.version = meta.get("dg_version") or Path(path).stem
        self.conf, self.iou = conf, iou

    def detect(self, img_bgr: np.ndarray) -> list[Det]:
        blob, ratio, pad = preprocess(img_bgr, self.size)
        output = self.session.run(None, {self.input_name: blob})[0]
        return decode(output, ratio, pad, img_bgr.shape[:2], self.conf, self.iou, nc=len(self.names) or None)
