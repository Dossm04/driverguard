"""«Кто онлайн» (WEB-9): last_seen пишется при авторизованном запросе, online = ≤5 мин."""

from datetime import UTC, datetime, timedelta

from app.models import User


def test_last_seen_and_online_flag(client, admin, admin_headers, db):
    # Любой авторизованный запрос отмечает last_seen (не чаще раза в минуту)
    assert client.get("/api/v1/dashboard/summary", headers=admin_headers).status_code in (
        200,
        404,
    )
    rows = client.get("/api/v1/users", headers=admin_headers).json()
    me = next(r for r in rows if r["email"] == "admin@test.kz")
    assert me["last_seen"] is not None
    assert me["online"] is True

    # Учётка, которая давно не заходила, — офлайн
    db.add(
        User(
            role="viewer",
            email="old@test.kz",
            password_hash="x",
            name="Давно не был",
            created_at=datetime.now(UTC) - timedelta(days=30),
            last_seen=datetime.now(UTC) - timedelta(hours=2),
        )
    )
    db.commit()
    rows = client.get("/api/v1/users", headers=admin_headers).json()
    old = next(r for r in rows if r["email"] == "old@test.kz")
    assert old["online"] is False and old["last_seen"] is not None


def test_users_endpoint_admin_only(client, viewer_headers):
    assert client.get("/api/v1/users", headers=viewer_headers).status_code == 403
