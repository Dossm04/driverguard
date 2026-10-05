"""Сборка датасета (ML-1): источники (Roboflow-экспорт, свои кадры) → единая YOLO-структура.

Что делает prepare():
- читает каждый источник (images/ + labels/ или плоская папка), переводит имена классов в наши
  (classes.ALIASES), боксы чужих классов выбрасывает, картинки без боксов оставляет как негативы;
- делит по СЕССИЯМ (split.py) — кадры одного человека/поездки не попадают и в train, и в val;
- в train добавляет grayscale-копии части картинок (аугментация под ИК-камеру);
- пишет out/data.yaml (абсолютный path — ultralytics не путается с DATASETS_DIR) и out/report.json;
- считает ворота ML-1: ≥ N изображений на класс, ≥ 20 % собственных съёмок, негативы, нет утечки.
"""

from __future__ import annotations

import hashlib
import json
import shutil
from collections import Counter, defaultdict
from dataclasses import asdict, dataclass, field
from pathlib import Path

import cv2
import yaml

from dgml.classes import CLASSES, normalize
from dgml.labels import Box, read_labels, remap, write_labels
from dgml.split import IMAGE_EXT, SPLITS, Item, leakage, session_of, split_by_session

OWN_PREFIXES = ("cabin", "own", "retrain")  # источники, считающиеся «собственной съёмкой из кабины»


@dataclass
class Check:
    name: str
    ok: bool
    detail: str


@dataclass
class Report:
    images: dict[str, int] = field(default_factory=dict)  # split → изображений (без gray-копий)
    boxes: dict[str, dict[str, int]] = field(default_factory=dict)  # split → класс → боксов
    images_with_class: dict[str, int] = field(default_factory=dict)  # класс → изображений (все части)
    negatives: int = 0
    sources: dict[str, int] = field(default_factory=dict)
    own_share: float = 0.0
    dropped_boxes: int = 0
    leakage: list[str] = field(default_factory=list)
    gray_copies: int = 0
    checks: list[Check] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return all(c.ok for c in self.checks)

    def to_dict(self) -> dict:
        return asdict(self)

    def markdown(self) -> str:
        lines = ["| Часть | Изображений | " + " | ".join(CLASSES) + " |", "|---|---|" + "---|" * len(CLASSES)]
        for s in SPLITS:
            b = self.boxes.get(s, {})
            lines.append(f"| {s} | {self.images.get(s, 0)} | " + " | ".join(str(b.get(c, 0)) for c in CLASSES) + " |")
        lines.append("")
        lines.append(
            f"Негативов: {self.negatives} · собственная съёмка: {self.own_share:.0%} · "
            f"grayscale-копий в train: {self.gray_copies} · выброшено чужих боксов: {self.dropped_boxes}"
        )
        lines.append("")
        lines.append("Ворота ML-1:")
        for c in self.checks:
            lines.append(f"- {'✅' if c.ok else '❌'} {c.name}: {c.detail}")
        return "\n".join(lines)


def source_names(root: Path) -> list[str] | None:
    """Имена классов источника: data.yaml (names: list | dict) или classes.txt / labels.txt.

    None — файла нет: считаем, что id в разметке уже наши (0 phone, 1 cigarette, …).
    """
    root = Path(root)
    for yml in (root / "data.yaml", root / "dataset.yaml"):
        if yml.is_file():
            data = yaml.safe_load(yml.read_text(encoding="utf-8")) or {}
            names = data.get("names")
            if isinstance(names, dict):
                return [str(names[k]) for k in sorted(names, key=int)]
            if isinstance(names, list):
                return [str(n) for n in names]
    for txt in (root / "classes.txt", root / "labels.txt", root / "_classes.txt"):
        if txt.is_file():
            return [ln.strip() for ln in txt.read_text(encoding="utf-8").splitlines() if ln.strip()]
    return None


def class_mapping(names: list[str] | None) -> dict[int, int | None]:
    if names is None:
        return {i: i for i in range(len(CLASSES))}
    mapping: dict[int, int | None] = {}
    for i, nm in enumerate(names):
        ours = normalize(nm)
        mapping[i] = CLASSES.index(ours) if ours else None
    return mapping


def _label_for(image: Path) -> Path | None:
    same = image.with_suffix(".txt")
    if same.is_file():
        return same
    parts = list(image.parts)
    if "images" in parts:
        idx = len(parts) - 1 - parts[::-1].index("images")
        parts[idx] = "labels"
        cand = Path(*parts).with_suffix(".txt")
        if cand.is_file():
            return cand
    return None


def discover(root: Path, source: str | None = None) -> list[Item]:
    root = Path(root)
    images = sorted(p for p in root.rglob("*") if p.suffix.lower() in IMAGE_EXT and "labels" not in p.parts)
    items = []
    for img in images:
        src, sess = session_of(img)
        items.append(Item(image=img, label=_label_for(img), source=source or src, session=sess))
    return items


