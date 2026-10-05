"""Validate and remap a Roboflow YOLO export without mixing its held-out splits."""
from __future__ import annotations
from collections import Counter, defaultdict
from pathlib import Path
import hashlib
import json
import math
import re
import shutil
import time
import yaml
from PIL import Image

CLASSES = ["phone", "cigarette", "seatbelt_on", "seatbelt_off"]
ALIASES = {"phone": 0, "cell phone": 0, "mobile phone": 0,
           "cigarette": 1, "seatbelt": 2, "seat belt": 2, "seatbelt on": 2,
           "seatbelt off": 3, "no seatbelt": 3, "no seat belt": 3}
SOURCE = {"title": "PFE", "author": "PFE (Roboflow workspace pfe-lcrvh)",
          "url": "https://universe.roboflow.com/pfe-lcrvh/pfe-scklc",
          "version": 1, "license_as_listed": "CC BY 4.0",
          "changes": "Four-class remapping; audited exclusion of three malformed PFE v1 labels; duplicate quarantine; source splits preserved."}

# These three names are from the user's Colab validation report, not a blanket
# permission to ignore malformed annotations in arbitrary datasets.
KNOWN_PFE_V1_INVALID_LABELS = frozenset({
    "train/labels/2183_jpg.rf.0631bd6ee34b77570ec9d796c14783d0.txt",
    "train/labels/2183_jpg.rf.0641f1910972e6ae139d5dc5f43e22e5.txt",
    "train/labels/2183_jpg.rf.ee7e9cef2ffa42c44592cfcbb9a1168d.txt",
})

def sha256(path):
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for part in iter(lambda: f.read(1024 * 1024), b""):
            h.update(part)
    return h.hexdigest()

def normalize(name):
    return " ".join(str(name).lower().replace("_", " ").replace("-", " ").split())

def parse_labels(path, mapping):
    if not path.is_file():
        raise ValueError(f"Missing label file (not assumed to be a negative): {path}")
    output, ignored = [], 0
    for number, line in enumerate(path.read_text(encoding="utf-8-sig").splitlines(), 1):
        if not line.strip():
            continue
        parts = line.split()
        if len(parts) != 5:
            raise ValueError(f"Expected detection boxes, 5 fields: {path}:{number}")
        values = list(map(float, parts))
        cls, x, y, w, h = values
        if not all(map(math.isfinite, values)) or cls != int(cls) or int(cls) not in mapping:
            raise ValueError(f"Invalid class/number: {path}:{number}")
        if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1):
            raise ValueError(f"Invalid normalized box: {path}:{number}")
        if min(x-w/2, y-h/2) < -0.011 or max(x+w/2, y+h/2) > 1.011:
            raise ValueError(f"Box outside image: {path}:{number}")
        target = mapping[int(cls)]
        if target is None:
            ignored += 1
        else:
            output.append((target, x, y, w, h))
    return output, ignored

def source_group(stem):
    # Roboflow augmentations retain the pre-.rf. name. This is not a driver ID.
    return re.split(r"[._]rf[._]", stem, maxsplit=1, flags=re.I)[0]

