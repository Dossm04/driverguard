"""Стендовый протокол (ML-6, Приложение Г ТЗ): 20 сценариев × день/ночь × 3 повтора × испытуемые.

Оператор заполняет started_at / stimulus_at / ended_at каждого прогона (ISO-время, как на устройстве),
evaluate() сопоставляет прогоны с событиями устройства и считает TP/FP/FN, precision/recall, задержку.
"""

from __future__ import annotations

import csv
import json
import sqlite3
from collections import defaultdict
from dataclasses import dataclass, field
from datetime import UTC, datetime, timedelta
from pathlib import Path

# (№, сценарий, ожидаемое событие или None, примечание)
SCENARIOS: list[tuple[int, str, str | None, str]] = [
    (1, "Глаза закрыты 2 с", "microsleep", ""),
    (2, "Глаза закрыты 1 с", None, "нет события"),
    (3, "Частые моргания 1 мин", None, "нет события"),
    (4, "Зевок ×3 за 3 мин", "fatigue", "fatigue ×1"),
    (5, "Медленное опускание головы 3 с", "head_nod", ""),
    (6, "Взгляд вправо 10 с", "distraction", ""),
    (7, "Взгляд в зеркало 3 с", None, "нет события"),
    (8, "Телефон у уха 5 с", "phone", ""),
    (9, "Рука у уха без телефона", None, "нет события"),
    (10, "Телефон лежит на панели", None, "нет события"),
    (11, "Сигарета у лица 5 с", "smoking", ""),
    (12, "Ручка/карандаш у рта", None, "нет события"),
    (13, "Ремень пристёгнут, куртка тёмная", None, "нет события"),
    (14, "Без ремня 40 с", "seatbelt", "beta"),
    (15, "Очки прозрачные, сценарии 1–2", "microsleep", "как в 1–2: событие при 2 с, нет при 1 с"),
    (16, "Солнцезащитные очки, сценарий 5", "head_nod", "без ложного microsleep"),
    (17, "Головной убор с козырьком", None, "детекция лица сохраняется"),
    (18, "Лицо закрыто рукой 4 с", None, "локальное предупреждение, событий нет"),
    (19, "Камера перекрыта 6 мин («движение» в симуляции)", "camera_sabotage", ""),
    (20, "Водитель вышел из кабины", None, "предупреждение, нет ложных событий"),
]
CONDITIONS = ("день", "ночь")
COLUMNS = [
    "run_id", "subject", "condition", "repeat", "scenario_id", "scenario", "expected",
    "started_at", "stimulus_at", "ended_at", "observed", "latency_ms", "fps", "temp_c", "note",
]
EVENT_TYPES = [
    "microsleep", "fatigue", "head_nod", "distraction", "phone", "smoking", "seatbelt", "camera_sabotage", "speeding",
]


def make_protocol(subjects: int | list[str], conditions=CONDITIONS, repeats: int = 3) -> list[dict]:
    names = [f"S{i + 1:02d}" for i in range(subjects)] if isinstance(subjects, int) else list(subjects)
    rows = []
    n = 0
    for subject in names:
        for cond in conditions:
            for rep in range(1, repeats + 1):
                for sid, title, expected, note in SCENARIOS:
                    n += 1
                    rows.append({
                        "run_id": f"R{n:04d}", "subject": subject, "condition": cond, "repeat": rep,
                        "scenario_id": sid, "scenario": title, "expected": expected or "", "started_at": "",
                        "stimulus_at": "", "ended_at": "", "observed": "", "latency_ms": "", "fps": "",
                        "temp_c": "", "note": note,
                    })
    return rows


def write_protocol(rows: list[dict], path: Path) -> None:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=COLUMNS)
        w.writeheader()
        w.writerows(rows)


def read_protocol(path: Path) -> list[dict]:
    with Path(path).open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _parse_ts(value: str | None) -> datetime | None:
    if not value:
        return None
    v = value.strip().replace("Z", "+00:00")
    try:
        dt = datetime.fromisoformat(v)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


@dataclass
class EventRec:
    type: str
    ts: datetime


def events_from_sqlite(path: Path) -> list[EventRec]:
    """События из очереди устройства (device/dg.sqlite, таблица events)."""
    conn = sqlite3.connect(str(path))
    try:
        rows = conn.execute("SELECT type, ts FROM events").fetchall()
    finally:
        conn.close()
    out = []
    for t, ts in rows:
        dt = _parse_ts(ts)
        if dt:
            out.append(EventRec(str(t), dt))
    return out


def events_from_json(path: Path) -> list[EventRec]:
    """Экспорт из панели: JSON-список объектов (или {"items": [...]}) с полями type, ts."""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    items = data.get("items", []) if isinstance(data, dict) else data
    out = []
    for e in items:
        dt = _parse_ts(e.get("ts"))
        if dt and e.get("type"):
            out.append(EventRec(str(e["type"]), dt))
    return out


