#!/usr/bin/env python
"""Сборка датасета (ML-1): источники → data/dataset (YOLO), сплит по сессиям, grayscale, отчёт с воротами.

  python scripts/prepare_dataset.py data/raw/cabin data/raw/roboflow-phone:phone-rf --out data/dataset --force
  python scripts/prepare_dataset.py --synthetic --out data/synthetic --force     # smoke без реальных данных

Источник: папка с images/ + labels/ (Roboflow-экспорт YOLO) или плоская папка jpg+txt.
`путь:имя` задаёт имя источника (иначе берётся из имён файлов source__session__кадр или из папки).
Имена классов источника читаются из его data.yaml / classes.txt и переводятся в наши (dgml/classes.py).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dgml.dataset import prepare  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Сборка YOLO-датасета с проверкой ворот ML-1")
    p.add_argument("sources", nargs="*", help="папки источников: путь или путь:имя")
    p.add_argument("--out", default="data/dataset")
    p.add_argument("--ratios", default="0.7,0.2,0.1", help="доли train,val,test")
    p.add_argument("--seed", type=int, default=42)
    p.add_argument("--gray-ratio", type=float, default=0.3, help="доля grayscale-копий в train (ИК)")
    p.add_argument("--min-per-class", type=int, default=500)
    p.add_argument("--min-own-share", type=float, default=0.2)
    p.add_argument("--force", action="store_true", help="пересобрать, если --out существует")
    p.add_argument("--synthetic", action="store_true", help="сгенерировать синтетику вместо источников")
    p.add_argument("--no-gate", action="store_true", help="не возвращать код 2 при непройденных воротах")
    a = p.parse_args(argv)

    sources: list[tuple[Path, str | None]] = []
    if a.synthetic:
        from dgml.synthetic import make_dataset

        raw = Path(a.out).parent / (Path(a.out).name + "_raw")
        if raw.exists():
            import shutil

            shutil.rmtree(raw)
        n = make_dataset(raw, sessions=8, per_session=24, seed=a.seed)
        print(f"Синтетика: {n} изображений → {raw}")
        sources.append((raw, None))
        a.min_per_class, a.min_own_share = min(a.min_per_class, 20), a.min_own_share
    for spec in a.sources:
        path, _, name = spec.partition(":")
        sources.append((Path(path), name or None))
    if not sources:
        p.error("укажите хотя бы один источник или --synthetic")
    ratios = tuple(float(v) for v in a.ratios.split(","))
    if len(ratios) != 3:
        p.error("--ratios: три числа через запятую")
    try:
        report = prepare(sources, Path(a.out), ratios=ratios, seed=a.seed, gray_ratio=a.gray_ratio,
                         min_per_class=a.min_per_class, min_own_share=a.min_own_share, overwrite=a.force)
    except (FileExistsError, ValueError) as exc:
        print(f"Ошибка: {exc}", file=sys.stderr)
        return 1
    print(report.markdown())
    print(f"\ndata.yaml и report.json → {Path(a.out).resolve()}")
    if not report.passed and not a.no_gate:
        print("Ворота ML-1 не пройдены — датасет нужно дополнить (см. ml/README.md).", file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
