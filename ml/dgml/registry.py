"""Реестр версий моделей (ML-4): ml/models/registry.json — v1, v2, … с метриками, отпечатком датасета,
коммитом и артефактами; promote() привязывает версию к устройству (device/config.yaml + копия ONNX)."""

from __future__ import annotations

import hashlib
import json
import re
import shutil
import subprocess
from datetime import UTC, datetime
from pathlib import Path

from dgml import ML_ROOT

REGISTRY_PATH = ML_ROOT / "models" / "registry.json"
_VERSION_RE = re.compile(r"^v\d+$")


def load(path: Path = REGISTRY_PATH) -> dict:
    path = Path(path)
    if not path.is_file():
        return {"models": []}
    data = json.loads(path.read_text(encoding="utf-8"))
    data.setdefault("models", [])
    return data


def save(reg: dict, path: Path = REGISTRY_PATH) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(reg, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def get(reg: dict, version: str) -> dict | None:
    return next((m for m in reg["models"] if m.get("version") == version), None)


def next_version(reg: dict) -> str:
    nums = [int(m["version"][1:]) for m in reg["models"] if _VERSION_RE.match(str(m.get("version", "")))]
    return f"v{max(nums, default=0) + 1}"


def add(reg: dict, entry: dict) -> dict:
    version = entry.get("version") or next_version(reg)
    if not _VERSION_RE.match(version):
        raise ValueError(f"Версия должна быть вида v1, v2, … (получено {version!r})")
    if get(reg, version) is not None:
        raise ValueError(f"Версия {version} уже есть в реестре")
    entry = {"version": version, "created": now_iso(), **entry}
    entry["version"] = version
    reg["models"].append(entry)
    return entry


def update(reg: dict, version: str, **fields) -> dict:
    entry = get(reg, version)
    if entry is None:
        raise KeyError(f"Версии {version} нет в реестре")
    for k, v in fields.items():
        if isinstance(v, dict) and isinstance(entry.get(k), dict):
            entry[k] = {**entry[k], **v}
        else:
            entry[k] = v
    return entry


def latest(reg: dict, passed_only: bool = False) -> dict | None:
    models = [m for m in reg["models"] if not passed_only or (m.get("gate") or {}).get("passed")]
    return max(models, key=lambda m: int(m["version"][1:]), default=None)


def now_iso() -> str:
    return datetime.now(UTC).replace(microsecond=0).isoformat()


def dataset_fingerprint(dataset_dir: Path) -> str:
    """Короткий sha1 по списку файлов и их размерам — «тот же датасет» без хэширования гигабайт."""
    root = Path(dataset_dir)
    h = hashlib.sha1()
    for p in sorted(root.rglob("*")):
        if p.is_file() and p.suffix.lower() in {".jpg", ".jpeg", ".png", ".txt"}:
            h.update(f"{p.relative_to(root)}:{p.stat().st_size}\n".encode())
    return h.hexdigest()[:12]


def git_commit(repo: Path | None = None) -> str | None:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"], cwd=str(repo or ML_ROOT), capture_output=True, text=True, timeout=5
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return out.stdout.strip() or None


def model_label(version: str) -> str:
    """Строка model_version, которую устройство шлёт в backend (ML-4: привязка версии к устройству)."""
    return f"violations-{version}"


def set_yaml_value(text: str, section: str, key: str, value: str) -> str:
    """Меняет `key:` внутри верхнеуровневой секции YAML, не трогая комментарии и остальные строки.

    Секции/ключа нет — добавляет. Работает построчно, поэтому config.yaml с комментариями сохраняется как есть.
    """
    lines = text.splitlines()
    sec_re = re.compile(rf"^{re.escape(section)}:\s*(#.*)?$")
    key_re = re.compile(rf"^(\s+){re.escape(key)}:\s*[^#]*?(\s*#.*)?$")
    start = next((i for i, ln in enumerate(lines) if sec_re.match(ln)), None)
    if start is None:
        if lines and lines[-1].strip():
            lines.append("")
        lines += [f"{section}:", f"  {key}: {value}"]
        return "\n".join(lines) + "\n"
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if lines[j] and not lines[j][0].isspace() and not lines[j].startswith("#"):
            end = j
            break
    for j in range(start + 1, end):
        m = key_re.match(lines[j])
        if m:
            comment = m.group(2) or ""
            lines[j] = f"{m.group(1)}{key}: {value}{comment}"
            return "\n".join(lines) + "\n"
    while end > start + 1 and not lines[end - 1].strip():  # вставляем до пустых строк между секциями
        end -= 1
    lines.insert(end, f"  {key}: {value}")
    return "\n".join(lines) + "\n"


def promote(reg: dict, version: str, device_dir: Path, ml_root: Path = ML_ROOT) -> Path:
    """Копирует ONNX версии в device/models/ и прописывает её в device/config.yaml (detector.model,
    device.model_version). Возвращает путь к скопированному файлу."""
    entry = get(reg, version)
    if entry is None:
        raise KeyError(f"Версии {version} нет в реестре")
    onnx_rel = (entry.get("artifacts") or {}).get("onnx")
    if (entry.get("gate") or {}).get("passed") is not True:
        raise ValueError(f"Версия {version} не прошла проверку качества — установка запрещена")
    if not onnx_rel:
        raise ValueError(f"У версии {version} нет ONNX — сначала scripts/export.py --version {version}")
    src = Path(ml_root) / onnx_rel
    if not src.is_file():
        raise FileNotFoundError(f"Файл {src} не найден")
    device_dir = Path(device_dir)
    dst_dir = device_dir / "models"
    dst_dir.mkdir(parents=True, exist_ok=True)
    dst = dst_dir / src.name
    shutil.copy2(src, dst)
    cfg = device_dir / "config.yaml"
    if cfg.is_file():
        text = cfg.read_text(encoding="utf-8")
        text = set_yaml_value(text, "device", "model_version", model_label(version))
        text = set_yaml_value(text, "detector", "model", f"models/{src.name}")
        cfg.write_text(text, encoding="utf-8")
    entry["promoted_at"] = now_iso()
    entry["device_model"] = f"models/{src.name}"
    return dst
