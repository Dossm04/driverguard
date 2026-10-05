"""События: идемпотентный upsert (REL-3, TC-9), фильтры, пагинация."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select

from app.models import Event


def _event(uuid_, type_="microsleep", severity="critical", ts=None, **extra):
    return {
        "uuid": str(uuid_),
        "device_serial": "DG-0001",
        "type": type_,
        "severity": severity,
        "confidence": 0.95,
        "ts": (ts or datetime.now(UTC)).isoformat(),
        "lat": 50.05,
        "lon": 72.96,
        "speed_kmh": 84,
        "value": 1.8,
        **extra,
    }


def test_batch_upsert_idempotent(client, db, base_fleet, admin_headers):
    u1, u2 = uuid.uuid4(), uuid.uuid4()
    batch = [_event(u1), _event(u2, type_="speeding", severity="warning", value=25)]

    first = client.post("/api/v1/events", json=batch, headers=admin_headers)
    assert first.status_code == 200
    assert first.json() == {"accepted": 2, "duplicates": 0}

    # Повторная отправка того же батча — 200 и ноль новых строк
    second = client.post("/api/v1/events", json=batch, headers=admin_headers)
    assert second.status_code == 200
    assert second.json() == {"accepted": 0, "duplicates": 2}

    assert db.scalar(select(func.count()).select_from(Event)) == 2
    stored = db.get(Event, u1)
    # Водитель определился по устройству → машине → закреплённому водителю
    assert stored.driver_id == base_fleet["driver"].id


def test_device_token_can_send(client, db, base_fleet):
    token = client.post(
        "/api/v1/auth/device", json={"serial": "DG-0001", "secret": "secret-1"}
    ).json()["access_token"]
    resp = client.post(
        "/api/v1/events",
        json=[_event(uuid.uuid4())],
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200
    assert resp.json()["accepted"] == 1


def test_filters_and_pagination(client, db, base_fleet, admin_headers):
    now = datetime.now(UTC)
    batch = [
        _event(uuid.uuid4(), type_="microsleep", severity="critical", ts=now),
        _event(uuid.uuid4(), type_="speeding", severity="warning", ts=now, value=25),
        _event(uuid.uuid4(), type_="phone", severity="critical", ts=now - timedelta(days=10)),
    ]
    client.post("/api/v1/events", json=batch, headers=admin_headers)

    by_type = client.get(
        "/api/v1/events", params={"type": "speeding"}, headers=admin_headers
    ).json()
    assert by_type["total"] == 1
    assert by_type["items"][0]["type"] == "speeding"

    fresh = client.get(
        "/api/v1/events",
        params={"ts_from": (now - timedelta(days=1)).isoformat()},
        headers=admin_headers,
    ).json()
    assert fresh["total"] == 2

    paged = client.get(
        "/api/v1/events", params={"page": 2, "page_size": 2}, headers=admin_headers
    ).json()
    assert paged["total"] == 3
    assert len(paged["items"]) == 1

    by_status = client.get("/api/v1/events", params={"status": "new"}, headers=admin_headers).json()
    assert by_status["total"] == 3


def test_events_require_auth(client, base_fleet):
    assert client.get("/api/v1/events").status_code == 401
    assert client.post("/api/v1/events", json=[]).status_code == 401


def test_clip_url(client, db, base_fleet, admin_headers, monkeypatch):
    u = uuid.uuid4()
    client.post("/api/v1/events", json=[_event(u)], headers=admin_headers)

    # Несуществующее событие и событие без клипа — честный 404
    missing = client.get(f"/api/v1/events/{uuid.uuid4()}/clip-url", headers=admin_headers)
    assert missing.status_code == 404
    no_clip = client.get(f"/api/v1/events/{u}/clip-url", headers=admin_headers)
    assert no_clip.status_code == 404
    assert no_clip.json()["detail"] == "У события нет клипа"

    # Happy path: MinIO в тестах не поднимаем — подменяем подпись ссылки
    event = db.get(Event, u)
    event.clip_key = f"clips/DG-0001/2026-08/{u}.mp4"
    db.commit()
    monkeypatch.setattr(
        "app.storage.presigned_clip_download",
        lambda key, **kw: f"http://localhost:9000/clips/{key}?X-Amz-Signature=test",
    )
    ok = client.get(f"/api/v1/events/{u}/clip-url", headers=admin_headers)
    assert ok.status_code == 200
    assert ok.json() == {
        "url": f"http://localhost:9000/clips/clips/DG-0001/2026-08/{u}.mp4?X-Amz-Signature=test"
    }


def test_viewer_does_not_see_driver_phone_in_events(
    client, db, base_fleet, admin_headers, viewer_headers
):
    """SEC-5: телефон водителя в ответах событий скрыт от роли viewer."""
    u = uuid.uuid4()
    client.post("/api/v1/events", json=[_event(u)], headers=admin_headers)
    listed = client.get("/api/v1/events", headers=viewer_headers).json()["items"][0]
    single = client.get(f"/api/v1/events/{u}", headers=viewer_headers).json()
    assert listed["driver_phone"] is None and single["driver_phone"] is None
    as_admin = client.get(f"/api/v1/events/{u}", headers=admin_headers).json()
    assert as_admin["driver_phone"] == "+77010000001"
