#!/usr/bin/env python
"""Отчёт по стенду (ML-6): протокол с временами прогонов + события устройства → precision/recall, задержка.

  python scripts/bench_report.py bench/protocol.csv --sqlite ../device/dg.sqlite --out ../docs/bench-report.md
  python scripts/bench_report.py bench/protocol.csv --events events.json     # экспорт из панели (GET /events)
  python scripts/bench_report.py bench/protocol.csv --events events.csv      # CSV из панели «События»
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from dgml.bench import (  # noqa: E402
    evaluate,
    events_from_csv,
    events_from_json,
    events_from_sqlite,
    read_protocol,
    report_markdown,
)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Расчёт метрик стендовых испытаний")
    p.add_argument("protocol", help="CSV протокола с заполненными временами")
    p.add_argument("--sqlite", default=None, help="device/dg.sqlite")
    p.add_argument("--events", default=None, help="JSON или CSV событий из панели")
    p.add_argument("--grace", type=float, default=5.0, help="допуск после конца прогона, с")
    p.add_argument("--title", default="Стендовые испытания DriverGuard")
    p.add_argument("--out", default=None, help="Markdown-файл отчёта (по умолчанию — в stdout)")
    a = p.parse_args(argv)
    if not a.sqlite and not a.events:
        p.error("нужен --sqlite или --events")
    events = []
    if a.sqlite:
        events += events_from_sqlite(Path(a.sqlite))
    if a.events:
        path = Path(a.events)
        events += events_from_json(path) if path.suffix.lower() == ".json" else events_from_csv(path)
    result = evaluate(read_protocol(Path(a.protocol)), events, grace_s=a.grace)
    md = report_markdown(result, a.title)
    if a.out:
        Path(a.out).write_text(md, encoding="utf-8")
        print(f"Отчёт → {a.out} (событий: {len(events)}, прогонов: {result['evaluated']})")
    else:
        print(md)
    return 0


if __name__ == "__main__":
    sys.exit(main())
