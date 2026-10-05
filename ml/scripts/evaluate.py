#!/usr/bin/env python
"""Оценка модели (ML-2): mAP/P/R по классам, confusion matrix, ворота; проверка на тест-видео из кабины.

  python scripts/evaluate.py --weights runs/v1/weights/best.pt --version v1              # val
  python scripts/evaluate.py --weights runs/v1/weights/best.pt --split test
  python scripts/evaluate.py --weights runs/v1/weights/best.pt --video cabin_test.mp4    # кадры с телефоном
  python scripts/evaluate.py --onnx models/violations_v1.onnx --video cabin_test.mp4     # без torch

Результаты → runs/eval_<имя>/: eval.json, confusion_matrix.md, per_class.md, <видео>_detections.csv.
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dgml import ML_ROOT, registry  # noqa: E402
from dgml.classes import EVENT_BY_CLASS  # noqa: E402
from dgml.metrics import GATE_MAP50, confusion_markdown, gate, per_class_markdown, summarize_val  # noqa: E402


def eval_split(weights: str, data: str, split: str, imgsz: int, out: Path, threshold: float) -> tuple[dict, bool]:
    try:
        from ultralytics import YOLO
    except ImportError:
        print("Нет ultralytics: pip install -e \".[train]\"", file=sys.stderr)
        raise SystemExit(1) from None
    model = YOLO(weights)
    res = model.val(data=str(Path(data).resolve()), split=split, imgsz=imgsz, plots=True, project=str(out.parent),
                    name=out.name, exist_ok=True, verbose=False)
    summary = summarize_val(res, res.names)
    passed, text = gate(summary, threshold)
    names = [res.names[k] for k in sorted(res.names)]
    (out / "eval.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (out / "per_class.md").write_text(per_class_markdown(summary["per_class"]) + "\n", encoding="utf-8")
    if "confusion" in summary:
        cm_md = confusion_markdown(summary["confusion"], names)
        (out / "confusion_matrix.md").write_text(cm_md + "\n", encoding="utf-8")
        print(confusion_markdown(summary["confusion"], names))
    print(per_class_markdown(summary["per_class"]))
    print(f"{split}: {text}")
    return summary, passed


def eval_video(
    detector, video: str, out: Path, conf: float, names: dict[int, str], stride: int, save_video: bool
) -> dict:
    import cv2

    cap = cv2.VideoCapture(video)
    if not cap.isOpened():
        raise RuntimeError(f"Не удалось открыть {video}")
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    writer = None
    stem = Path(video).stem
    rows: list[list] = []
    seconds: dict[str, set[int]] = {}
    n = 0
    while True:
        ok, frame = cap.read()
        if not ok:
            break
        if n % stride == 0:
            t_ms = int(n / fps * 1000)
            for d in detector(frame):
                if d.conf < conf:
                    continue
                name = names.get(d.cls, str(d.cls))
                rows.append([t_ms, name, round(d.conf, 3), int(d.x1), int(d.y1), int(d.x2), int(d.y2)])
                seconds.setdefault(name, set()).add(t_ms // 1000)
                if save_video:
                    cv2.rectangle(frame, (int(d.x1), int(d.y1)), (int(d.x2), int(d.y2)), (60, 130, 246), 2)
                    cv2.putText(frame, f"{name} {d.conf:.2f}", (int(d.x1), max(12, int(d.y1) - 4)),
                                cv2.FONT_HERSHEY_SIMPLEX, 0.5, (60, 130, 246), 1, cv2.LINE_AA)
            if save_video:
                if writer is None:
                    h, w = frame.shape[:2]
                    writer = cv2.VideoWriter(str(out / f"{stem}_detections.mp4"), cv2.VideoWriter_fourcc(*"mp4v"),
                                             max(1.0, fps / stride), (w, h))
                writer.write(frame)
        n += 1
    cap.release()
    if writer:
        writer.release()
    with (out / f"{stem}_detections.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        w.writerow(["t_ms", "class", "conf", "x1", "y1", "x2", "y2"])
        w.writerows(rows)
    summary = {
        "video": video, "frames": n, "detections": len(rows),
        "seconds_by_class": {k: len(v) for k, v in seconds.items()},
        "events_hint": {EVENT_BY_CLASS[k]: len(v) for k, v in seconds.items() if k in EVENT_BY_CLASS},
    }
    print(f"{video}: кадров {n}, детекций {len(rows)}, секунд с классом: {summary['seconds_by_class']}")
    return summary


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Оценка детектора нарушений")
    p.add_argument("--weights", default=None, help="best.pt (нужен ultralytics)")
    p.add_argument("--onnx", default=None, help="ONNX-модель (оценка на видео без torch)")
    p.add_argument("--data", default="data/dataset/data.yaml")
    p.add_argument("--split", default="val", choices=["val", "test"])
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--conf", type=float, default=0.25)
    p.add_argument("--video", nargs="*", default=[], help="тест-видео из кабины")
    p.add_argument("--stride", type=int, default=3, help="анализировать каждый N-й кадр видео")
    p.add_argument("--save-video", action="store_true", help="писать видео с боксами (mp4)")
    p.add_argument("--version", default=None, help="записать метрики в реестр для этой версии")
    p.add_argument("--out", default=None, help="папка результатов (по умолчанию runs/eval_<версия|веса>)")
    p.add_argument("--gate", type=float, default=GATE_MAP50)
    p.add_argument("--no-split", action="store_true", help="только видео, без val/test")
    a = p.parse_args(argv)
    if not a.weights and not a.onnx:
        p.error("нужен --weights или --onnx")
    tag = a.version or Path(a.weights or a.onnx).stem
    out = Path(a.out) if a.out else ML_ROOT / "runs" / f"eval_{tag}"
    out.mkdir(parents=True, exist_ok=True)

    passed = True
    result: dict = {}
    if a.weights and not a.no_split:
        result, passed = eval_split(a.weights, a.data, a.split, a.imgsz, out, a.gate)
    if a.video:
        if a.onnx:
            from dgml.onnx_infer import OnnxDetector

            det = OnnxDetector(a.onnx, conf=a.conf)
            names, detector = det.names, det.detect
        else:
            from ultralytics import YOLO

            from dgml.onnx_infer import Det

            model = YOLO(a.weights)
            names = model.names

            def detector(frame):
                r = model.predict(frame, imgsz=a.imgsz, conf=a.conf, verbose=False)[0]
                return [Det(int(c), float(s), *map(float, b)) for b, s, c in
                        zip(r.boxes.xyxy.tolist(), r.boxes.conf.tolist(), r.boxes.cls.tolist(), strict=True)]

        result["videos"] = [eval_video(detector, v, out, a.conf, names, a.stride, a.save_video) for v in a.video]
    (out / "eval.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    if a.version and a.weights and not a.no_split:
        reg = registry.load()
        if registry.get(reg, a.version):
            new_metrics = {f"{a.split}_map50": result["map50"], "per_class": result["per_class"]}
            registry.update(reg, a.version, metrics=new_metrics, gate={"threshold": a.gate, "passed": passed})
            registry.save(reg)
            print(f"Реестр обновлён: {a.version}")
    print(f"Результаты → {out}")
    return 0 if passed else 2


if __name__ == "__main__":
    sys.exit(main())
