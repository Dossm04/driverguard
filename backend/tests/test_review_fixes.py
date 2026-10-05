"""Регрессия фиксов код-ревью: RBAC, дубликаты справочников, дедуп retrain_queue."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app import security
from app.models import Driver, RetrainQueueItem, User
from app.security import hash_secret


def _driver_headers(client, db, phone="+77010000077"):
    user = User(
        role="driver",
        phone=phone,
        pin_hash=hash_secret("1234"),
        name="Тестов В.В.",
        created_at=datetime.now(UTC),
    )
    db.add(user)
    db.flush()
    driver = Driver(user_id=user.id, name="Тестов В.В.", phone=phone, created_at=datetime.now(UTC))
    db.add(driver)
    db.commit()
    security._pin_attempts.clear()
    token = client.post("/api/v1/auth/driver-login", json={"phone": phone, "pin": "1234"}).json()[
        "access_token"
    ]
    return {"Authorization": f"Bearer {token}"}, driver


def test_driver_cannot_read_fleet(client, db, base_fleet, admin_headers):
    """SEC-1: водителю недоступны лента событий, дашборд и чужие профили."""
    headers, driver = _driver_headers(client, db)
    assert client.get("/api/v1/events", headers=headers).status_code == 403
    assert client.get("/api/v1/dashboard/summary", headers=headers).status_code == 403
    other = base_fleet["driver"].id
    assert client.get(f"/api/v1/drivers/{other}/profile", headers=headers).status_code == 403
    own = client.get(f"/api/v1/drivers/{driver.id}/profile", headers=headers)
    assert own.status_code == 200
    # Чужой рейс водитель стартовать не может
    resp = client.post(
        "/api/v1/trips/start",
        json={"driver_id": other, "vehicle_id": base_fleet["vehicle"].id},
        headers=headers,
    )
    assert resp.status_code == 403


def test_duplicate_directory_entries_409(client, db, base_fleet, admin_headers):
    dup_vehicle = client.post(
        "/api/v1/vehicles",
        json={"plate": "KZ 4521 AB", "model": "КамАЗ"},
        headers=admin_headers,
    )
    assert dup_vehicle.status_code == 409
    dup_device = client.post(
        "/api/v1/devices", json={"serial": "DG-0001", "secret": "x"}, headers=admin_headers
    )
    assert dup_device.status_code == 409


def test_driver_phone_patch_syncs_login(client, db, admin_headers):
    headers, driver = _driver_headers(client, db, phone="+77010000078")
    resp = client.patch(
        f"/api/v1/drivers/{driver.id}",
        json={"phone": "+77010000099", "pin": "5678"},
        headers=admin_headers,
    )
    assert resp.status_code == 200
    security._pin_attempts.clear()
    old = client.post("/api/v1/auth/driver-login", json={"phone": "+77010000078", "pin": "5678"})
    assert old.status_code == 401  # старый номер больше не работает
    new = client.post("/api/v1/auth/driver-login", json={"phone": "+77010000099", "pin": "5678"})
    assert new.status_code == 200


def test_retrain_queue_dedupe_on_review_flips(client, db, base_fleet, admin_headers):
    ev = uuid.uuid4()
    client.post(
        "/api/v1/events",
        json=[
            {
                "uuid": str(ev),
                "device_serial": "DG-0001",
                "type": "microsleep",
                "severity": "critical",
                "confidence": 0.9,
                "ts": datetime.now(UTC).isoformat(),
                "speed_kmh": 80,
            }
        ],
        headers=admin_headers,
    )

    def review(new_status):
        r = client.post(
            f"/api/v1/events/{ev}/review", json={"status": new_status}, headers=admin_headers
        )
        assert r.status_code == 200

    review("false_positive")
    review("false_positive")  # повторное «ложное» не плодит дубликаты
    rows = db.scalars(select(RetrainQueueItem)).all()
    assert len(rows) == 1

    review("confirmed")  # возврат в confirmed чистит неэкспортированную очередь
    db.expire_all()
    assert db.scalars(select(RetrainQueueItem)).all() == []