def _unique_name(source: str, session: str, stem: str, used: set[str]) -> str:
    tail = stem.split("__")[-1]
    base = f"{source}__{session}__{tail}"
    name, n = base, 1
    while name in used:
        n += 1
        name = f"{base}-{n}"
    used.add(name)
    return name


def _gray_pick(name: str, ratio: float) -> bool:
    return int(hashlib.sha1(name.encode()).hexdigest()[:8], 16) % 1000 < ratio * 1000


def prepare(
    sources: list[tuple[Path, str | None]],
    out: Path,
    ratios: tuple[float, float, float] = (0.7, 0.2, 0.1),
    seed: int = 42,
    gray_ratio: float = 0.3,
    min_per_class: int = 500,
    min_own_share: float = 0.2,
    min_negative_share: float = 0.05,
    overwrite: bool = False,
) -> Report:
    out = Path(out)
    if out.exists():
        if not overwrite:
            raise FileExistsError(f"{out} уже существует — используйте --force для пересборки")
        shutil.rmtree(out)
    labeled: list[tuple[Item, list[Box]]] = []
    report = Report()
    for root, src_override in sources:
        names = source_names(root)
        mapping = class_mapping(names)
        for it in discover(root, src_override):
            rows, dropped = remap(read_labels(it.label), mapping)
            report.dropped_boxes += dropped
            labeled.append((it, rows))
    if not labeled:
        raise ValueError("В источниках нет изображений")

    splits = split_by_session([it for it, _ in labeled], ratios=ratios, seed=seed)
    rows_by_image = {it.image: rows for it, rows in labeled}
    report.leakage = leakage(splits)
    used: set[str] = set()
    with_class: dict[str, set[Path]] = defaultdict(set)
    src_counter: Counter[str] = Counter()
    for split_name in SPLITS:
        img_dir, lbl_dir = out / "images" / split_name, out / "labels" / split_name
        img_dir.mkdir(parents=True, exist_ok=True)
        lbl_dir.mkdir(parents=True, exist_ok=True)
        boxes: Counter[str] = Counter()
        for it in splits[split_name]:
            rows = rows_by_image[it.image]
            name = _unique_name(it.source, it.session, it.image.stem, used)
            shutil.copy2(it.image, img_dir / f"{name}{it.image.suffix.lower()}")
            write_labels(lbl_dir / f"{name}.txt", rows)
            src_counter[it.source] += 1
            if not rows:
                report.negatives += 1
            for cls, *_ in rows:
                boxes[CLASSES[cls]] += 1
                with_class[CLASSES[cls]].add(it.image)
            if split_name == "train" and gray_ratio > 0 and _gray_pick(name, gray_ratio):
                img = cv2.imread(str(it.image))
                if img is not None:
                    gray = cv2.cvtColor(cv2.cvtColor(img, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
                    cv2.imwrite(str(img_dir / f"{name}_gray.jpg"), gray)
                    write_labels(lbl_dir / f"{name}_gray.txt", rows)
                    report.gray_copies += 1
        report.images[split_name] = len(splits[split_name])
        report.boxes[split_name] = {c: boxes.get(c, 0) for c in CLASSES}

    total = len(labeled)
    report.sources = dict(src_counter)
    report.images_with_class = {c: len(with_class[c]) for c in CLASSES}
    own = sum(n for s, n in src_counter.items() if s.lower().startswith(OWN_PREFIXES))
    report.own_share = own / total if total else 0.0

    for c in CLASSES:
        n = report.images_with_class[c]
        report.checks.append(Check(f"изображений с классом {c}", n >= min_per_class, f"{n} (нужно ≥ {min_per_class})"))
    report.checks.append(
        Check("собственная съёмка из кабины", report.own_share >= min_own_share,
              f"{report.own_share:.0%} (нужно ≥ {min_own_share:.0%}; источники cabin*/own*/retrain*)")
    )
    neg_share = report.negatives / total if total else 0.0
    report.checks.append(
        Check("негативы (кадры без нарушений)", neg_share >= min_negative_share,
              f"{report.negatives} = {neg_share:.0%} (нужно ≥ {min_negative_share:.0%})")
    )
    report.checks.append(Check("утечка сессий между частями", not report.leakage, ", ".join(report.leakage) or "нет"))
    report.checks.append(
        Check("val и test не пустые", report.images["val"] > 0 and report.images["test"] > 0,
              f"val {report.images['val']}, test {report.images['test']}")
    )

    data_yaml = {
        "path": str(out.resolve()),
        "train": "images/train",
        "val": "images/val",
        "test": "images/test",
        "names": dict(enumerate(CLASSES)),
    }
    (out / "data.yaml").write_text(yaml.safe_dump(data_yaml, allow_unicode=True, sort_keys=False), encoding="utf-8")
    (out / "report.json").write_text(json.dumps(report.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8")
    return report
