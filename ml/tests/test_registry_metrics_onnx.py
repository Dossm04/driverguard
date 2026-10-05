"""Реестр версий (ML-4), метрики и ворота (ML-2), декодирование выхода YOLOv8 без torch."""

from pathlib import Path

import numpy as np
import pytest

from dgml import registry
from dgml.metrics import best_epoch, confusion_markdown, gate, per_class_markdown, read_results_csv
from dgml.onnx_infer import decode, letterbox, nms, parse_names, preprocess

RESULTS = """epoch, train/box_loss, metrics/precision(B), metrics/recall(B), metrics/mAP50(B), metrics/mAP50-95(B)
1,  1.2,  0.5,  0.4,  0.61,  0.30
2,  1.0,  0.7,  0.6,  0.88,  0.52
3,  0.9,  0.69,  0.62,  0.86,  0.55
"""


def test_registry_versions_update_latest(tmp_path: Path):
    path = tmp_path / "registry.json"
    reg = registry.load(path)
    assert reg == {"models": []} and registry.next_version(reg) == "v1"
    e1 = registry.add(reg, {"metrics": {"map50": 0.7}, "gate": {"passed": False}})
    e2 = registry.add(reg, {"metrics": {"map50": 0.9}, "gate": {"passed": True}, "artifacts": {"onnx": None}})
    assert e1["version"] == "v1" and e2["version"] == "v2" and e2["created"]
    with pytest.raises(ValueError):
        registry.add(reg, {"version": "v2"})
    with pytest.raises(ValueError):
        registry.add(reg, {"version": "release-1"})
    registry.update(reg, "v2", artifacts={"onnx": "models/violations_v2.onnx"}, notes="ок")
    assert registry.get(reg, "v2")["artifacts"] == {"onnx": "models/violations_v2.onnx"}
    registry.save(reg, path)
    again = registry.load(path)
    assert registry.latest(again)["version"] == "v2"
    assert registry.latest(again, passed_only=True)["version"] == "v2"
    registry.add(again, {"gate": {"passed": False}})
    assert registry.latest(again)["version"] == "v3" and registry.latest(again, passed_only=True)["version"] == "v2"
    with pytest.raises(KeyError):
        registry.update(again, "v9", notes="x")


CONFIG = """# комментарий
device:
  serial: DG-0001
  model_version: mediapipe-face-landmarker-1   # старое
  profile: highway

camera:
  width: 640
"""


def test_set_yaml_value_keeps_comments_and_adds_missing():
    text = registry.set_yaml_value(CONFIG, "device", "model_version", "violations-v1")
    assert "  model_version: violations-v1   # старое\n" in text
    assert "# комментарий" in text and "camera:\n  width: 640" in text
    text = registry.set_yaml_value(text, "detector", "model", "models/violations_v1.onnx")
    assert text.endswith("detector:\n  model: models/violations_v1.onnx\n")
    text = registry.set_yaml_value(text, "detector", "model", "models/violations_v2.onnx")
    assert text.count("model:") == 1 and "violations_v2" in text
    text = registry.set_yaml_value(text, "device", "fw_version", '"0.3.0"')
    assert "  profile: highway\n  fw_version: \"0.3.0\"\n" in text


def test_promote_copies_onnx_and_binds_device(tmp_path: Path):
    ml_root = tmp_path / "ml"
    (ml_root / "models").mkdir(parents=True)
    (ml_root / "models" / "violations_v1.onnx").write_bytes(b"onnx")
    device = tmp_path / "device"
    device.mkdir()
    (device / "config.yaml").write_text(CONFIG, encoding="utf-8")
    reg = {"models": [{"version": "v1", "gate": {"passed": True}, "artifacts": {"onnx": "models/violations_v1.onnx"}}]}
    dst = registry.promote(reg, "v1", device, ml_root=ml_root)
    assert dst == device / "models" / "violations_v1.onnx" and dst.read_bytes() == b"onnx"
    cfg = (device / "config.yaml").read_text(encoding="utf-8")
    assert "model_version: violations-v1" in cfg and "detector:\n  model: models/violations_v1.onnx" in cfg
    assert reg["models"][0]["promoted_at"] and reg["models"][0]["device_model"] == "models/violations_v1.onnx"
    with pytest.raises(ValueError):
        registry.promote({"models": [{"version": "v2", "artifacts": {}}]}, "v2", device, ml_root=ml_root)
    assert registry.model_label("v3") == "violations-v3"


