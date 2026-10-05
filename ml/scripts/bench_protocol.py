#!/usr/bin/env python
"""Генерация протокола стендовых испытаний (ML-6, Приложение Г ТЗ).

  python scripts/bench_protocol.py --subjects 5 --out bench/protocol_2026-09-22.csv
  python scripts/bench_protocol.py --subjects Иванов,Петров --repeats 3 --conditions день,ночь

Оператор заполняет started_at / stimulus_at / ended_at (ISO, например 2026-09-22T10:15:30+05:00) и fps/temp_c
из HUD устройства; результат считает scripts/bench_report.py.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dgml.bench import SCENARIOS, make_protocol, write_protocol  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Протокол стенда: 20 сценариев × условия × повторы × испытуемые")
    p.add_argument("--subjects", default="5", help="число испытуемых или имена через запятую")
    p.add_argument("--repeats", type=int, default=3)
    p.add_argument("--conditions", default="день,ночь")
    p.add_argument("--out", default="bench/protocol.csv")
    a = p.parse_args(argv)
    subjects: int | list[str] = int(a.subjects) if a.subjects.isdigit() else [s.strip() for s in a.subjects.split(",")]
    rows = make_protocol(subjects, conditions=tuple(a.conditions.split(",")), repeats=a.repeats)
    write_protocol(rows, Path(a.out))
    print(f"{len(rows)} прогонов ({len(SCENARIOS)} сценариев) → {a.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
