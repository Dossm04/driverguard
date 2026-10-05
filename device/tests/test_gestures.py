"""Жесты рук: телефон у уха, сигарета у рта; курение по затяжкам (dg.gestures, dg.rules)."""

from dg.gestures import gestures_from_hands
from tests.test_rules import engine, run


class P:
    def __init__(self, x, y, z=0.0):
        self.x, self.y, self.z = x, y, z


def face_points():
    face = [P(0.5, 0.5) for _ in range(478)]
    face[234], face[454] = P(0.3, 0.5), P(0.7, 0.5)  # уши
    face[13], face[14] = P(0.5, 0.64), P(0.5, 0.66)  # губы
    return face


def hand(cx, cy):
    return [P(cx, cy) for _ in range(21)]


def test_palm_at_ear_is_phone_and_finger_at_mouth_is_smoke():
    face = face_points()
    g = gestures_from_hands(face, [hand(0.72, 0.52)])
    assert g.phone_conf >= 0.8 and g.smoke_conf == 0
    g = gestures_from_hands(face, [hand(0.5, 0.66)])
    assert g.smoke_conf >= 0.8 and g.phone_conf == 0
    assert gestures_from_hands(face, [hand(0.5, 0.95)]).phone_conf == 0
    assert gestures_from_hands(None, [hand(0.5, 0.66)]).smoke_conf == 0


def test_smoking_by_three_puffs_within_a_minute():
    e = engine()
    t = 60 * 33
    out = []
    for _ in range(3):
        d, t = run(e, t, 800, smoke_conf=0.8)
        out += d
        d, t = run(e, t, 5000)
        out += d
    assert [x.type for x in out] == ["smoking"] and out[0].note == "повторные затяжки"
    e2 = engine()
    d, _ = run(e2, 60 * 33, 1500, smoke_conf=0.8)
    assert d == []  # одна короткая затяжка — не событие
