"""Лидерборд (BE-7): ранжирование, дельта, серии, бейджи, командный зачёт депо."""

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.orm import Session, joinedload

from app import scoring, stats
from app.db import get_db
from app.models import Driver
from app.security import get_current_user

router = APIRouter(tags=["лидерборд"], dependencies=[Depends(get_current_user)])


def _badges(streak: int) -> list[str]:
    """Бейджи серии (ТЗ 6.1.6). «Ночной страж» появится с данными ночных рейсов."""
    badges = []
    if streak >= 7:
        badges.append("week_no_risk")
    if streak >= 30:
        badges.append("iron_streak")
    return badges


@router.get("/leaderboard")
def leaderboard(period: Literal["7", "30"] = "7", db: Session = Depends(get_db)):
    days = int(period)
    now = datetime.now(UTC)
    since = now - timedelta(days=days)

    streaks = stats.streaks_by_driver(db, now)
    weights = stats.load_weights(db)
    cur = stats.scores_by_driver(db, since, now, days, streaks, weights)
    prev = stats.scores_by_driver(db, now - timedelta(days=2 * days), since, days, streaks, weights)
    km = stats.km_by_driver(db, since, now)
    drivers = db.scalars(select(Driver).options(joinedload(Driver.depot))).all()

    rows = []
    for d in drivers:
        s = cur.get(d.id)
        if s is None:
            continue
        # новичок: добавлен внутри периода и ещё без событий — Score/серия ему не начислены
        is_new = d.created_at is not None and d.created_at > since and s.events == 0
        rows.append(
            {
                "driver_id": d.id,
                "is_new": is_new,
                "name": d.name,
                "depot": d.depot.name if d.depot else "—",
                "score": s.score,
                "zone": s.zone,
                "delta": s.score - prev[d.id].score if d.id in prev else 0,
                "streak": streaks.get(d.id, 0),
                "km": round(km.get(d.id, 0.0)),
                "events": s.events,
                "badges": _badges(streaks.get(d.id, 0)),
            }
        )
    rows.sort(key=lambda r: (r["is_new"], -r["score"], r["events"], r["name"]))  # новички — в конце
    for rank, row in enumerate(rows, start=1):
        row["rank"] = rank

    depots: dict[str, list[int]] = {}
    for row in rows:
        depots.setdefault(row["depot"], []).append(row["score"])
    depot_rows = []
    for name, values in depots.items():
        avg = scoring.round_half_up(sum(values) / len(values))
        depot_rows.append(
            {"name": name, "avg_score": avg, "zone": scoring.zone(avg), "drivers": len(values)}
        )
    depot_rows.sort(key=lambda r: -r["avg_score"])

    return {"period_days": days, "rows": rows, "depots": depot_rows}
