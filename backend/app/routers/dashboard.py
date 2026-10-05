"""Дашборд-агрегаты (BE-9): KPI сводка, графики, критические, красная зона.

На seed-данных summary обязан возвращать ровно цифры Figma (правило 3 CLAUDE.md).
"""

from datetime import UTC, datetime, timedelta
from typing import Literal

from fastapi import APIRouter, Depends
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app import scoring, stats
from app.db import get_db
from app.models import Device, Driver, Event, Heartbeat
from app.routers.events import event_out
from app.schemas import EventOut
from app.security import phone_for, require_roles
from app.timeutil import local_date, local_midnight

router = APIRouter(
    prefix="/dashboard",
    tags=["дашборд"],
    # Панель координатора — только сотрудники (SEC-1)
    dependencies=[Depends(require_roles("admin", "coordinator", "viewer"))],
)

Period = Literal["today", "7d", "30d"]
ONLINE_WINDOW = timedelta(minutes=5)
HEARTBEAT_EXPECTED_PER_DEVICE = 7 * 24 * 6  # каждые 10 минут за 7 дней (REL-5)


def _period_days(period: Period) -> int:
    """Окно скоринга периода: для «Сегодня» — неделя (см. docs/decisions.md)."""
    return {"today": 7, "7d": 7, "30d": 30}[period]


def _active_events(db: Session, since: datetime, until: datetime):
    return (
        db.scalar(
            select(func.count())
            .select_from(Event)
            .where(
                Event.ts > since,
                Event.ts <= until,
                Event.status.in_(scoring.SCORED_STATUSES),
            )
        )
        or 0
    )


@router.get("/summary")
def summary(period: Period = "today", db: Session = Depends(get_db)):
    now = datetime.now(UTC)
    today = local_midnight(now)  # день парка (Asia/Almaty), а не UTC

    # 1. Машины на линии = устройства с heartbeat за 5 минут (BE-17)
    devices = db.scalars(select(Device)).all()
    online = sum(1 for d in devices if d.last_seen and now - d.last_seen <= ONLINE_WINDOW)

    # 2. События за период + дельта к прошлому периоду
    if period == "today":
        # верхняя граница — now: событиям из будущего (сбитые часы устройства) тут не место
        events_now = _active_events(db, today, now)
        events_prev = _active_events(db, today - timedelta(days=1), today)
    else:
        days = 7 if period == "7d" else 30
        events_now = _active_events(db, now - timedelta(days=days), now)
        events_prev = _active_events(db, now - timedelta(days=2 * days), now - timedelta(days=days))

    # 3. Критические за 24 часа
    critical_24h = (
        db.scalar(
            select(func.count())
            .select_from(Event)
            .where(
                Event.ts > now - timedelta(hours=24),
                Event.severity == "critical",
                Event.status.in_(scoring.SCORED_STATUSES),
            )
        )
        or 0
    )

    # 4. Средний Score парка за окно периода + дельта
    days = _period_days(period)
    streaks = stats.streaks_by_driver(db, now)
    weights = stats.load_weights(db)
    cur = stats.scores_by_driver(db, now - timedelta(days=days), now, days, streaks, weights)
    prev = stats.scores_by_driver(
        db,
        now - timedelta(days=2 * days),
        now - timedelta(days=days),
        days,
        streaks,
        weights,
    )
    avg_now, avg_prev = stats.fleet_avg(cur), stats.fleet_avg(prev)

    # 5. Пробег за неделю + дельта к прошлой неделе
    km_now = sum(stats.km_by_driver(db, now - timedelta(days=7), now).values())
    km_prev = sum(
        stats.km_by_driver(db, now - timedelta(days=14), now - timedelta(days=7)).values()
    )
    km_delta_pct = round((km_now / km_prev - 1) * 100, 1) if km_prev else 0.0

    # 6. Аптайм устройств: полученные heartbeat'ы / ожидаемые за 7 дней. Считаем только
    # настоящие блоки в кабинах: телефоны (fw_version=web — менторы, жюри) шлют телеметрию
    # лишь пока открыта «Камера», и 40 таких «устройств» уронили бы KPI до 10 %
    real_ids = [d.id for d in devices if d.fw_version != "web"]
    beats = (
        db.scalar(
            select(func.count())
            .select_from(Heartbeat)
            .where(Heartbeat.ts > now - timedelta(days=7), Heartbeat.device_id.in_(real_ids))
        )
        or 0
        if real_ids
        else 0
    )
    expected = HEARTBEAT_EXPECTED_PER_DEVICE * len(real_ids)
    uptime = round(100 * beats / expected, 1) if expected else 100.0

    new_events = (
        db.scalar(select(func.count()).select_from(Event).where(Event.status == "new")) or 0
    )

    return {
        "period": period,
        "vehicles": {"online": online, "total": len(devices)},
        "events": {"value": events_now, "prev": events_prev, "delta": events_now - events_prev},
        "critical_24h": {"value": critical_24h},
        "avg_score": {
            "value": avg_now,
            "prev": avg_prev,
            "delta": avg_now - avg_prev,
            "target": 80,
            "zone": scoring.zone(avg_now),
        },
        "km_week": {"value": round(km_now), "delta_pct": km_delta_pct},
        "uptime": {"value": uptime, "active": online, "total": len(devices)},
        "badges": {"new_events": new_events},
    }


