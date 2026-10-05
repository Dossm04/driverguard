"""Метрики и ворота выпуска (ML-2): mAP@50 ≥ 0.85 на валидации, таблицы per-class и confusion matrix."""

from __future__ import annotations

import csv
from pathlib import Path

GATE_MAP50 = 0.85

_RESULT_KEYS = {
    "epoch": "epoch",
    "metrics/precision(B)": "precision",
    "metrics/recall(B)": "recall",
    "metrics/mAP50(B)": "map50",
    "metrics/mAP50-95(B)": "map50_95",
}


def read_results_csv(path: Path) -> dict[str, float]:
    """Последняя строка results.csv ultralytics → {epoch, precision, recall, map50, map50_95}."""
    with Path(path).open(encoding="utf-8") as f:
        rows = [{k.strip(): v.strip() for k, v in row.items()} for row in csv.DictReader(f)]
    if not rows:
        raise ValueError(f"{path}: пустой results.csv")
    last = rows[-1]
    out: dict[str, float] = {}
    for src, dst in _RESULT_KEYS.items():
        if src in last and last[src] != "":
            out[dst] = float(last[src])
    return out


def best_epoch(path: Path) -> dict[str, float]:
    """Строка results.csv с максимальным mAP50 (best.pt ultralytics выбирает по fitness ≈ этому же)."""
    with Path(path).open(encoding="utf-8") as f:
        rows = [{k.strip(): v.strip() for k, v in row.items()} for row in csv.DictReader(f)]
    best = max(rows, key=lambda r: float(r.get("metrics/mAP50(B)", 0) or 0))
    return {dst: float(best[src]) for src, dst in _RESULT_KEYS.items() if src in best and best[src] != ""}


def gate(metrics: dict, threshold: float = GATE_MAP50) -> tuple[bool, str]:
    map50 = float(metrics.get("map50", 0.0) or 0.0)
    ok = map50 >= threshold
    verdict = "выпуск разрешён" if ok else "ворота НЕ пройдены"
    return ok, f"mAP@50 = {map50:.3f} {'≥' if ok else '<'} {threshold:.2f} — {verdict}"


def per_class_markdown(rows: list[dict]) -> str:
    lines = ["| Класс | Precision | Recall | AP@50 |", "|---|---|---|---|"]
    for r in rows:
        lines.append(f"| {r['name']} | {r['precision']:.3f} | {r['recall']:.3f} | {r['ap50']:.3f} |")
    return "\n".join(lines)


def confusion_markdown(matrix: list[list[float]], names: list[str]) -> str:
    """Матрица ultralytics: строки — предсказано, столбцы — истина; последний индекс — фон."""
    labels = list(names) + ["фон"]
    n = len(labels)
    lines = ["| предсказано \\ истина | " + " | ".join(labels) + " |", "|---|" + "---|" * n]
    for i in range(min(n, len(matrix))):
        row = matrix[i]
        lines.append(f"| {labels[i]} | " + " | ".join(str(int(round(row[j]))) for j in range(min(n, len(row)))) + " |")
    return "\n".join(lines)


def _as_list(value) -> list:
    """numpy-массив/список/None → список (без `or []`, который на массиве падает)."""
    if value is None:
        return []
    try:
        return list(value)
    except TypeError:
        return []


def summarize_val(res, names: dict | list) -> dict:
    """DetMetrics ultralytics → словарь для реестра (устойчиво к отсутствию полей)."""
    box = getattr(res, "box", None)
    out: dict = {
        "map50": float(getattr(box, "map50", 0.0)),
        "map50_95": float(getattr(box, "map", 0.0)),
        "precision": float(getattr(box, "mp", 0.0)),
        "recall": float(getattr(box, "mr", 0.0)),
        "per_class": [],
    }
    name_list = [names[k] for k in sorted(names)] if isinstance(names, dict) else list(names)
    idx = _as_list(getattr(box, "ap_class_index", None))
    p, r, ap50 = (_as_list(getattr(box, a, None)) for a in ("p", "r", "ap50"))
    for k, ci in enumerate(idx):
        out["per_class"].append(
            {
                "name": name_list[int(ci)] if int(ci) < len(name_list) else str(ci),
                "precision": float(p[k]) if k < len(p) else 0.0,
                "recall": float(r[k]) if k < len(r) else 0.0,
                "ap50": float(ap50[k]) if k < len(ap50) else 0.0,
            }
        )
    cm = getattr(getattr(res, "confusion_matrix", None), "matrix", None)
    if cm is not None:
        out["confusion"] = [[float(v) for v in row] for row in cm.tolist()]
    return out
