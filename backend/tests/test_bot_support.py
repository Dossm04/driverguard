"""ШАГ 12: служебная учётка бота и комментарий review в аудите (BOT-1, SEC-4)."""

from sqlalchemy import select

from app.models import AuditLog
from app.seed import _event_uuid


def test_bot_account_reviews_with_comment(client, seeded, headers):
    login = client.post(
        "/api/v1/auth/login", json={"email": "bot@driverguard.kz", "password": "bot12345"}
    )
    assert login.status_code == 200 and login.json()["user"]["role"] == "coordinator"
    bot_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}

    target = _event_uuid("wk-0-1")
    resp = client.post(
        f"/api/v1/events/{target}/review",
        json={"status": "false_positive", "comment": "Telegram: Айгерим"},
        headers=bot_headers,
    )
    assert resp.status_code == 200 and resp.json()["status"] == "false_positive"
    audit = seeded.scalars(select(AuditLog).where(AuditLog.action == "event_review")).one()
    assert audit.after == {"status": "false_positive", "comment": "Telegram: Айгерим"}
    assert audit.user_id == login.json()["user"]["id"]

    too_long = client.post(
        f"/api/v1/events/{target}/review",
        json={"status": "confirmed", "comment": "x" * 201},
        headers=bot_headers,
    )
    assert too_long.status_code == 422
