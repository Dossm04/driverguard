"""Машина состояний: микросон не при 1 с, но при 1.6 с; моргание — не микросон; cooldown и др."""

import pytest

from dg.config import Thresholds
from dg.rules import RuleEngine
from dg.signals import FrameSignals

FRAME_MS = 33  # ~30 FPS


@pytest.mark.parametrize("kind,signal,before", [
    ("phone", {"phone_conf": 0.9}, 1000),
    ("smoking", {"smoke_conf": 0.9}, 2000),
    ("head_nod", {"pitch": 0.2}, 1000),
    ("distraction", {"yaw": 0.6}, 7000),
])
def test_face_gap_breaks_continuous_episode(kind, signal, before):
    e = engine()
    first, t = run(e, 60 * FRAME_MS, before, speed_kmh=70, **signal)
    absent, t = run(e, t, 1500, face=False, speed_kmh=70)
    resumed, _ = run(e, t, 150, speed_kmh=70, **signal)
    assert not [d for d in first + absent + resumed if d.type == kind]


def test_face_gap_clears_stale_phone_alarm():
    e = engine()
    _, t = run(e, 60 * FRAME_MS, 2500, phone_conf=0.9, speed_kmh=70)
    assert e.phone_active
    run(e, t, 100, face=False, speed_kmh=70)
    assert not e.phone_active
    assert e.alert_level == 0


def engine(**overrides) -> RuleEngine:
    th = Thresholds(**overrides)
    e = RuleEngine(th=th, speed_limit=90)
    # калибровка: 60 кадров с открытыми глазами, ровной головой
    for i in range(th.CALIB_FRAMES):
        e.process(FrameSignals(t_ms=i * FRAME_MS, face=True, eye_close=0.05, ear=0.3, pitch=0.02, yaw=0.0))
    assert e.calibrated
    return e


def run(e: RuleEngine, start_ms: int, duration_ms: int, **sig):
    """Прогоняет кадры с одинаковыми сигналами; возвращает все детекции."""
    out = []
    t = start_ms
    while t < start_ms + duration_ms:
        base = {"face": True, "eye_close": 0.05, "ear": 0.3, "pitch": 0.02, "yaw": 0.0}
        base.update(sig)
        out += e.process(FrameSignals(t_ms=t, **base))
        t += FRAME_MS
    return out, t


def test_microsleep_needs_1500ms_not_1000ms():
    e = engine()
    t0 = 60 * FRAME_MS
    dets, t = run(e, t0, 1000, eye_close=0.9, ear=0.1)
    assert [d.type for d in dets] == []  # 1.0 с — ещё не микросон
    dets2, t = run(e, t, 700, eye_close=0.9, ear=0.1)  # суммарно ~1.7 с
    assert [d.type for d in dets2] == ["microsleep"]
    assert dets2[0].severity == "critical" and dets2[0].confidence >= 0.9
    assert e.alert_level == 2  # сирена
    # открыл глаза — сирена выключается, второго события нет
    dets3, _ = run(e, t, 500, eye_close=0.05)
    assert dets3 == [] and e.alert_level == 0 and not e.microsleep_active


def test_blink_is_not_microsleep_and_is_counted():
    e = engine()
    t0 = 60 * FRAME_MS
    dets, t = run(e, t0, 200, eye_close=0.9, ear=0.1)  # моргание 200 мс
    dets2, _ = run(e, t, 400, eye_close=0.05)
    assert dets + dets2 == []
    assert len(e._blinks) == 1


def test_single_frame_spike_is_debounced():
    e = engine()
    t0 = 60 * FRAME_MS
    e.process(FrameSignals(t_ms=t0, face=True, eye_close=0.95, ear=0.05, pitch=0.02))  # 1 кадр
    assert not e.eyes_closed
    dets, _ = run(e, t0 + FRAME_MS, 2000, eye_close=0.05)
    assert dets == []