def prepare_dataset(raw, output, min_images_per_class=1, *, allowed_invalid_labels=(), progress=None):
    raw, output = Path(raw).resolve(), Path(output).resolve()
    if output.exists():
        raise FileExistsError(f"Output already exists; choose a new folder: {output}")
    metadata = yaml.safe_load((raw / "data.yaml").read_text(encoding="utf-8-sig"))
    names = metadata["names"]
    names = dict(enumerate(names)) if isinstance(names, list) else {int(k): v for k, v in names.items()}
    mapping = {k: ALIASES.get(normalize(v)) for k, v in names.items()}
    if set(mapping.values()) - {None} != set(range(4)):
        raise ValueError(f"Source must contain all four classes. Found: {names}")
    allowed_invalid_labels = set(allowed_invalid_labels)
    rows, errors, invalid_files = [], [], []
    started = time.monotonic()
    def report(message):
        if progress is not None:
            progress(message)
    for split, folder in [("train", "train"), ("val", "valid" if (raw / "valid").is_dir() else "val"), ("test", "test")]:
        images = sorted(p for p in (raw / folder / "images").rglob("*") if p.suffix.lower() in {".jpg", ".jpeg", ".png", ".webp"})
        if not images:
            raise ValueError(f"No images in source {split}; do not create a random test set.")
        report(f"Проверка {split}: {len(images)} изображений")
        for index, image in enumerate(images, 1):
            label = raw / folder / "labels" / image.relative_to(raw / folder / "images").with_suffix(".txt")
            try:
                invalid = None
                try:
                    boxes, ignored = parse_labels(label, mapping)
                except ValueError as exc:
                    relative_label = label.relative_to(raw).as_posix()
                    if relative_label not in allowed_invalid_labels or not str(exc).startswith("Expected detection boxes, 5 fields:"):
                        raise
                    invalid = {"image": image.relative_to(raw).as_posix(),
                               "label": relative_label, "split": split,
                               "reason": "invalid_detection_label", "error": str(exc),
                               "label_sha256": sha256(label),
                               "line_field_counts": [len(line.split()) for line in label.read_text(encoding="utf-8-sig").splitlines() if line.strip()]}
                    boxes, ignored = [], 0
                    report(f"Исключён повреждённый пример: {relative_label}")
                with Image.open(image) as im:
                    im = im.convert("RGB")
                    pixels = hashlib.sha256(str(im.size).encode() + im.tobytes()).hexdigest()
                rows.append(dict(split=split, image=image, label=label, sha=sha256(image),
                                 pixels=pixels, group=source_group(image.stem), boxes=boxes, ignored=ignored, invalid=invalid))
                if invalid:
                    invalid_files.append(invalid)
            except (ValueError, OSError) as exc:
                errors.append(str(exc))
            if index % 250 == 0 or index == len(images):
                report(f"{split}: {index}/{len(images)} ({index/len(images):.0%}); прошло {time.monotonic()-started:.0f} с")
    if errors:
        raise ValueError(f"{len(errors)} invalid files. First errors:\n" + "\n".join(errors[:12]))
    # Quarantine every member of a group touching more than one split.
    lookup = {kind: defaultdict(set) for kind in ("sha", "pixels", "group")}
    invalid_keys = {kind: set() for kind in lookup}
    for row in rows:
        for kind in lookup:
            lookup[kind][row[kind]].add(row["split"])
            if row["invalid"]:
                invalid_keys[kind].add(row[kind])
    quarantined, kept, seen = [], [], set()
    for row in rows:
        invalid_related = next((kind for kind in lookup if row[kind] in invalid_keys[kind]), None)
        reason = next((kind for kind in lookup if len(lookup[kind][row[kind]]) > 1), None)
        if row["invalid"]:
            quarantined.append(row["invalid"])
        elif invalid_related:
            quarantined.append({"image": str(row["image"].relative_to(raw)), "reason": "related_to_invalid_" + invalid_related})
        elif reason:
            quarantined.append({"image": str(row["image"].relative_to(raw)), "reason": "cross_split_" + reason})
        elif (row["split"], row["pixels"]) in seen:
            quarantined.append({"image": str(row["image"].relative_to(raw)), "reason": "within_split_duplicate"})
        else:
            seen.add((row["split"], row["pixels"]))
            kept.append(row)
    counts = {}
    for split in ("train", "val", "test"):
        items = [r for r in kept if r["split"] == split]
        per_image = Counter(c for r in items for c in {b[0] for b in r["boxes"]})
        counts[split] = {"images": len(items), "images_per_class": {n: per_image[i] for i, n in enumerate(CLASSES)},
                         "boxes_per_class": dict(Counter(CLASSES[b[0]] for r in items for b in r["boxes"])),
                         "empty_target_labels": sum(not r["boxes"] for r in items)}
        if any(per_image[c] < min_images_per_class for c in range(4)):
            raise ValueError(f"Insufficient class coverage after quarantine: {split}: {counts[split]}")
    output.mkdir(parents=True)
    report(f"Проверка завершена. Запись {len(kept)} изображений; исключено {len(quarantined)}")
    manifest = []
    for index, row in enumerate(kept, 1):
        stem = hashlib.sha256(str(row["image"].relative_to(raw)).encode()).hexdigest()[:24]
        image = output / row["split"] / "images" / (stem + row["image"].suffix.lower())
        label = output / row["split"] / "labels" / (stem + ".txt")
        image.parent.mkdir(parents=True, exist_ok=True)
        label.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(row["image"], image)
        label.write_text("\n".join(f"{c} {x:.8f} {y:.8f} {w:.8f} {h:.8f}" for c, x, y, w, h in row["boxes"]), encoding="utf-8")
        manifest.append({"split": row["split"], "source": str(row["image"].relative_to(raw)), "image": str(image.relative_to(output)), "sha256": row["sha"], "group": row["group"]})
        if index % 500 == 0 or index == len(kept):
            report(f"Запись: {index}/{len(kept)} ({index/len(kept):.0%})")
    (output / "data.yaml").write_text(yaml.safe_dump({"path": str(output), "train": "train/images", "val": "val/images", "test": "test/images", "names": dict(enumerate(CLASSES))}, sort_keys=False), encoding="utf-8")
    audit = {"source": SOURCE, "source_classes": names, "counts": counts, "quarantined": quarantined,
             "invalid_files": invalid_files, "allowed_invalid_labels": sorted(allowed_invalid_labels),
             "manifest": manifest, "discarded_non_target_boxes": sum(r["ignored"] for r in rows),
             "driver_independent_split_verified": False,
             "annotation_completeness_verified": False,
             "limitations": ["Source split has no verified driver/session IDs.", "Exact/pixel duplicates and common Roboflow name groups checked; adjacent frames may remain.", "Dropping face/food assumes four target classes were fully annotated; inspect contact sheet.", "An empty target label is not a verified real-world negative."]}
    (output / "dataset_audit.json").write_text(json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    report(f"Готово за {time.monotonic()-started:.0f} с. Отчёт: {output / 'dataset_audit.json'}")
    return audit
