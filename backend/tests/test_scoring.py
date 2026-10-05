"""Юнит-тесты движка Score: каждый вес, каждый модификатор (правило 5 CLAUDE.md)."""

from datetime import UTC, date, datetime

import pytest

from app.scoring import (
    DEFAULT_WEIGHTS,
    ScoredEvent,
    event_weight,
    penalty_sum,
    round_half_up,
    score,
    streak_days,
    zone,
)

TS = datetime(2026, 8, 31, 12, 0, tzinfo=UTC)


@pytest.mark.parametrize(
    ("type_", "weight"),
    [
        ("microsleep", 15),
        ("camera_sabotage", 20),
        ("phone", 10),
        ("distraction", 4),
        ("seatbelt", 6),
        ("head_nod", 5),
        ("smoking", 4),
        ("speeding", 3),
        ("harsh_braking", 2),
        ("fatigue", 2),
        ("sos", 0),
    ],
)
def test_base_weights(type_, weight):
    assert event_weight(type_, speed_kmh=30) == weight
    assert DEFAULT_WEIGHTS[type_] == weight


def test_speeding_extra_weight():
    """+1 за каждые полные 10 км/ч сверх +20."""
    assert event_weight("speeding", value=20) == 3
    assert event_weight("speeding", value=25) == 3
    assert event_weight("speeding", value=30) == 4
    assert event_weight("speeding", value=42) == 5
    assert event_weight("speeding", value=55) == 6


def test_fast_modifier():
    """phone/microsleep при >60 км/ч ×1.5."""
    assert event_weight("phone", speed_kmh=61) == 15
    assert event_weight("microsleep", speed_kmh=84) == 22.5
    assert event_weight("microsleep", speed_kmh=60) == 15  # ровно 60 — без модификатора
    assert event_weight("smoking", speed_kmh=90) == 4  # другие типы не ускоряются


def test_slow_phone_modifier():
    """phone при <5 км/ч ×0.3 (TC-5)."""
    assert event_weight("phone", speed_kmh=3) == 3
    assert event_weight("phone", speed_kmh=5) == 10


def test_false_positive_excluded():
    events = [
        ScoredEvent("microsleep", TS, 80, status="confirmed"),
        ScoredEvent("microsleep", TS, 80, status="false_positive"),
        ScoredEvent("phone", TS, 70, status="new"),
    ]
    assert penalty_sum(events) == 22.5 + 15


def test_score_formula_and_clamp():
    # Пустая неделя, серия 3 → 100 (clamp сверху)
    assert score([], days=7, streak_days=3) == 100
    # Тяжёлая неделя → clamp снизу 40
    heavy = [ScoredEvent("camera_sabotage", TS, 50)] * 10
    assert score(heavy, days=7, streak_days=0) == 40
    # Бонус серии ограничен 10
    one = [ScoredEvent("microsleep", TS, 50)]  # штраф 15×0.8 = 12
    assert score(one, days=7, streak_days=25) == 98  # 100 − 12 + 10


def test_round_half_up():
    assert round_half_up(54.5) == 55  # не банковское округление
    assert round_half_up(54.4) == 54
    assert round_half_up(-0.5) == 0


def test_streak():
    today = date(2026, 8, 31)
    assert streak_days([], today) == 365
    assert streak_days([today], today) == 0
    assert streak_days([date(2026, 8, 26)], today) == 5
    assert streak_days([date(2026, 8, 26), date(2026, 8, 29)], today) == 2


def test_zones():
    assert zone(85) == "ok"
    assert zone(84) == "warn"
    assert zone(70) == "warn"
    assert zone(69) == "danger"