def test_microsleep_cooldown_and_second_episode():
    e = engine()
    t0 = 60 * FRAME_MS
    dets, t = run(e, t0, 1700, eye_close=0.9, ear=0.1)
    assert [d.type for d in dets] == ["microsleep"]
    dets, t = run(e, t, 1000, eye_close=0.05)  # открыл
    dets2, t = run(e, t, 1700, eye_close=0.9, ear=0.1)  # сразу снова заснул — cooldown 5 с
    assert dets2 == []
    dets3, t = run(e, t, 6000, eye_close=0.05)
    dets4, _ = run(e, t, 1700, eye_close=0.9, ear=0.1)
    assert [d.type for d in dets4] == ["microsleep"]


def test_head_nod_after_2s():
    e = engine()
    t0 = 60 * FRAME_MS
    dets, t = run(e, t0, 1500, pitch=0.02 + 0.2)
    assert dets == []
    dets2, _ = run(e, t, 800, pitch=0.02 + 0.2)
    assert [d.type for d in dets2] == ["head_nod"] and dets2[0].severity == "warning"


def test_no_face_warning_then_sabotage_only_when_moving():
    e = engine(SABOTAGE_MS=10000)
    t0 = 60 * FRAME_MS
    dets, t = run(e, t0, 4000, face=False, speed_kmh=0)
    assert dets == [] and e.no_face_warning and e.alert_level == 1
    dets2, t = run(e, t, 8000, face=False, speed_kmh=0)  # стоим — саботажа нет
    assert dets2 == []
    e2 = engine(SABOTAGE_MS=10000)
    dets3, _ = run(e2, t0, 11000, face=False, speed_kmh=60)
    assert [d.type for d in dets3] == ["camera_sabotage"] and dets3[0].severity == "critical"


def test_distraction_requires_speed_and_escalates():
    e = engine()
    t0 = 60 * FRAME_MS
    dets, t = run(e, t0, 9000, yaw=0.6, speed_kmh=10)  # медленно — не отвлечение
    assert dets == []
    dets2, t = run(e, t0, 9000, yaw=0.6, speed_kmh=70)
    assert [d.type for d in dets2] == ["distraction"] and dets2[0].severity == "warning"
    dets3, _ = run(e, t, 7000, yaw=0.6, speed_kmh=70)
    assert [(d.type, d.severity) for d in dets3] == [("distraction", "critical")]


def test_speeding_after_10s_over_limit_with_value():
    e = engine()
    t0 = 60 * FRAME_MS
    dets, t = run(e, t0, 9000, speed_kmh=132)
    assert dets == []
    dets2, _ = run(e, t, 1500, speed_kmh=132)
    assert [d.type for d in dets2] == ["speeding"]
    assert dets2[0].value == 42 and dets2[0].severity == "critical"


def test_perclos_fatigue_with_cooldown():
    e = engine()
    t0 = 60 * FRAME_MS
    # 20 с: чередуем 0.6 с закрыто / 1.4 с открыто → PERCLOS ≈ 30 %
    dets = []
    t = t0
    for _ in range(12):
        d1, t = run(e, t, 600, eye_close=0.9, ear=0.1)
        d2, t = run(e, t, 1400, eye_close=0.05)
        dets += d1 + d2
    types = [d.type for d in dets]
    assert "fatigue" in types and types.count("fatigue") == 1  # cooldown 30 с
    assert "microsleep" not in types


def test_low_confidence_is_dropped():
    e = engine(MIN_CONFIDENCE=0.99)
    t0 = 60 * FRAME_MS
    dets, _ = run(e, t0, 3000, pitch=0.5)  # head_nod с confidence 0.8 < 0.99
    assert dets == []


def test_thresholds_update_from_backend():
    th = Thresholds()
    changed = th.update({"MICROSLEEP_MS": 2000, "PERCLOS_WARN": 0.25, "unknown": 1, "NOD_MS": None})
    assert set(changed) == {"MICROSLEEP_MS", "PERCLOS_WARN"} and th.MICROSLEEP_MS == 2000