@router.get("/events-by-day")
def events_by_day(days: int = 7, db: Session = Depends(get_db)):
    now = datetime.now(UTC)
    today = local_midnight(now)  # день парка (Asia/Almaty), а не UTC
    since = today - timedelta(days=days - 1)
    rows = db.scalars(
        select(Event).where(Event.ts >= since, Event.status.in_(scoring.SCORED_STATUSES))
    ).all()
    buckets = {
        (today - timedelta(days=i)).date().isoformat(): {"critical": 0, "warning": 0, "info": 0}
        for i in range(days - 1, -1, -1)
    }
    for e in rows:
        key = local_date(e.ts).isoformat()
        if key in buckets:
            buckets[key][e.severity] += 1
    return [{"date": d, **counts} for d, counts in buckets.items()]


@router.get("/events-by-type")
def events_by_type(days: int = 7, db: Session = Depends(get_db)):
    now = datetime.now(UTC)
    rows = db.execute(
        select(Event.type, func.count())
        .where(Event.ts > now - timedelta(days=days), Event.status.in_(scoring.SCORED_STATUSES))
        .group_by(Event.type)
        .order_by(func.count().desc())
    ).all()
    total = sum(count for _, count in rows) or 1
    return [
        {"type": type_, "count": count, "share_pct": round(100 * count / total)}
        for type_, count in rows
    ]


@router.get("/critical-latest", response_model=list[EventOut])
def critical_latest(
    limit: int = 3,
    db: Session = Depends(get_db),
    user=Depends(require_roles("admin", "coordinator", "viewer")),
):
    now = datetime.now(UTC)
    events = db.scalars(
        select(Event)
        .where(
            Event.severity == "critical",
            Event.status.in_(scoring.SCORED_STATUSES),
            Event.ts <= now,  # события с «будущей» меткой (сбой часов устройства) не показываем
        )
        .options(joinedload(Event.driver).joinedload(Driver.vehicle))
        .order_by(Event.ts.desc(), Event.uuid.desc())
        .limit(min(limit, 20))
    ).all()
    out = [event_out(e) for e in events]
    for o in out:
        o.driver_phone = phone_for(user, o.driver_phone)  # SEC-5
    return out


@router.get("/red-zone")
def red_zone(db: Session = Depends(get_db)):
    """Водители с 30-дневным Score < 60 (окно — см. docs/decisions.md)."""
    now = datetime.now(UTC)
    streaks = stats.streaks_by_driver(db, now)
    month = stats.scores_by_driver(db, now - timedelta(days=30), now, 30, streaks)
    trips = stats.trips_count_by_driver(db, now - timedelta(days=30), now)
    drivers = {d.id: d for d in db.scalars(select(Driver)).all()}
    result = [
        {
            "driver_id": driver_id,
            "name": drivers[driver_id].name,
            "score": s.score,
            "trips_30d": trips.get(driver_id, 0),
        }
        for driver_id, s in month.items()
        if s.score < 60 and driver_id in drivers
    ]
    return sorted(result, key=lambda r: r["score"])
