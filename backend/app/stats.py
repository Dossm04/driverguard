"""Агрегаты для дашборда/лидерборда: обвязка вокруг чистого app.scoring.

Окна скоринга (docs/decisions.md): KPI «Средний Score» — окно выбранного периода
(today → 7 дней), «красная зона» — 30-дневное окно.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import scoring
from app.models import Driver, Event, Setting, Trip
from app.scoring import ScoredEvent
from app.timeutil import local_date


@dataclass
class DriverScore:
    score: int
    events: int
    zone: str


def load_scoring(db: Session) -> tuple[dict[str, float], dict[str, float]]:
    """(веса, модификаторы) из Настроек (BE-15); дефолты формулы — как в CLAUDE.md."""
    row = db.get(Setting, "scoring")
    weights = dict(scoring.DEFAULT_WEIGHTS)
    modifiers = dict(scoring.DEFAULT_MODIFIERS)
    if row and isinstance(row.value, dict):
        weights.update(row.value.get("weights", {}))
        modifiers.update(row.value.get("modifiers", {}))
    return weights, modifiers


def load_weights(db: Session) -> dict[str, float]:
    return load_scoring(db)[0]


def _scored(e: Event) -> ScoredEvent:
    return ScoredEvent(e.type, e.ts, e.speed_kmh, e.value, e.status, e.severity)


def streaks_by_driver(
    db: Session, now: datetime | None = None, driver_id: int | None = None
) -> dict[int, int]:
    """Серия: дни подряд без critical-событий (new/confirmed). driver_id — только один
    водитель (профиль/PWA), иначе весь парк (лидерборд, дашборд)."""
    now = now or datetime.now(UTC)
    events_q = select(Event.driver_id, Event.ts).where(
        Event.severity == "critical",
        Event.status.in_(scoring.SCORED_STATUSES),
        Event.driver_id.is_not(None),
        Event.ts > now - timedelta(days=365),
    )
    drivers_q = select(Driver.id, Driver.created_at)
    if driver_id is not None:
        events_q = events_q.where(Event.driver_id == driver_id)
        drivers_q = drivers_q.where(Driver.id == driver_id)
    by_driver: dict[int, list] = {}
    for d_id, ts in db.execute(events_q).all():
        by_driver.setdefault(d_id, []).append(local_date(ts))
    today = local_date(now)
    out: dict[int, int] = {}
    for d_id, created in db.execute(drivers_q).all():
        # серия не длиннее стажа: новичок без событий — 0 дней, а не 365
        tenure = max(0, (today - local_date(created)).days) if created else 365
        out[d_id] = min(scoring.streak_days(by_driver.get(d_id, []), today), tenure)
    return out


def scores_by_driver(
    db: Session,
    since: datetime,
    until: datetime,
    days: int,
    streaks: dict[int, int],
    weights: dict[str, float] | None = None,
    modifiers: dict[str, float] | None = None,
) -> dict[int, DriverScore]:
    """Score всех водителей за окно (since, until]; конфиг — из Настроек, если не передан."""
    if weights is None or modifiers is None:
        db_weights, db_modifiers = load_scoring(db)
        weights = weights or db_weights
        modifiers = modifiers or db_modifiers
    events = db.scalars(
        select(Event).where(
            Event.ts > since,
            Event.ts <= until,
            Event.status.in_(scoring.SCORED_STATUSES),
            Event.driver_id.is_not(None),
        )
    ).all()
    by_driver: dict[int, list[ScoredEvent]] = {}
    for e in events:
        by_driver.setdefault(e.driver_id, []).append(_scored(e))
    result: dict[int, DriverScore] = {}
    for driver_id, streak in streaks.items():
        evs = by_driver.get(driver_id, [])
        value = scoring.score(evs, days, streak, weights, modifiers)
        result[driver_id] = DriverScore(score=value, events=len(evs), zone=scoring.zone(value))
    return result


def fleet_avg(scores: dict[int, DriverScore]) -> int:
    if not scores:
        return 100
    return scoring.round_half_up(sum(s.score for s in scores.values()) / len(scores))


def km_by_driver(db: Session, since: datetime, until: datetime) -> dict[int, float]:
    rows = db.execute(
        select(Trip.driver_id, func.coalesce(func.sum(Trip.distance_km), 0.0))
        .where(Trip.started_at > since, Trip.started_at <= until)
        .group_by(Trip.driver_id)
    ).all()
    return {driver_id: float(km) for driver_id, km in rows}


def trips_count_by_driver(db: Session, since: datetime, until: datetime) -> dict[int, int]:
    rows = db.execute(
        select(Trip.driver_id, func.count())
        .where(Trip.started_at > since, Trip.started_at <= until)
        .group_by(Trip.driver_id)
    ).all()
    return dict(rows)