def events_from_csv(path: Path) -> list[EventRec]:
    with Path(path).open(encoding="utf-8") as f:
        rows = list(csv.DictReader(f))
    out = []
    for r in rows:
        dt = _parse_ts(r.get("ts") or r.get("Время") or r.get("time"))
        t = r.get("type") or r.get("Тип") or r.get("event")
        if dt and t:
            out.append(EventRec(str(t), dt))
    return out


@dataclass
class TypeStats:
    tp: int = 0
    fp: int = 0
    fn: int = 0
    latencies: list[float] = field(default_factory=list)

    @property
    def precision(self) -> float | None:
        return self.tp / (self.tp + self.fp) if (self.tp + self.fp) else None

    @property
    def recall(self) -> float | None:
        return self.tp / (self.tp + self.fn) if (self.tp + self.fn) else None


def evaluate(rows: list[dict], events: list[EventRec], grace_s: float = 5.0) -> dict:
    """Сопоставляет прогоны протокола с событиями устройства.

    Окно прогона — [started_at, ended_at + grace]. Ожидаемое событие в окне → TP (задержка от stimulus_at,
    иначе от started_at); нет — FN. Любое другое событие в окне → FP этого типа. Прогоны без времени
    начала/конца пропускаются (считаются в `skipped`).
    """
    by_type: dict[str, TypeStats] = defaultdict(TypeStats)
    by_cond: dict[str, dict[str, TypeStats]] = defaultdict(lambda: defaultdict(TypeStats))
    skipped = 0
    per_run = []
    for r in rows:
        start, end = _parse_ts(r.get("started_at")), _parse_ts(r.get("ended_at"))
        if not start or not end:
            skipped += 1
            continue
        stim = _parse_ts(r.get("stimulus_at")) or start
        window_end = end + timedelta(seconds=grace_s)
        expected = (r.get("expected") or "").strip() or None
        inside = sorted((e for e in events if start <= e.ts <= window_end), key=lambda e: e.ts)
        detected = {e.type for e in inside}
        cond = r.get("condition") or "—"
        if expected:
            if expected in detected:
                first = next(e for e in inside if e.type == expected)
                latency = (first.ts - stim).total_seconds() * 1000
                for stats in (by_type[expected], by_cond[cond][expected]):
                    stats.tp += 1
                    stats.latencies.append(latency)
            else:
                by_type[expected].fn += 1
                by_cond[cond][expected].fn += 1
        for t in detected - ({expected} if expected else set()):
            by_type[t].fp += 1
            by_cond[cond][t].fp += 1
        per_run.append({"run_id": r.get("run_id"), "expected": expected, "observed": sorted(detected),
                        "ok": (expected in detected) if expected else not detected})
    return {"by_type": dict(by_type), "by_condition": {c: dict(v) for c, v in by_cond.items()},
            "skipped": skipped, "runs": per_run, "evaluated": len(rows) - skipped}


def _fmt(v: float | None) -> str:
    return "—" if v is None else f"{v:.0%}"


def _table(stats: dict[str, TypeStats]) -> list[str]:
    lines = ["| Тип | TP | FP | FN | Precision | Recall | Задержка, мс (медиана) |", "|---|---|---|---|---|---|---|"]
    for t in sorted(stats, key=lambda x: (EVENT_TYPES.index(x) if x in EVENT_TYPES else 99, x)):
        s = stats[t]
        lat = sorted(s.latencies)
        med = f"{lat[len(lat) // 2]:.0f}" if lat else "—"
        lines.append(f"| {t} | {s.tp} | {s.fp} | {s.fn} | {_fmt(s.precision)} | {_fmt(s.recall)} | {med} |")
    return lines


def report_markdown(result: dict, title: str = "Стендовые испытания") -> str:
    by_type: dict[str, TypeStats] = result["by_type"]
    tp = sum(s.tp for s in by_type.values())
    fp = sum(s.fp for s in by_type.values())
    precision_all = tp / (tp + fp) if (tp + fp) else None
    ms = by_type.get("microsleep")
    lines = [f"# {title}", "",
             f"Прогонов оценено: {result['evaluated']} (пропущено без времени: {result['skipped']}).", "",
             f"**KPI-2** precision всех алертов: {_fmt(precision_all)} (цель ≥ 90 %) · "
             f"**KPI-1** recall микросна: {_fmt(ms.recall if ms else None)} (цель ≥ 95 %)", "",
             "## По типам событий", *_table(by_type)]
    for cond, stats in result["by_condition"].items():
        lines += ["", f"## Условие: {cond}", *_table(stats)]
    failed = [r for r in result["runs"] if not r["ok"]]
    if failed:
        lines += ["", "## Несовпадения", "| Прогон | Ожидалось | Наблюдалось |", "|---|---|---|"]
        lines += [f"| {r['run_id']} | {r['expected'] or 'нет события'} | {', '.join(r['observed']) or '—'} |"
                  for r in failed]
    return "\n".join(lines) + "\n"
