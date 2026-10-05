"""Аудит (домен): устройство говорит за себя, рейс по времени события, heartbeat, PATCH водителя."""

from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app.models import Event
from app.seed import PHONES


def _driver(client, i=0):
    r = client.post("/api/v1/auth/driver-login", json={"phone": PHONES[i], "pin": "1234"})
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _device(client, n=1):
    r = client.post(
        "/api/v1/auth/device", json={"serial": f"DG-000{n}", "secret": f"device-secret-{n}"}
    )
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def _event(uuid, **kw):
    return {
        "uuid": uuid,
        "type": "head_nod",
        "severity": "warning",
        "confidence": 0.8,
        "ts": datetime.now(UTC).isoformat(),
        "gps_valid": False,
        **kw,
    }


def test_device_cannot_spoof_serial_or_driver(client, seeded, headers):
    dh = _device(client, 1)  # машина Иванова (driver 1)
    r = client.post(
        "/api/v1/events",
        json=[_event("a1a1a1a1-0000-4000-8000-000000000001", device_serial="DG-0003", driver_id=3)],
        headers=dh,
    )
    assert r.status_code == 200 and r.json()["accepted"] == 1
    ev = seeded.scalar(select(Event).where(Event.uuid == "a1a1a1a1-0000-4000-8000-000000000001"))
    assert ev.driver_id == 1 and ev.device_id == 1  # не 3
    # сотрудник может указать серийник явно
    r2 = client.post(
        "/api/v1/events",
        json=[_event("a1a1a1a1-0000-4000-8000-000000000002", device_serial="DG-0003")],
        headers=headers,
    )
    assert r2.status_code == 200
    ev2 = seeded.scalar(select(Event).where(Event.uuid == "a1a1a1a1-0000-4000-8000-000000000002"))
    assert ev2.driver_id == 3


def test_offline_event_attaches_to_trip_active_at_event_time(client, seeded, headers):
    h = _driver(client)
    me = client.get("/api/v1/drivers/me", headers=h).json()
    if me["active_trip"]:
        client.post(f"/api/v1/trips/{me['active_trip']['id']}/stop", headers=h)
    trip = client.post(
        "/api/v1/trips/start",
        json={"driver_id": 1, "vehicle_id": me["driver"]["vehicle"]["id"]},
        headers=h,
    ).json()
    started = datetime.fromisoformat(trip["started_at"])
    assert client.post(f"/api/v1/trips/{trip['id']}/stop", headers=h).status_code == 200
    dh = _device(client, 1)
    inside = (started + timedelta(milliseconds=1)).isoformat()  # рейс длился доли секунды
    before = (started - timedelta(hours=2)).isoformat()
    client.post(
        "/api/v1/events",
        json=[
            _event("b1b1b1b1-0000-4000-8000-000000000001", ts=inside),
            _event("b1b1b1b1-0000-4000-8000-000000000002", ts=before),
        ],
        headers=dh,
    )
    ev_in = seeded.scalar(select(Event).where(Event.uuid == "b1b1b1b1-0000-4000-8000-000000000001"))
    ev_out = seeded.scalar(
        select(Event).where(Event.uuid == "b1b1b1b1-0000-4000-8000-000000000002")
    )
    assert ev_in.trip_id == trip["id"]
    assert ev_out.trip_id != trip["id"]


def test_heartbeat_validation_and_device_time(client, seeded, headers):
    dh = _device(client, 1)
    bad = client.post("/api/v1/devices/1/heartbeat", json={"fps": "много"}, headers=dh)
    assert bad.status_code == 422
    old = (datetime.now(UTC) - timedelta(hours=3)).isoformat()
    ok = client.post(
        "/api/v1/devices/1/heartbeat", json={"ts": old, "fps": 28.5, "trip_km_delta": 0}, headers=dh
    )
    assert ok.status_code == 200
    dev = next(d for d in client.get("/api/v1/devices", headers=headers).json() if d["id"] == 1)
    assert dev["online"] is True  # last_seen — серверное «сейчас», не старый ts


def test_trips_validation(client, seeded, headers):
    assert client.get("/api/v1/trips", params={"limit": -1}, headers=headers).status_code == 422
    r = client.post(
        "/api/v1/trips/start", json={"driver_id": 1, "vehicle_id": 999}, headers=headers
    )
    assert r.status_code == 404
    assert (
        client.post(
            "/api/v1/drivers", json={"name": "Тест Т.Т.", "depot_id": 99}, headers=headers
        ).status_code
        == 404
    )


def test_patch_driver_with_phone_creates_pwa_account(client, seeded, headers):
    created = client.post(
        "/api/v1/drivers", json={"name": "Новый Н.Н.", "depot_id": 1}, headers=headers
    ).json()
    assert created["phone"] is None
    r = client.patch(
        f"/api/v1/drivers/{created['id']}",
        json={"phone": "+77770001122", "pin": "4321"},
        headers=headers,
    )
    assert r.status_code == 200
    login = client.post("/api/v1/auth/driver-login", json={"phone": "+77770001122", "pin": "4321"})
    assert login.status_code == 200 and login.json()["driver_id"] == created["id"]


def test_checklist_requires_base_answers(client, seeded, headers):
    files = {
        slot: (f"{slot}.png", b"\x89PNG\r\n\x1a\n" + b"0" * 64, "image/png")
        for slot in (
            "front_lights",
            "rear_lights",
            "left_side",
            "right_side",
            "tires",
            "windshield",
            "under_engine",
        )
    }
    r = client.post(
        "/api/v1/checklists", files=files, data={"answers": "{}", "driver_id": "1"}, headers=headers
    )
    assert r.status_code == 422 and "обязательные пункты" in r.json()["detail"]
