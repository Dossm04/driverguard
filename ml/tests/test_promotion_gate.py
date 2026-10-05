import pytest

from dgml import registry


@pytest.mark.parametrize("gate", [None, {}, {"passed": False}, {"passed": "true"}])
def test_failed_or_missing_gate_cannot_modify_device(tmp_path, gate):
    model = tmp_path / "model.onnx"
    model.write_bytes(b"unvalidated model")
    device = tmp_path / "device"
    device.mkdir()
    config = device / "config.yaml"
    config.write_text("device:\n  model_version: previous\n", encoding="utf-8")
    before = config.read_bytes()
    reg = {"models": [{"version": "v1", "gate": gate, "artifacts": {"onnx": "model.onnx"}}]}
    with pytest.raises(ValueError, match="проверку качества"):
        registry.promote(reg, "v1", device, ml_root=tmp_path)
    assert config.read_bytes() == before
    assert not (device / "models").exists()