def test_dataset_fingerprint_changes_with_files(tmp_path: Path):
    (tmp_path / "images").mkdir()
    (tmp_path / "images" / "a.jpg").write_bytes(b"1")
    f1 = registry.dataset_fingerprint(tmp_path)
    (tmp_path / "images" / "b.jpg").write_bytes(b"22")
    assert f1 != registry.dataset_fingerprint(tmp_path) and len(f1) == 12


def test_results_csv_and_gate(tmp_path: Path):
    p = tmp_path / "results.csv"
    p.write_text(RESULTS, encoding="utf-8")
    last = read_results_csv(p)
    assert last["epoch"] == 3 and abs(last["map50"] - 0.86) < 1e-9
    best = best_epoch(p)
    assert best["epoch"] == 2 and abs(best["map50_95"] - 0.52) < 1e-9
    assert gate(best)[0] and not gate({"map50": 0.84})[0]
    assert "ворота НЕ пройдены" in gate({})[1]
    md = per_class_markdown([{"name": "phone", "precision": 0.9, "recall": 0.8, "ap50": 0.88}])
    assert "| phone | 0.900 | 0.800 | 0.880 |" in md
    cm = confusion_markdown([[10, 1, 2], [0, 8, 1], [1, 2, 0]], ["phone", "cigarette"])
    assert cm.splitlines()[0] == "| предсказано \\ истина | phone | cigarette | фон |"
    assert "| фон | 1 | 2 | 0 |" in cm


def test_letterbox_and_decode_roundtrip():
    img = np.zeros((300, 400, 3), dtype=np.uint8)
    canvas, ratio, (dw, dh) = letterbox(img, 160)
    assert canvas.shape == (160, 160, 3) and abs(ratio - 0.4) < 1e-9 and (dw, dh) == (0, 20)
    blob, _, _ = preprocess(img, 160)
    assert blob.shape == (1, 3, 160, 160) and blob.dtype == np.float32
    # два «предсказания» YOLOv8 (1, 4+nc, N): телефон в центре и его дубль, плюс слабый бокс
    nc, n = 4, 3
    out = np.zeros((1, 4 + nc, n), dtype=np.float32)
    out[0, :4, 0] = [80, 80, 40, 60]
    out[0, 4 + 0, 0] = 0.9
    out[0, :4, 1] = [82, 81, 40, 60]
    out[0, 4 + 0, 1] = 0.7  # дубль → NMS уберёт
    out[0, :4, 2] = [20, 100, 10, 10]
    out[0, 4 + 1, 2] = 0.1  # ниже порога
    dets = decode(out, ratio, (dw, dh), img.shape[:2], conf_thr=0.25, nc=nc)
    assert len(dets) == 1 and dets[0].cls == 0 and abs(dets[0].conf - 0.9) < 1e-6
    # обратно в координаты кадра: центр (80,80) на холсте → ((80-0)/0.4, (80-20)/0.4) = (200, 150)
    assert abs((dets[0].x1 + dets[0].x2) / 2 - 200) < 1 and abs((dets[0].y1 + dets[0].y2) / 2 - 150) < 1
    assert decode(out.transpose(0, 2, 1), ratio, (dw, dh), img.shape[:2], conf_thr=0.25, nc=nc)[0].cls == 0
    assert decode(out, ratio, (dw, dh), img.shape[:2], conf_thr=0.95, nc=nc) == []
    big = np.zeros((1, 4 + nc, 8400), dtype=np.float32)  # реальная форма ultralytics — без nc тоже верно
    big[0, :4, 5] = [80, 80, 40, 60]
    big[0, 4 + 2, 5] = 0.6
    assert decode(big, ratio, (dw, dh), img.shape[:2])[0].cls == 2


def test_nms_and_parse_names():
    boxes = np.array([[0, 0, 10, 10], [1, 1, 11, 11], [50, 50, 60, 60]], dtype=np.float32)
    assert sorted(nms(boxes, np.array([0.9, 0.8, 0.7]))) == [0, 2]
    assert nms(np.zeros((0, 4)), np.zeros(0)) == []
    assert parse_names({"names": "{0: 'phone', 1: 'cigarette'}"}) == {0: "phone", 1: "cigarette"}
    assert parse_names({"names": '["a", "b"]'}) == {0: "a", 1: "b"}
    assert parse_names({}) == {} and parse_names({"names": "???"}) == {}
