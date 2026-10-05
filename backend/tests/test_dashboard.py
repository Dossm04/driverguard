"""ШАГ 3: dashboard/leaderboard/review/WS на полном seed'е.

Главный тест: /dashboard/summary на seed-данных возвращает РОВНО цифры Figma
(правило 3 CLAUDE.md): 5/6, 14 (+3 к 11), 3, 78 (−2, цель 80), 12 480 (+4.2%), 98.2.
"""

import pytest

from app.seed import _event_uuid


def test_summary_matches_figma(client, headers):
    s = client.get("/api/v1/dashboard/summary", params={"period": "today"}, headers=headers)
    assert s.status_code == 200
    body = s.json()
    assert body["vehicles"] == {"online": 5, "total": 6}
    assert body["events"] == {"value": 14, "prev": 11, "delta": 3}
    assert body["critical_24h"]["value"] == 3
    assert body["avg_score"]["value"] == 78
    assert body["avg_score"]["delta"] == -2
    assert body["km_week"]["value"] == 12480
    assert body["km_week"]["delta_pct"] == 4.2
    assert body["uptime"]["value"] == 98.2
    assert body["uptime"]["active"] == 5
    assert body["badges"]["new_events"] == 3


def test_red_zone_matches_figma(client, headers):
    rz = client.get("/api/v1/dashboard/red-zone", headers=headers).json()
    assert [(r["name"], r["score"], r["trips_30d"]) for r in rz] == [
        ("Иванов А.С.", 41, 12),
        ("Петров Д.В.", 53, 9),
        ("Сейткали М.", 56, 7),
    ]


def test_critical_latest_heroes(client, headers):
    latest = client.get("/api/v1/dashboard/critical-latest", headers=headers).json()
    assert [e["type"] for e in latest] == ["distraction", "speeding", "microsleep"]
    assert latest[2]["driver_name"] == "Иванов А.С."
    assert latest[2]["vehicle_plate"] == "KZ 4521 AB"
    assert latest[1]["value"] == 42  # «Превышение скорости +42 км/ч»


def test_events_by_type_speeding_share(client, headers):
    types = client.get("/api/v1/dashboard/events-by-type", headers=headers).json()
    share = {t["type"]: t["share_pct"] for t in types}
    assert share["speeding"] == 27


def test_events_by_day_shape(client, headers):
    days = client.get("/api/v1/dashboard/events-by-day", headers=headers).json()
    assert len(days) == 7
    today = days[-1]
    assert today["critical"] == 3
    assert today["warning"] == 11
    yesterday = days[-2]
    assert yesterday["critical"] == 0
    assert yesterday["warning"] == 11


def test_leaderboard_sorting_and_scores(client, headers):
    lb = client.get("/api/v1/leaderboard", params={"period": "7"}, headers=headers).json()
    rows = lb["rows"]
    assert [r["score"] for r in rows] == [95, 93, 90, 70, 65, 55]
    assert rows[0]["name"] == "Ким С.В."
    assert rows[0]["streak"] >= 14
    assert "week_no_risk" in rows[0]["badges"]
    assert rows[-1]["name"] == "Иванов А.С."
    assert {d["name"] for d in lb["depots"]} == {"Астана", "Караганда"}
    # Зону депо считает сервер — фронт цветит бары по ней, а не своими порогами
    assert all(d["zone"] in {"ok", "warn", "danger"} for d in lb["depots"])
    # Ранги сквозные
    assert [r["rank"] for r in rows] == [1, 2, 3, 4, 5, 6]


def test_review_false_positive_returns_points(client, seeded, headers):
    """US-7/П-6: «ложное» возвращает баллы и создаёт запись в retrain_queue."""
    from sqlalchemy import select

    from app.models import AuditLog, RetrainQueueItem

    before = client.get("/api/v1/leaderboard", headers=headers).json()["rows"]
    ivanov_before = next(r for r in before if r["name"] == "Иванов А.С.")["score"]
    assert ivanov_before == 55

    # Микросон Иванова двухдневной давности (вес 22.5): uuid детерминированный
    target = _event_uuid("wk-0-1")
    resp = client.post(
        f"/api/v1/events/{target}/review", json={"status": "false_positive"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "false_positive"

    after = client.get("/api/v1/leaderboard", headers=headers).json()["rows"]
    ivanov_after = next(r for r in after if r["name"] == "Иванов А.С.")["score"]
    # 55 → 100 − (56−22.5)×0.8 = 73.2 → 73
    assert ivanov_after == 73

    queue = seeded.scalars(select(RetrainQueueItem)).all()
    assert len(queue) == 1 and queue[0].event_uuid == target
    audit = seeded.scalars(select(AuditLog).where(AuditLog.action == "event_review")).all()
    assert len(audit) == 1


def test_confirm_review(client, seeded, headers):
    target = _event_uuid("wk-1-2")  # телефон Петрова, статус confirmed → confirmed остаётся
    resp = client.post(
        f"/api/v1/events/{target}/review", json={"status": "confirmed"}, headers=headers
    )
    assert resp.status_code == 200
    assert resp.json()["status"] == "confirmed"


def test_driver_profile(client, headers):
    profile = client.get("/api/v1/drivers/1/profile", headers=headers).json()
    assert profile["driver"]["name"] == "Иванов А.С."
    assert profile["driver"]["vehicle"]["plate"] == "KZ 4521 AB"
    assert profile["score"]["value"] == 55
    assert len(profile["score_by_week"]) == 8
    assert profile["score_by_week"][-1]["score"] == 55
    assert profile["trainings"][0]["title"] == "Управление усталостью"
    assert len(profile["recent_events"]) == 10


def test_assign_training(client, headers):
    resp = client.post("/api/v1/drivers/2/trainings", json={}, headers=headers)
    assert resp.status_code == 201
    assert resp.json()["training"] == "Управление усталостью"
    profile = client.get("/api/v1/drivers/2/profile", headers=headers).json()
    assert profile["trainings"][0]["status"] == "assigned"


def test_ws_live_positions(client, headers):
    token = headers["Authorization"].split()[1]
    with client.websocket_connect(f"/ws/live?token={token}") as ws:
        msg = ws.receive_json()
    assert msg["type"] == "positions"
    assert len(msg["vehicles"]) == 6
    plates = {v["plate"] for v in msg["vehicles"]}
    assert "KZ 4521 AB" in plates
    offline = [v for v in msg["vehicles"] if v["status"] == "offline"]
    assert len(offline) == 1 and offline[0]["driver_name"] == "Сапаров Д.Н."


def test_ws_rejects_without_token(client, seeded):
    from starlette.websockets import WebSocketDisconnect

    with pytest.raises(WebSocketDisconnect):
        with client.websocket_connect("/ws/live") as ws:
            ws.receive_json()
