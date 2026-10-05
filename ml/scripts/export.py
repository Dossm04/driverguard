#!/usr/bin/env python
"""Экспорт в ONNX (ML-3, шаг 1) + калибровочный набор для Hailo DFC (шаг 2 — после приезда железа).

  python scripts/export.py --version v1                       # best.pt версии из реестра → models/violations_v1.onnx
  python scripts/export.py --weights best.pt --version v1 --calib-from data/dataset/images/val
  python scripts/export.py --coco                             # COCO yolov8n → device/models/yolov8n-coco.onnx (DEV-8)
  python scripts/export.py --version v1 --check               # прогон ONNX через onnxruntime на калибровочном кадре

Опсет 11 и статический вход 640×640 — то, что понимает Hailo Dataflow Compiler; после железа:
  hailomz compile yolov8n --ckpt models/violations_v1.onnx --calib-path models/calib_v1 --hw-arch hailo8l
"""

from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dgml import ML_ROOT, registry  # noqa: E402

DEVICE_DIR = ML_ROOT.parent / "device"


def add_metadata(onnx_path: Path, **props: str) -> None:
    """Дописывает metadata_props (dg_version и т. п.) — устройство показывает версию в heartbeat."""
    try:
        import onnx
    except ImportError:
        print("onnx не установлен — метаданные версии не записаны (pip install onnx)")
        return
    model = onnx.load(str(onnx_path))
    existing = {p.key for p in model.metadata_props}
    for k, v in props.items():
        if k in existing:
            for p in model.metadata_props:
                if p.key == k:
                    p.value = v
        else:
            model.metadata_props.add(key=k, value=v)
    onnx.save(model, str(onnx_path))


def export_onnx(weights: str, out: Path, imgsz: int, opset: int) -> Path:
    try:
        from ultralytics import YOLO
    except ImportError:
        print("Нет ultralytics: pip install -e \".[train]\"", file=sys.stderr)
        raise SystemExit(1) from None
    model = YOLO(weights)
    produced = Path(model.export(format="onnx", imgsz=imgsz, opset=opset, simplify=True, dynamic=False, half=False))
    out.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(produced), str(out))
    return out


def make_calib(src_dir: Path, out_dir: Path, n: int, imgsz: int) -> int:
    """N кадров из датасета (равномерно по списку) → JPG после letterbox + один .npy (N, imgsz, imgsz, 3) RGB."""
    import cv2
    import numpy as np

    from dgml.onnx_infer import letterbox
    from dgml.split import IMAGE_EXT

    images = sorted(p for p in Path(src_dir).rglob("*") if p.suffix.lower() in IMAGE_EXT)
    if not images:
        raise FileNotFoundError(f"В {src_dir} нет изображений для калибровки")
    step = max(1, len(images) // n)
    picked = images[::step][:n]
    out_dir.mkdir(parents=True, exist_ok=True)
    arrays = []
    for i, p in enumerate(picked):
        img = cv2.imread(str(p))
        if img is None:
            continue
        canvas, _, _ = letterbox(img, imgsz)
        cv2.imwrite(str(out_dir / f"calib_{i:04d}.jpg"), canvas)
        arrays.append(canvas[:, :, ::-1])
    np.save(str(out_dir.with_suffix(".npy")), np.stack(arrays).astype(np.uint8))
    return len(arrays)


def check_onnx(onnx_path: Path, image: Path | None) -> None:
    import cv2
    import numpy as np

    from dgml.onnx_infer import OnnxDetector

    det = OnnxDetector(onnx_path, conf=0.2)
    if image and image.is_file():
        img = cv2.imread(str(image))
    else:
        img = np.full((480, 640, 3), 114, dtype=np.uint8)
    dets = det.detect(img)
    best = f", лучшая: {det.names.get(dets[0].cls)} {dets[0].conf:.2f}" if dets else ""
    print(f"ONNX ок: вход {det.size}×{det.size}, классов {len(det.names)}, версия {det.version}; "
          f"детекций на кадре: {len(dets)}{best}")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Экспорт YOLOv8 → ONNX (+ калибровка для Hailo)")
    p.add_argument("--version", default=None, help="версия из реестра (веса берутся из artifacts.weights)")
    p.add_argument("--weights", default=None, help="явный путь к .pt (иначе — из реестра)")
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--opset", type=int, default=11)
    p.add_argument("--calib-from", default=None, help="папка с кадрами для калибровки (обычно images/val)")
    p.add_argument("--calib-n", type=int, default=64)
    p.add_argument("--coco", action="store_true", help="экспорт COCO yolov8n.pt для DEV-8 fallback в device/models")
    p.add_argument("--check", action="store_true", help="прогнать ONNX через onnxruntime")
    p.add_argument("--out", default=None)
    a = p.parse_args(argv)

    if a.coco:
        out = Path(a.out) if a.out else DEVICE_DIR / "models" / "yolov8n-coco.onnx"
        export_onnx(a.weights or "yolov8n.pt", out, a.imgsz, a.opset)
        add_metadata(out, dg_version="coco-yolov8n")
        print(f"COCO-модель → {out} (класс «cell phone» = телефон до своей модели)")
        if a.check:
            check_onnx(out, None)
        return 0

    reg = registry.load()
    weights = a.weights
    if a.version and not weights:
        entry = registry.get(reg, a.version)
        if entry is None:
            print(f"Версии {a.version} нет в реестре", file=sys.stderr)
            return 1
        weights = str(ML_ROOT / entry["artifacts"]["weights"])
    if not weights:
        p.error("нужен --version (из реестра) или --weights")
    version = a.version or "adhoc"
    out = Path(a.out) if a.out else ML_ROOT / "models" / f"violations_{version}.onnx"
    if not a.check or not out.is_file():
        export_onnx(weights, out, a.imgsz, a.opset)
        add_metadata(out, dg_version=registry.model_label(version), dg_task="violations")
        print(f"ONNX → {out}")
    calib_dir = None
    if a.calib_from:
        calib_dir = ML_ROOT / "models" / f"calib_{version}"
        n = make_calib(Path(a.calib_from), calib_dir, a.calib_n, a.imgsz)
        print(f"Калибровка: {n} кадров → {calib_dir}/ и {calib_dir.with_suffix('.npy')}")
    if a.version and registry.get(reg, a.version):
        registry.update(reg, a.version, artifacts={"onnx": str(out.relative_to(ML_ROOT)),
                                                   "calib": str(calib_dir.relative_to(ML_ROOT)) if calib_dir else None})
        registry.save(reg)
        print(f"Реестр обновлён: {a.version} → onnx")
    if a.check:
        first = next(iter(sorted(calib_dir.glob("*.jpg"))), None) if calib_dir else None
        check_onnx(out, first)
    print(f"Hailo (после железа): hailomz compile yolov8n --ckpt {out.name} --calib-path {calib_dir or '<калибровка>'} "
          f"--hw-arch hailo8l  → models/violations_{version}.hef, затем scripts/registry.py set-hef")
    return 0


if __name__ == "__main__":
    sys.exit(main())
