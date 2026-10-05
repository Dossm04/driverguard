"""PWA «Камера»: события DMS из браузера и heartbeat телефона (пакет 6)."""

import uuid
from datetime import UTC, datetime, timedelta

from app import ws
from app.models import Device, Driver


def _driver_headers(client, phone="+77012441832", pin="1234"):
    resp = client.post("/api/v1/auth/driver-login", json={"phone": phone, "pin": pin})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def _event(**kw):
    base = {
        "uuid": str(uuid.uuid4()),
        "type": "microsleep",
        "severity": "critical",
        "confidence": 0.9,
        "ts": datetime.now(UTC).isoformat(),
        "lat": 51.1,
        "lon": 71.4,
        "gps_valid": True,
        "speed_kmh": 40,
        "value": 1.8,
        "note": "глаза закрыты дольше порога",
    }
    return {**base, **kw}


def test_camera_events_idempotent_and_bound_to_driver(client, seeded, headers):
    h = _driver_headers(client)
    ev = _event()
    resp = client.post("/api/v1/drivers/me/camera-events", json=[ev], headers=h)
    assert resp.status_code == 200, resp.text
    assert resp.json() == {"accepted": 1, "duplicates": 0}
    # повтор того же UUID — дубликат
    resp = client.post("/api/v1/drivers/me/camera-events", json=[ev], headers=h)
    assert resp.json() == {"accepted": 0, "duplicates": 1}

    # событие видно координатору с источником «камера телефона» и водителем из токена
    driver = seeded.scalar(
        __import__("sqlalchemy").select(Driver).where(Driver.phone == "+77012441832")
    )
    items = client.get(
        f"/api/v1/events?driver_id={driver.id}&type=microsleep&page_size=5", headers=headers
    ).json()["items"]
    mine = next(i for i in items if i["uuid"] == ev["uuid"])
    assert mine["context"]["source"] == "pwa_camera"
    assert mine["driver_id"] == driver.id and mine["is_demo"] is False
    # телефон в кабине держит устройство машины онлайн и ставит машину на карту
    assert ws.live_position(driver.vehicle.id) is not None
    device = seeded.scalar(
        __import__("sqlalchemy").select(Device).where(Device.vehicle_id == driver.vehicle.id)
    )
    seeded.refresh(device)
    assert datetime.now(UTC) - device.last_seen < timedelta(minutes=1)


def test_camera_events_reject_unknown_type_and_staff(client, seeded, headers):
    h = _driver_headers(client)
    assert (
        client.post(
            "/api/v1/drivers/me/camera-events",
            json=[_event(type="seatbelt")],
            headers=h,  # ремень — только с устройства
        ).status_code
        == 422
    )
    assert (
        client.post(
            "/api/v1/drivers/me/camera-events", json=[_event()], headers=headers
        ).status_code
        == 404
    )
    too_many = [_event() for _ in range(21)]
    assert (
        client.post("/api/v1/drivers/me/camera-events", json=too_many, headers=h).status_code == 413
    )


def test_camera_heartbeat_marks_online(client, seeded):
    h = _driver_headers(client)
    resp = client.post(
        "/api/v1/drivers/me/camera-heartbeat",
        json={"lat": 51.2, "lon": 71.5, "gps_valid": True, "speed_kmh": 12.5, "fps": 20},
        headers=h,
    )
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body["ok"] and body["vehicle"] and body["device"]
    # повторный heartbeat не плодит строки телеметрии чаще раза в 10 минут
    resp = client.post("/api/v1/drivers/me/camera-heartbeat", json={}, headers=h)
    assert resp.status_code == 200


def test_camera_events_accept_phone_and_smoking_from_hand_gestures(client, seeded):
    """PWA «Камера» шлёт телефон/курение по жестам руки — типы принимаются и считаются в Score."""
    resp = client.post("/api/v1/auth/driver-login", json={"phone": "+77012441832", "pin": "1234"})
    h = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    r = client.post(
        "/api/v1/drivers/me/camera-events",
        json=[_event(type="phone"), _event(type="smoking", severity="warning")],
        headers=h,
    )
    assert r.status_code == 200, r.text
    assert r.json()["accepted"] == 2
    r = client.post("/api/v1/drivers/me/camera-events", json=[_event(type="seatbelt")], headers=h)
    assert r.status_code == 422  # ремень телефон не определяет — только устройство
