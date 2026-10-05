"""Сплит датасета по сессиям (ML-1): кадры одного человека/поездки не расходятся по train/val/test."""

from __future__ import annotations

import hashlib
from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path

IMAGE_EXT = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
SPLITS = ("train", "val", "test")


@dataclass(frozen=True)
class Item:
    image: Path
    label: Path | None
    source: str
    session: str


def session_of(image: Path) -> tuple[str, str]:
    """(источник, сессия) из имени `source__session__frame.jpg`; иначе — имя папки как сессия."""
    parts = image.stem.split("__")
    if len(parts) >= 3:
        return parts[0], parts[1]
    folder = image.parent.name
    if folder in ("images", "train", "val", "test"):
        folder = image.parent.parent.name
    return folder, folder


def _stable_key(session: str, seed: int) -> str:
    return hashlib.sha1(f"{seed}:{session}".encode()).hexdigest()


def split_by_session(
    items: list[Item], ratios: tuple[float, float, float] = (0.7, 0.2, 0.1), seed: int = 42
) -> dict[str, list[Item]]:
    """Жадный сплит: сессии (от больших к меньшим) кладутся в ту часть, что дальше всех от своей квоты.

    Детерминирован (порядок среди равных по размеру — по хэшу от seed), поэтому повторный
    prepare на тех же данных даёт тот же сплит — версии моделей сравнимы между собой.
    """
    if abs(sum(ratios) - 1.0) > 1e-6:
        raise ValueError("Сумма долей train/val/test должна быть 1")
    by_session: dict[str, list[Item]] = defaultdict(list)
    for it in items:
        by_session[it.session].append(it)
    order = sorted(by_session, key=lambda s: (-len(by_session[s]), _stable_key(s, seed)))
    total = len(items)
    out: dict[str, list[Item]] = {s: [] for s in SPLITS}
    for session in order:
        # у какой части наибольший дефицит относительно квоты
        deficits = [(ratios[i] * total - len(out[s]), i) for i, s in enumerate(SPLITS) if ratios[i] > 0]
        _, idx = max(deficits)
        out[SPLITS[idx]].extend(by_session[session])
    return out


def leakage(splits: dict[str, list[Item]]) -> list[str]:
    """Сессии, оказавшиеся больше чем в одной части (должно быть пусто)."""
    seen: dict[str, set[str]] = defaultdict(set)
    for name, items in splits.items():
        for it in items:
            seen[it.session].add(name)
    return sorted(s for s, parts in seen.items() if len(parts) > 1)