def test_phone_requires_2s_and_siren_only_at_speed():
    e = engine()
    t0 = 60 * FRAME_MS
    dets, t = run(e, t0, 1500, phone_conf=0.9, speed_kmh=30)
    assert dets == []  # подтверждение ещё не набрано
    dets2, t = run(e, t, 700, phone_conf=0.9, speed_kmh=30)
    assert [d.type for d in dets2] == ["phone"] and e.alert_level == 1  # < 60 км/ч — мягкий алерт
    e2 = engine()
    d3, _ = run(e2, t0, 2300, phone_conf=0.9, speed_kmh=90)
    assert [d.type for d in d3] == ["phone"] and e2.alert_level == 2  # > 60 км/ч — сирена


def test_recalibration_after_face_returns():
    e = engine()
    t0 = 60 * FRAME_MS
    run(e, t0, 4000, face=False)  # лицо пропало > NOFACE_MS
    assert e.no_face_warning
    run(e, t0 + 4000, 100, pitch=0.3)  # вернулось с другим наклоном
    assert not e.calibrated  # калибровка перезапущена (DEV-14)


# ── детектор нарушений: телефон (DEV-8), курение (DEV-9), ремень (DEV-10) ──
def test_phone_needs_confirmation_and_speed():
    e = engine()
    t0 = 60 * FRAME_MS
    dets, t = run(e, t0, 1500, phone_conf=0.8, speed_kmh=70)
    assert dets == []  # 1.5 с < PHONE_MS
    dets, t = run(e, t, 800, phone_conf=0.8, speed_kmh=70)
    assert [d.type for d in dets] == ["phone"] and dets[0].severity == "critical" and e.alert_level == 2
    e2 = engine()
    dets, _ = run(e2, t0, 4000, phone_conf=0.9, speed_kmh=3)  # стоит — телефон допустим
    assert dets == []


def test_smoking_after_3s_not_2s():
    e = engine()
    t0 = 60 * FRAME_MS
    dets, t = run(e, t0, 2000, smoke_conf=0.7)
    assert dets == []
    dets, t = run(e, t, 1300, smoke_conf=0.7)
    assert [d.type for d in dets] == ["smoking"] and dets[0].severity == "warning"
    assert dets[0].confidence == 0.7 and e.alert_level == 1
    dets, _ = run(e, t, 1000, smoke_conf=0.0)
    assert dets == [] and e.alert_level == 0


def test_seatbelt_once_until_fastened_and_only_when_moving():
    e = engine()
    t0 = 60 * FRAME_MS
    dets, t = run(e, t0, 29000, seatbelt_off_conf=0.8, speed_kmh=40)
    assert dets == []
    dets, t = run(e, t, 2000, seatbelt_off_conf=0.8, speed_kmh=40)
    assert [d.type for d in dets] == ["seatbelt"] and dets[0].extra == {"beta": True}
    dets, t = run(e, t, 40000, seatbelt_off_conf=0.8, speed_kmh=40)  # всё ещё не пристёгнут — второго события нет
    assert dets == []
    dets, t = run(e, t, 1000, seatbelt_on_conf=0.9, speed_kmh=40)  # пристегнулся
    assert dets == []
    dets, t = run(e, t, 31000, seatbelt_off_conf=0.8, speed_kmh=40)  # снова снял → новое событие
    assert [d.type for d in dets] == ["seatbelt"]
    slow = engine()
    dets, _ = run(slow, t0, 35000, seatbelt_off_conf=0.8, speed_kmh=10)  # медленно — не считаем
    assert dets == []
    both = engine()
    dets, _ = run(both, t0, 35000, seatbelt_off_conf=0.6, seatbelt_on_conf=0.7, speed_kmh=40)  # «on» увереннее
    assert dets == []
