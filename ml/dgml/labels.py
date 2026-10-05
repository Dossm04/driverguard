"""Разметка в формате YOLO: `cls cx cy w h` (нормировано 0..1), одна строка на бокс."""

from __future__ import annotations

from pathlib import Path

Box = tuple[int, float, float, float, float]


def read_labels(path: Path | None) -> list[Box]:
    if path is None or not Path(path).is_file():
        return []
    rows: list[Box] = []
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        parts = line.split()
        if len(parts) < 5:
            continue
        try:
            cls = int(float(parts[0]))
            cx, cy, w, h = (float(v) for v in parts[1:5])
        except ValueError:
            continue
        if w <= 0 or h <= 0:
            continue
        rows.append((cls, cx, cy, w, h))
    return rows


def write_labels(path: Path, rows: list[Box]) -> None:
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        "".join(f"{c} {cx:.6f} {cy:.6f} {w:.6f} {h:.6f}\n" for c, cx, cy, w, h in rows), encoding="utf-8"
    )


def remap(rows: list[Box], mapping: dict[int, int | None]) -> tuple[list[Box], int]:
    """Переводит id классов источника в наши; боксы классов, которых у нас нет, выбрасываются.

    Возвращает (боксы, сколько выброшено).
    """
    out: list[Box] = []
    dropped = 0
    for cls, cx, cy, w, h in rows:
        new = mapping.get(cls)
        if new is None:
            dropped += 1
            continue
        out.append((new, cx, cy, w, h))
    return out, dropped
