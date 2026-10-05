"""Движок Driver Score — чистые функции (правило 5 CLAUDE.md = ТЗ 6.1.5).

Score = clamp(40..100, 100 − Σ(вес × модификатор_скорости) × 7/дней × 0.8 + бонус_серии(≤10)).
Учитываются только события status ∈ {new, confirmed}; false_positive возвращает баллы.
Округление — арифметическое (половина вверх), чтобы результат был воспроизводим.
"""

import math
from dataclasses import dataclass
from datetime import date, datetime

DEFAULT_WEIGHTS: dict[str, float] = {
    "microsleep": 15,
    "camera_sabotage": 20,
    "phone": 10,
    "distraction": 4,
    "seatbelt": 6,
    "head_nod": 5,
    "smoking": 4,
    "speeding": 3,
    "harsh_braking": 2,
    "fatigue": 2,
    "sos": 0,
}

# Модификаторы скорости (правило 5 CLAUDE.md)
FAST_KMH = 60  # phone/microsleep при >60 км/ч ×1.5
SLOW_KMH = 5  # phone при <5 км/ч ×0.3
FAST_MULT = 1.5
SLOW_MULT = 0.3
# Модификаторы скорости редактируются в Настройках (BE-15); ключи — как в Setting("scoring")
DEFAULT_MODIFIERS: dict[str, float] = {
    "fast_kmh": FAST_KMH,
    "fast_mult": FAST_MULT,
    "slow_kmh": SLOW_KMH,
    "slow_mult": SLOW_MULT,
}

SCORED_STATUSES = ("new", "confirmed")


@dataclass(frozen=True)
class ScoredEvent:
    """Минимум данных о событии, нужный скорингу."""

    type: str
    ts: datetime
    speed_kmh: float | None = None
    value: float | None = None
    status: str = "confirmed"
    severity: str = "warning"


def round_half_up(x: float) -> int:
    return math.floor(x + 0.5)


def event_weight(
    type_: str,
    speed_kmh: float | None = None,
    value: float | None = None,
    weights: dict[str, float] | None = None,
    modifiers: dict[str, float] | None = None,
) -> float:
    """Вес одного события с учётом величины превышения и модификатора скорости."""
    m = modifiers or DEFAULT_MODIFIERS
    w = float((weights or DEFAULT_WEIGHTS).get(type_, 0))
    if type_ == "speeding" and value is not None and value > 20:
        w += int((value - 20) // 10)  # +1 за каждые полные 10 км/ч сверх 20
    if type_ in ("phone", "microsleep") and speed_kmh is not None:
        if speed_kmh > float(m.get("fast_kmh", FAST_KMH)):
            w *= float(m.get("fast_mult", FAST_MULT))
    slow_kmh = float(m.get("slow_kmh", SLOW_KMH))
    if type_ == "phone" and speed_kmh is not None and speed_kmh < slow_kmh:
        w *= float(m.get("slow_mult", SLOW_MULT))
    return w


def penalty_sum(
    events: list[ScoredEvent],
    weights: dict[str, float] | None = None,
    modifiers: dict[str, float] | None = None,
) -> float:
    return sum(
        event_weight(e.type, e.speed_kmh, e.value, weights, modifiers)
        for e in events
        if e.status in SCORED_STATUSES
    )


def score(
    events: list[ScoredEvent],
    days: int,
    streak_days: int,
    weights: dict[str, float] | None = None,
    modifiers: dict[str, float] | None = None,
) -> int:
    """Score за окно в `days` дней; события должны быть уже отфильтрованы по окну."""
    penalty = penalty_sum(events, weights, modifiers)
    raw = 100 - penalty * (7 / days) * 0.8 + min(streak_days, 10)
    return max(40, min(100, round_half_up(raw)))


def streak_days(critical_dates: list[date], today: date, max_days: int = 365) -> int:
    """Серия: дни подряд (начиная с сегодня) без critical-событий.

    critical_dates — даты critical-событий со статусом new/confirmed.
    """
    critical = set(critical_dates)
    days = 0
    while days < max_days:
        d = date.fromordinal(today.toordinal() - days)
        if d in critical:
            break
        days += 1
    return days


def zone(value: int) -> str:
    """Цветовая зона Score: ≥85 зелёная, 70–84 жёлтая, <70 красная (ТЗ 6.1.5)."""
    if value >= 85:
        return "ok"
    if value >= 70:
        return "warn"
    return "danger"
