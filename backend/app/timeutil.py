"""Границы «дня» — по часовому поясу парка (Asia/Almaty), а не по UTC.

Координатор в Астане в 02:00 ночи должен видеть «сегодня» как свой календарный день:
события с 19:00 UTC вчера уже относятся к сегодняшнему дню. Все окна «сегодня/вчера/по дням»
и серии дней без нарушений считаются через эти функции — единая точка правды для backend,
seed и тестов.
"""

from datetime import UTC, date, datetime
from functools import lru_cache
from zoneinfo import ZoneInfo

from app.config import get_settings


@lru_cache
def tz() -> ZoneInfo:
    return ZoneInfo(get_settings().app_tz)


def local_midnight(now: datetime) -> datetime:
    """Полночь текущего локального дня (aware-datetime в поясе парка; сравнима с UTC)."""
    return now.astimezone(tz()).replace(hour=0, minute=0, second=0, microsecond=0)


def local_date(dt: datetime) -> date:
    if dt.tzinfo is None:  # SQLite/наивные значения трактуем как UTC
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(tz()).date()
