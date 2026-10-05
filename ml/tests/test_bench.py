"""Стендовый протокол (ML-6): генерация, сопоставление с событиями, precision/recall и отчёт."""

import sqlite3
from datetime import UTC, datetime, timedelta
from pathlib import Path

from dgml.bench import (
    SCENARIOS,
    EventRec,
    evaluate,
    events_from_json,
    events_from_sqlite,
    make_protocol,
    read_protocol,
    report_markdown,
    write_protocol,
)

T0 = datetime(2026, 9, 22, 10, 0, tzinfo=UTC)


def test_protocol_shape_and_roundtrip(tmp_path: Path):
    rows = make_protocol(2, repeats=3)
    assert len(rows) == 2 * 2 * 3 * 20 and len(SCENARIOS) == 20
    assert rows[0]["expected"] == "microsleep" and rows[1]["expected"] == ""
    path = tmp_path / "p.csv"
    write_protocol(rows, path)
    back = read_protocol(path)
    assert back[7]["scenario_id"] == "8" and back[7]["expected"] == "phone"
    named = make_protocol(["Иванов"], conditions=("день",), repeats=1)
    assert len(named) == 20 and named[0]["subject"] == "Иванов" and named[0]["run_id"] == "R0001"


def _runs():
    rows = make_protocol(1, conditions=("день",), repeats=1)
    t = T0
    for r in rows:
        r["started_at"] = t.isoformat()
        r["stimulus_at"] = (t + timedelta(seconds=2)).isoformat()
        r["ended_at"] = (t + timedelta(seconds=30)).isoformat()
        t += timedelta(minutes=1)
    return rows


def test_evaluate_counts_tp_fp_fn_and_latency():
    rows = _runs()
    by_id = {int(r["scenario_id"]): r for r in rows}

    def at(sid: int, offset_s: float) -> datetime:
        return datetime.fromisoformat(by_id[sid]["started_at"]) + timedelta(seconds=offset_s)

    events = [
        EventRec("microsleep", at(1, 3.2)),  # TP, задержка 1200 мс от stimulus (2 с)
        EventRec("microsleep", at(2, 4)),  # FP: ожидалось «нет события»
        EventRec("phone", at(8, 6)),  # TP
        EventRec("phone", at(10, 5)),  # FP: телефон на панели
        EventRec("head_nod", at(16, 4)),  # TP
        EventRec("microsleep", at(16, 5)),  # FP: ложный микросон в тёмных очках
        EventRec("microsleep", at(15, 3)),  # TP: очки прозрачные
        # сценарий 11 (smoking) и 19 (camera_sabotage) без события → FN
    ]
    res = evaluate(rows, events)
    assert res["skipped"] == 0 and res["evaluated"] == 20
    ms = res["by_type"]["microsleep"]
    assert (ms.tp, ms.fp, ms.fn) == (2, 2, 0)
    ph = res["by_type"]["phone"]
    assert (ph.tp, ph.fp, ph.fn) == (1, 1, 0) and ph.precision == 0.5 and ph.recall == 1.0
    assert res["by_type"]["smoking"].fn == 1 and res["by_type"]["camera_sabotage"].fn == 1
    assert abs(ms.latencies[0] - 1200) < 1
    assert res["by_condition"]["день"]["phone"].tp == 1
    md = report_markdown(res)
    assert "KPI-2" in md and "| phone | 1 | 1 | 0 | 50% | 100% |" in md
    assert "## Условие: день" in md and "## Несовпадения" in md and "R0002" in md


def test_evaluate_skips_runs_without_times_and_grace_window():
    rows = _runs()
    rows[0]["ended_at"] = ""
    late = datetime.fromisoformat(rows[7]["ended_at"]) + timedelta(seconds=4)  # в пределах grace 5 с
    too_late = datetime.fromisoformat(rows[7]["ended_at"]) + timedelta(seconds=9)
    res = evaluate(rows, [EventRec("phone", late), EventRec("smoking", too_late)])
    assert res["skipped"] == 1
    assert res["by_type"]["phone"].tp == 1
    assert res["by_type"]["smoking"].fp == 0 and res["by_type"]["smoking"].fn == 1  # событие после grace не в окне


def test_event_sources(tmp_path: Path):
    db = tmp_path / "dg.sqlite"
    conn = sqlite3.connect(db)
    conn.execute("CREATE TABLE events (uuid TEXT, type TEXT, ts TEXT)")
    conn.execute("INSERT INTO events VALUES ('1', 'phone', '2026-09-22T10:00:05+00:00')")
    conn.execute("INSERT INTO events VALUES ('2', 'x', 'мусор')")
    conn.commit()
    conn.close()
    evs = events_from_sqlite(db)
    assert len(evs) == 1 and evs[0].type == "phone" and evs[0].ts.tzinfo is not None
    j = tmp_path / "events.json"
    j.write_text('{"items": [{"type": "microsleep", "ts": "2026-09-22T10:00:05Z"}, {"type": "", "ts": "x"}]}',
                 encoding="utf-8")
    assert [e.type for e in events_from_json(j)] == ["microsleep"]
