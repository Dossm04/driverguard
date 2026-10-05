"""Новичок: серия не длиннее стажа, в лидерборде — «новичок» в конце, в PWA — первая неделя."""

from datetime import UTC, datetime, timedelta

from app.models import Driver
from app.scoring import streak_days
from app.stats import streaks_by_driver


def test_streak_capped_by_tenure(db, base_fleet):
    veteran = base_fleet["driver"]
    veteran.created_at = datetime.now(UTC) - timedelta(days=400)
    rookie = Driver(name="Новиков Н.Н.", phone="+77010000099", created_at=datetime.now(UTC))
    db.add(rookie)
    db.commit()
    streaks = streaks_by_driver(db)
    assert streaks[rookie.id] == 0  # добавлен сегодня — ещё нет ни одного полного дня
    assert streaks[veteran.id] == 365  # без критических событий — максимум
    assert streak_days([], datetime.now(UTC).date()) == 365


def test_leaderboard_marks_newcomer_last(client, db, base_fleet, admin_headers):
    base_fleet["driver"].created_at = datetime.now(UTC) - timedelta(days=400)
    db.add(Driver(name="Новиков Н.Н.", phone="+77010000099", created_at=datetime.now(UTC)))
    db.commit()
    rows = client.get("/api/v1/leaderboard?period=7", headers=admin_headers).json()["rows"]
    assert [r["is_new"] for r in rows] == [False, True]
    assert rows[-1]["name"] == "Новиков Н.Н." and rows[-1]["streak"] == 0 and rows[-1]["rank"] == 2


def test_driver_me_first_week(client, db, base_fleet, admin_headers):
    r = client.post(
        "/api/v1/drivers",
        json={"name": "Новиков Н.Н.", "phone": "+77010000099", "pin": "4321"},
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    login = client.post("/api/v1/auth/driver-login", json={"phone": "+77010000099", "pin": "4321"})
    assert login.status_code == 200, login.text
    headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
    me = client.get("/api/v1/drivers/me", headers=headers)
    assert me.status_code == 200
    assert me.json()["score"]["is_new"] is True and me.json()["score"]["streak"] == 0
