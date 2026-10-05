"""Отчёты (BE-14, WEB-8, US-8): сводка по периоду/депо, экспорт CSV (UTF-8 BOM) и PDF."""

from collections import Counter
from datetime import UTC, datetime, timedelta
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app import report_pdf, scoring, stats
from app.db import get_db
from app.models import Depot, Driver, Event, Trip, Vehicle
from app.security import require_roles
from app.timeutil import local_midnight

router = APIRouter(
    prefix="/reports",
    tags=["отчёты"],
    dependencies=[Depends(require_roles("admin", "coordinator", "viewer"))],
)

Period = Literal["today", "7d", "30d"]
CELL_DEG = 0.05  # ~5 км: кластер «рискованного участка» трассы


def _window(period: Period, now: datetime) -> tuple[datetime, int]:
    """(начало окна, дней для скоринга): «Сегодня» считает Score по неделе (docs/decisions.md)."""
    if period == "today":
        return local_midnight(now), 7  # день парка (Asia/Almaty)
    days = 7 if period == "7d" else 30
    return now - timedelta(days=days), days


def build_report(db: Session, period: Period, depot_id: int | None) -> dict:
    now = datetime.now(UTC)
    since, score_days = _window(period, now)
    score_since = now - timedelta(days=score_days)

    depot = db.get(Depot, depot_id) if depot_id is not None else None
    if depot_id is not None and depot is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Депо не найдено")
    drivers_q = select(Driver).options(joinedload(Driver.depot), joinedload(Driver.vehicle))
    if depot_id is not None:
        drivers_q = drivers_q.where(Driver.depot_id == depot_id)
    drivers = db.scalars(drivers_q).unique().all()
    ids = [d.id for d in drivers]
    if not ids:
        ids = [-1]  # пустой парк — пустой отчёт, а не ошибка SQL

    events = db.scalars(
        select(Event).where(
            Event.driver_id.in_(ids),
            Event.ts > since,
            Event.ts <= now,
            Event.status.in_(scoring.SCORED_STATUSES),
        )
    ).all()
    trips = db.scalars(
        select(Trip)
        .where(Trip.driver_id.in_(ids), Trip.started_at > since, Trip.started_at <= now)
        .order_by(Trip.started_at.desc())
    ).all()
    trip_events = dict(
        db.execute(
            select(Event.trip_id, func.count())
            .where(
                Event.trip_id.in_([t.id for t in trips] or [-1]),
                Event.status.in_(scoring.SCORED_STATUSES),  # как и totals: «ложные» не считаем
            )
            .group_by(Event.trip_id)
        ).all()
    )

    all_streaks = stats.streaks_by_driver(db, now)
    streaks = {i: all_streaks.get(i, 0) for i in ids if i > 0}
    weights, modifiers = stats.load_scoring(db)
    scores = stats.scores_by_driver(db, score_since, now, score_days, streaks, weights, modifiers)
    km_all = stats.km_by_driver(db, since, now)

    by_driver_events: dict[int, list[Event]] = {}
    for e in events:
        by_driver_events.setdefault(e.driver_id, []).append(e)
    by_driver = []
    for d in drivers:
        evs = by_driver_events.get(d.id, [])
        s = scores.get(d.id)
        by_driver.append(
            {
                "driver_id": d.id,
                "name": d.name,
                "depot": d.depot.name if d.depot else None,
                "vehicle_plate": d.vehicle.plate if d.vehicle else None,
                "events": len(evs),
                "critical": sum(1 for e in evs if e.severity == "critical"),
                "score": s.score if s else 100,
                "zone": s.zone if s else "ok",
                "km": round(km_all.get(d.id, 0.0)),
            }
        )
    by_driver.sort(key=lambda r: (-r["events"], r["name"]))

    type_counts = Counter(e.type for e in events)
    total_events = sum(type_counts.values()) or 1
    by_type = [
        {"type": t, "count": c, "share_pct": round(100 * c / total_events)}
        for t, c in type_counts.most_common()
    ]

    # Динамика Score парка — 8 недельных точек (как в профиле водителя)
    score_trend = []
    for weeks_ago in range(7, -1, -1):
        w_until = now - timedelta(days=weeks_ago * 7)
        w_since = w_until - timedelta(days=7)
        week_scores = stats.scores_by_driver(db, w_since, w_until, 7, streaks, weights, modifiers)
        # Неделя без единого события — точки нет (null), а не «идеальные 100»
        has_events = any(s.events for s in week_scores.values())
        score_trend.append(
            {
                "weeks_ago": weeks_ago,
                "avg_score": stats.fleet_avg(week_scores) if has_events else None,
            }
        )

    # Рискованные участки: сетка ~5 км, топ-5 по числу событий
    cells: dict[tuple[float, float], dict] = {}
    for e in events:
        if e.lat is None or e.lon is None:
            continue
        key = (round(e.lat / CELL_DEG) * CELL_DEG, round(e.lon / CELL_DEG) * CELL_DEG)
        cell = cells.setdefault(key, {"events": 0, "critical": 0, "types": Counter()})
        cell["events"] += 1
        cell["critical"] += e.severity == "critical"
        cell["types"][e.type] += 1
    risky = sorted(cells.items(), key=lambda kv: (-kv[1]["critical"], -kv[1]["events"]))[:5]
    risky_segments = [
        {
            "lat": round(lat, 3),
            "lon": round(lon, 3),
            "events": c["events"],
            "critical": c["critical"],
            "top_type": c["types"].most_common(1)[0][0],
        }
        for (lat, lon), c in risky
    ]

    driver_by_id = {d.id: d for d in drivers}
    vehicles = {v.id: v for v in db.scalars(select(Vehicle)).all()}
    trip_rows = [
        {
            "id": t.id,
            "driver_id": t.driver_id,
            "driver_name": driver_by_id[t.driver_id].name if t.driver_id in driver_by_id else "—",
            "vehicle_plate": vehicles[t.vehicle_id].plate if t.vehicle_id in vehicles else "—",
            "started_at": t.started_at,
            "ended_at": t.ended_at,
            "km": round(t.distance_km),
            "events": int(trip_events.get(t.id, 0)),
            "status": t.status,
        }
        for t in trips[:50]
    ]

    fleet_scores = {i: scores[i] for i in scores if i in driver_by_id}
    return {
        "period": period,
        "depot": depot.name if depot else None,
        "generated_at": now,
        "totals": {
            "events": len(events),
            "critical": sum(1 for e in events if e.severity == "critical"),
            "warning": sum(1 for e in events if e.severity == "warning"),
            "km": round(sum(km_all.get(i, 0.0) for i in driver_by_id)),
            "trips": len(trips),
            "avg_score": stats.fleet_avg(fleet_scores),
            "avg_zone": scoring.zone(stats.fleet_avg(fleet_scores)),
            "drivers": len(drivers),
        },
        "by_type": by_type,
        "by_driver": by_driver,
        "score_trend": score_trend,
        "risky_segments": risky_segments,
        "trips": trip_rows,
    }


