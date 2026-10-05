#!/usr/bin/env python
"""Реестр версий моделей (ML-4).

  python scripts/registry.py list
  python scripts/registry.py show v1
  python scripts/registry.py promote v1        # ONNX → device/models, config.yaml: detector.model + model_version
  python scripts/registry.py set-hef v1 models/violations_v1.hef
  python scripts/registry.py note v1 "дообучена на очереди 2026-09-20"
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dgml import ML_ROOT, registry  # noqa: E402

DEVICE_DIR = ML_ROOT.parent / "device"


def cmd_list(reg: dict) -> None:
    if not reg["models"]:
        print("Реестр пуст — scripts/train.py запишет первую версию")
        return
    print("| Версия | Дата | mAP@50 | Ворота | ONNX | HEF | На устройстве | Заметка |")
    print("|---|---|---|---|---|---|---|---|")
    for m in reg["models"]:
        art = m.get("artifacts") or {}
        g = m.get("gate") or {}
        map50 = (m.get("metrics") or {}).get("map50", 0)
        cells = [
            m["version"], m.get("created", "")[:10], f"{map50:.3f}", "✅" if g.get("passed") else "❌",
            "да" if art.get("onnx") else "—", "да" if art.get("hef") else "—",
            m.get("promoted_at", "")[:10] or "—", m.get("notes", ""),
        ]
        print("| " + " | ".join(cells) + " |")


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Реестр версий моделей DriverGuard")
    sub = p.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list")
    sub.add_parser("show").add_argument("version")
    promote = sub.add_parser("promote")
    promote.add_argument("version")
    promote.add_argument("--device-dir", default=str(DEVICE_DIR))
    set_hef = sub.add_parser("set-hef")
    set_hef.add_argument("version")
    set_hef.add_argument("path")
    note = sub.add_parser("note")
    note.add_argument("version")
    note.add_argument("text")
    a = p.parse_args(argv)
    reg = registry.load()
    if a.cmd == "list":
        cmd_list(reg)
        return 0
    if registry.get(reg, a.version) is None:
        print(f"Версии {a.version} нет в реестре", file=sys.stderr)
        return 1
    if a.cmd == "show":
        print(json.dumps(registry.get(reg, a.version), ensure_ascii=False, indent=2))
        return 0
    if a.cmd == "promote":
        dst = registry.promote(reg, a.version, Path(a.device_dir))
        registry.save(reg)
        print(f"{a.version} → {dst}; device/config.yaml: detector.model и device.model_version = "
              f"{registry.model_label(a.version)}. Перезапустите устройство.")
        return 0
    if a.cmd == "set-hef":
        registry.update(reg, a.version, artifacts={"hef": a.path})
        registry.save(reg)
        print(f"{a.version}: hef = {a.path}")
        return 0
    if a.cmd == "note":
        registry.update(reg, a.version, notes=a.text)
        registry.save(reg)
        return 0
    return 1


if __name__ == "__main__":
    sys.exit(main())
