"""Сборка датасета из синтетики: сплит, grayscale, ворота; нарезка кадров из видео."""

from pathlib import Path

import cv2
import numpy as np
import pytest
import yaml

from dgml.classes import CLASSES
from dgml.dataset import class_mapping, discover, prepare, source_names
from dgml.frames import dhash, extract_frames, hamming, safe_token
from dgml.synthetic import make_dataset


@pytest.fixture(scope="module")
def raw(tmp_path_factory) -> Path:
    root = tmp_path_factory.mktemp("raw")
    n = make_dataset(root, sessions=6, per_session=14, seed=3)
    assert n == 84
    return root


def test_source_names_and_mapping(raw: Path, tmp_path: Path):
    assert source_names(raw) == CLASSES
    assert class_mapping(None) == {0: 0, 1: 1, 2: 2, 3: 3}
    rf = tmp_path / "rf"
    rf.mkdir()
    (rf / "data.yaml").write_text(yaml.safe_dump({"names": ["person", "cell phone", "no_seatbelt"]}), encoding="utf-8")
    assert class_mapping(source_names(rf)) == {0: None, 1: 0, 2: 3}
    items = discover(raw)
    assert len(items) == 84 and all(it.label and it.label.is_file() for it in items)
    assert {it.source for it in items} == {"cabin", "roboflow"}


def test_prepare_builds_yolo_layout_with_gates(raw: Path, tmp_path: Path):
    out = tmp_path / "dataset"
    report = prepare([(raw, None)], out, min_per_class=10, gray_ratio=0.5, overwrite=False)
    assert report.leakage == []
    assert sum(report.images.values()) == 84 and report.images["val"] > 0 and report.images["test"] > 0
    assert report.negatives > 0 and 0.4 <= report.own_share <= 0.6
    assert report.gray_copies > 0
    for c in CLASSES:
        assert report.images_with_class[c] >= 10
    assert report.passed, [c for c in report.checks if not c.ok]
    data = yaml.safe_load((out / "data.yaml").read_text(encoding="utf-8"))
    assert Path(data["path"]).is_absolute() and data["names"][3] == "seatbelt_off"
    imgs = list((out / "images" / "train").glob("*.jpg"))
    labels = list((out / "labels" / "train").glob("*.txt"))
    assert len(imgs) == len(labels) == report.images["train"] + report.gray_copies
    gray = next(p for p in imgs if p.stem.endswith("_gray"))
    g = cv2.imread(str(gray))
    assert np.array_equal(g[:, :, 0], g[:, :, 1])  # действительно серый
    assert (out / "report.json").is_file()
    assert "Ворота ML-1" in report.markdown()
    with pytest.raises(FileExistsError):
        prepare([(raw, None)], out, overwrite=False)


def test_prepare_gate_fails_on_small_dataset(raw: Path, tmp_path: Path):
    report = prepare([(raw, "roboflow")], tmp_path / "d2", min_per_class=500, overwrite=True)
    failed = {c.name for c in report.checks if not c.ok}
    assert any("phone" in n for n in failed)
    assert "собственная съёмка из кабины" in failed  # всё переименовано в roboflow → 0 % своих
    assert not report.passed


def test_dhash_and_extract_frames(tmp_path: Path):
    a = np.zeros((120, 160, 3), dtype=np.uint8)
    cv2.rectangle(a, (10, 10), (80, 100), (255, 255, 255), -1)
    b = a.copy()
    cv2.circle(b, (120, 60), 30, (200, 200, 200), -1)
    assert hamming(dhash(a), dhash(a)) == 0
    assert hamming(dhash(a), dhash(b)) >= 3
    video = tmp_path / "clip.avi"
    w = cv2.VideoWriter(str(video), cv2.VideoWriter_fourcc(*"MJPG"), 10.0, (160, 120))
    for i in range(40):
        frame = a.copy() if i < 20 else b.copy()
        cv2.putText(frame, str(i), (5, 115), cv2.FONT_HERSHEY_SIMPLEX, 0.4, (128, 128, 128), 1)
        w.write(frame)
    w.release()
    out = tmp_path / "frames"
    n = extract_frames(video, out, session="Иванов 10.09", source="cabin", every_ms=500, min_hamming=4)
    files = sorted(out.glob("*.jpg"))
    assert n == len(files) == 2  # 8 кандидатов (каждые 5 кадров), но только две непохожие сцены
    assert files[0].name == "cabin__x__000000.jpg" or files[0].name.startswith("cabin__")
    n_all = extract_frames(video, tmp_path / "all", session="s1", every_ms=500, min_hamming=0)
    assert n_all == 8
    assert safe_token("a b__c") == "a-b-c"
