#!/usr/bin/env python
"""Обучение YOLOv8n (ML-2) с записью в реестр версий (ML-4) и воротами выпуска mAP@50 ≥ 0.85.

  python scripts/train.py --data data/dataset/data.yaml --epochs 100 --version v1
  python scripts/train.py --smoke            # 1 эпоха на синтетике, CPU — проверка конвейера

Colab: notebooks/DriverGuard_YOLOv8_Colab.ipynb вызывает этот же скрипт. Нужен extra `train`:
  pip install -e ".[train]"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dgml import ML_ROOT, registry  # noqa: E402
from dgml.metrics import GATE_MAP50, best_epoch, gate, per_class_markdown, summarize_val  # noqa: E402

AUG = dict(hsv_h=0.015, hsv_s=0.7, hsv_v=0.5, degrees=5.0, translate=0.1, scale=0.4, fliplr=0.5, mosaic=1.0)


def _import_yolo():
    try:
        from ultralytics import YOLO
    except ImportError:
        print("Нет ultralytics: pip install -e \".[train]\" (в Colab — !pip install ultralytics)", file=sys.stderr)
        raise SystemExit(1) from None
    return YOLO


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Обучение YOLOv8 для детектора нарушений")
    p.add_argument("--data", default="data/dataset/data.yaml")
    p.add_argument("--model", default="yolov8n.pt", help="базовые веса (yolov8n.pt) или свои для дообучения")
    p.add_argument("--epochs", type=int, default=100)
    p.add_argument("--imgsz", type=int, default=640)
    p.add_argument("--batch", type=int, default=16)
    p.add_argument("--device", default=None, help="cuda:0 | cpu | пусто — авто")
    p.add_argument("--workers", type=int, default=4)
    p.add_argument("--version", default=None, help="v1, v2, … (по умолчанию следующая в реестре)")
    p.add_argument("--project", default="runs")
    p.add_argument("--notes", default="")
    p.add_argument("--gate", type=float, default=GATE_MAP50)
    p.add_argument("--no-gate", action="store_true", help="не возвращать код 2, если ворота не пройдены")
    p.add_argument("--no-registry", action="store_true", help="не писать в models/registry.json")
    p.add_argument("--smoke", action="store_true", help="синтетика, 1 эпоха, imgsz 160 — проверка конвейера")
    a = p.parse_args(argv)

    if a.smoke:
        from dgml.dataset import prepare
        from dgml.synthetic import make_dataset

        raw, out = ML_ROOT / "data" / "synthetic_raw", ML_ROOT / "data" / "synthetic"
        if not (out / "data.yaml").is_file():
            make_dataset(raw, sessions=8, per_session=24)
            prepare([(raw, None)], out, overwrite=True, min_per_class=20)
        a.data, a.epochs, a.imgsz, a.batch = str(out / "data.yaml"), max(1, min(a.epochs, 3)), 160, 8
        a.workers, a.notes = 0, (a.notes or "smoke: синтетика")
        a.version = a.version or "smoke"
        a.no_registry = a.no_registry or a.version == "smoke"
        a.no_gate = True  # smoke проверяет конвейер, а не качество

    data = Path(a.data)
    if not data.is_file():
        print(f"Нет {data}: сначала scripts/prepare_dataset.py", file=sys.stderr)
        return 1
    reg = registry.load()
    version = a.version or registry.next_version(reg)
    if not a.no_registry and registry.get(reg, version):
        print(f"Версия {version} уже есть в реестре — укажите другую (--version)", file=sys.stderr)
        return 1

    YOLO = _import_yolo()
    model = YOLO(a.model)
    train_kw = dict(
        data=str(data.resolve()), epochs=a.epochs, imgsz=a.imgsz, batch=a.batch, workers=a.workers,
        project=str(ML_ROOT / a.project), name=version, exist_ok=True, plots=True, verbose=False, **AUG,
    )
    if a.device:
        train_kw["device"] = a.device
    print(f"Обучение {version}: {a.model} · {data} · {a.epochs} эпох · imgsz {a.imgsz}")
    model.train(**train_kw)
    run_dir = ML_ROOT / a.project / version
    weights = run_dir / "weights" / "best.pt"
    metrics = best_epoch(run_dir / "results.csv")
    try:
        val = YOLO(str(weights)).val(data=str(data.resolve()), imgsz=a.imgsz, batch=a.batch, plots=False,
                                     project=str(run_dir), name="val", exist_ok=True, verbose=False,
                                     workers=a.workers, **({"device": a.device} if a.device else {}))
        summary = summarize_val(val, val.names)
        metrics.update({k: summary[k] for k in ("map50", "map50_95", "precision", "recall")})
        per_class = summary["per_class"]
    except Exception as exc:  # noqa: BLE001 — валидация best.pt не должна ронять запись результата
        print(f"Повторная валидация best.pt не удалась ({exc}); метрики — из results.csv")
        per_class = []
    passed, text = gate(metrics, a.gate)
    print(f"\n{version}: mAP@50 {metrics.get('map50', 0):.3f} · mAP@50-95 {metrics.get('map50_95', 0):.3f} · "
          f"P {metrics.get('precision', 0):.3f} · R {metrics.get('recall', 0):.3f}")
    if per_class:
        print(per_class_markdown(per_class))
    print(text)

    dataset_dir = data.parent
    entry = {
        "version": version,
        "task": "violations",
        "base": a.model,
        "dataset": {
            "path": str(dataset_dir),
            "fingerprint": registry.dataset_fingerprint(dataset_dir),
            **_dataset_counts(dataset_dir),
        },
        "train": {"epochs": a.epochs, "imgsz": a.imgsz, "batch": a.batch, "aug": AUG},
        "metrics": {**metrics, "per_class": per_class},
        "gate": {"threshold": a.gate, "passed": passed},
        "artifacts": {"weights": str(weights.relative_to(ML_ROOT)), "onnx": None, "hef": None},
        "git": registry.git_commit(),
        "notes": a.notes,
    }
    (run_dir / "registry_entry.json").write_text(json.dumps(entry, ensure_ascii=False, indent=2), encoding="utf-8")
    if not a.no_registry:
        registry.add(reg, entry)
        registry.save(reg)
        print(f"Реестр: {registry.REGISTRY_PATH.relative_to(ML_ROOT)} ← {version}")
    print(f"Веса: {weights}")
    return 0 if (passed or a.no_gate) else 2


def _dataset_counts(dataset_dir: Path) -> dict:
    report = dataset_dir / "report.json"
    if report.is_file():
        data = json.loads(report.read_text(encoding="utf-8"))
        return {"images": data.get("images"), "boxes": data.get("boxes")}
    return {}


if __name__ == "__main__":
    sys.exit(main())