@router.get("/summary")
def report_summary(
    period: Period = "7d", depot_id: int | None = None, db: Session = Depends(get_db)
):
    return build_report(db, period, depot_id)


def _is_number(text: str) -> bool:
    try:
        float(text)
    except ValueError:
        return False
    return True


def _csv_line(cells: list) -> str:
    out = []
    for c in cells:
        text = "" if c is None else str(c)
        # CSV-инъекция: ячейка «=CMD()» / «+…» / «@…» в Excel — формула, а не текст
        if text[:1] in ("=", "+", "-", "@", "\t", "\r") and not _is_number(text):
            text = "'" + text
        if any(ch in text for ch in ';"\n'):
            text = '"' + text.replace('"', '""') + '"'
        out.append(text)
    return ";".join(out)


def _attachment(filename: str) -> dict[str, str]:
    ascii_name = filename.encode("ascii", "ignore").decode() or "report"
    return {
        "Content-Disposition": (
            f"attachment; filename={ascii_name}; filename*=UTF-8''{quote(filename)}"
        )
    }


@router.get("/export.csv")
def export_csv(period: Period = "7d", depot_id: int | None = None, db: Session = Depends(get_db)):
    """CSV с BOM и «;» — открывается в Excel с кириллицей (как экспорт событий)."""
    r = build_report(db, period, depot_id)
    t = r["totals"]
    lines = [
        _csv_line(["DriverGuard — отчёт по парку"]),
        _csv_line(["период", report_pdf.PERIOD_LABELS[r["period"]]]),
        _csv_line(["депо", r["depot"] or "все депо"]),
        _csv_line(["сформирован", r["generated_at"].strftime("%Y-%m-%d %H:%M UTC")]),
        "",
        _csv_line(
            ["сводка", "события", "критические", "предупреждения", "км", "рейсов", "средний_score"]
        ),
        _csv_line(
            ["", t["events"], t["critical"], t["warning"], t["km"], t["trips"], t["avg_score"]]
        ),
        "",
        _csv_line(["тип", "название", "событий", "доля_%"]),
        *[
            _csv_line(
                [
                    x["type"],
                    report_pdf.EVENT_LABELS.get(x["type"], x["type"]),
                    x["count"],
                    x["share_pct"],
                ]
            )
            for x in r["by_type"]
        ],
        "",
        _csv_line(["водитель", "депо", "машина", "событий", "критических", "score", "зона", "км"]),
        *[
            _csv_line(
                [
                    d["name"],
                    d["depot"],
                    d["vehicle_plate"],
                    d["events"],
                    d["critical"],
                    d["score"],
                    d["zone"],
                    d["km"],
                ]
            )
            for d in r["by_driver"]
        ],
        "",
        _csv_line(["динамика_score", "недель_назад", "средний_score"]),
        *[_csv_line(["", p["weeks_ago"], p["avg_score"]]) for p in r["score_trend"]],
        "",
        _csv_line(
            ["рискованный_участок", "широта", "долгота", "событий", "критических", "основной_тип"]
        ),
        *[
            _csv_line([i, s["lat"], s["lon"], s["events"], s["critical"], s["top_type"]])
            for i, s in enumerate(r["risky_segments"], start=1)
        ],
        "",
        _csv_line(
            ["рейс", "водитель", "машина", "начало", "завершение", "км", "событий", "статус"]
        ),
        *[
            _csv_line(
                [
                    x["id"],
                    x["driver_name"],
                    x["vehicle_plate"],
                    x["started_at"].isoformat(),
                    x["ended_at"].isoformat() if x["ended_at"] else "",
                    x["km"],
                    x["events"],
                    x["status"],
                ]
            )
            for x in r["trips"]
        ],
    ]
    body = "﻿" + "\r\n".join(lines) + "\r\n"
    return Response(
        content=body.encode("utf-8"),
        media_type="text/csv; charset=utf-8",
        headers=_attachment(f"driverguard_отчёт_{period}.csv"),
    )


@router.get("/export.pdf")
def export_pdf(period: Period = "7d", depot_id: int | None = None, db: Session = Depends(get_db)):
    r = build_report(db, period, depot_id)
    r["generated_at"] = r["generated_at"].isoformat()
    for t in r["trips"]:
        t["started_at"] = t["started_at"].isoformat()
        t["ended_at"] = t["ended_at"].isoformat() if t["ended_at"] else None
    try:
        pdf = report_pdf.build_pdf(r)
    except report_pdf.FontNotFound as exc:  # правило 8: не печатаем квадраты вместо кириллицы
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from exc
    return Response(
        content=pdf,
        media_type="application/pdf",
        headers=_attachment(f"driverguard_отчёт_{period}.pdf"),
    )
