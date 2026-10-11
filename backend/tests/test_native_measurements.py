"""Native offline event observations survive ingestion, deduplication and presentation."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select

from app import ws
from app.models import Driver, Event
from app.routers.events import ws_manager


def driver_headers(client):
    response = client.post(
        "/api/v1/auth/driver-login", json={"phone": "+77012441832", "pin": "1234"}
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def native_event(**changes):
    return {
        "uuid": str(uuid.uuid4()), "type": "microsleep", "severity": "critical",
        "confidence": 0, "ts": (datetime.now(UTC) - timedelta(hours=2)).isoformat(),
        "gps_valid": False, "value": 1.7, "source": "android_camera",
        "detector": "face_rules", "note": "Проверка передачи измерений",
        "measurements": {
            "rule_version": "dms-0.6", "closed_ms": 1700, "ear": 0.12,
            "ear_baseline": 0.3, "blink_count_60s": 7, "perclos_pct": 21.5,
            "valid_observation_ms": 54_000, "coverage_pct": 90, "yawns_10min": 3,
            "jaw_open_ms": 0, "head_delta": 0.053, "yaw_delta": -0.082,
            "away_ms": 0, "missing_ms": 0, "sample_latency_ms": 57,
        }, **changes,
    }


def test_capabilities_require_driver_login_and_advertise_preserved_measurements(
    client, seeded, headers,
):
    response = client.get("/api/v1/drivers/me/camera-capabilities")
    assert response.status_code == 401
    response = client.get("/api/v1/drivers/me/camera-capabilities", headers=headers)
    assert response.status_code == 404
    response = client.get(
        "/api/v1/drivers/me/camera-capabilities", headers=driver_headers(client),
    )
    assert response.status_code == 200
    assert response.json() == {"measurements_version": 1, "gps_rules": True}


def test_native_readings_persist_across_retry_list_profile_and_live_event(
    client, seeded, headers, monkeypatch,
):
    messages = []
    monkeypatch.setattr(ws_manager, "broadcast_threadsafe", messages.append)
    auth = driver_headers(client)
    event = native_event()
    old_event = native_event(measurements=None, source="pwa_camera", detector=None)
    response = client.post(
        "/api/v1/drivers/me/camera-events", json=[event, old_event], headers=auth,
    )
    assert response.status_code == 200, response.text
    assert response.json() == {"accepted": 2, "duplicates": 0}
    stored = seeded.get(Event, uuid.UUID(event["uuid"]))
    assert stored.measurements == event["measurements"]
    assert stored.ts == datetime.fromisoformat(event["ts"])
    assert stored.context["source"] == "android_camera"
    assert stored.context["confidence_status"] == "uncalibrated"
    assert stored.is_demo is False
    assert seeded.get(Event, uuid.UUID(old_event["uuid"])).measurements is None

    # Retrying an offline UUID cannot replace its original observation snapshot.
    modified_retry = {**event, "measurements": {"closed_ms": 9999}}
    retry = client.post(
        "/api/v1/drivers/me/camera-events", json=[modified_retry], headers=auth,
    )
    assert retry.json() == {"accepted": 0, "duplicates": 1}
    seeded.refresh(stored)
    assert stored.measurements == event["measurements"]

    items = client.get("/api/v1/events?page_size=100", headers=headers).json()["items"]
    item = next(value for value in items if value["uuid"] == event["uuid"])
    own_items = client.get("/api/v1/drivers/me", headers=auth).json()["recent_events"]
    own = next(value for value in own_items if value["uuid"] == event["uuid"])
    broadcast = next(
        value["event"] for value in messages if value["event"]["uuid"] == event["uuid"]
    )
    for presented in (item, own, broadcast):
        observed = {k: v for k, v in presented["measurements"].items() if v is not None}
        assert observed == event["measurements"]
        assert presented["context"]["confidence_status"] == "uncalibrated"


def test_native_speeding_retains_actual_gps_and_rejects_false_fix(client, seeded, headers):
    auth = driver_headers(client)
    event = native_event(
        type="speeding", severity="warning", detector="gps_rules", gps_valid=True,
        lat=51.1, lon=71.4, speed_kmh=72.5, value=12.5,
        measurements={"rule_version": "dms-0.6", "speed_limit_kmh": 60},
    )
    response = client.post("/api/v1/drivers/me/camera-events", json=[event], headers=auth)
    assert response.status_code == 200, response.text
    stored = seeded.get(Event, uuid.UUID(event["uuid"]))
    assert stored.gps_valid and stored.speed_kmh == 72.5 and stored.value == 12.5
    assert stored.measurements["speed_limit_kmh"] == 60
    event["uuid"] = str(uuid.uuid4())
    event["gps_valid"] = False
    rejected = client.post("/api/v1/drivers/me/camera-events", json=[event], headers=auth)
    assert rejected.status_code == 422
    assert seeded.get(Event, uuid.UUID(event["uuid"])) is None


def test_invalid_location_does_not_move_vehicle_from_latest_valid_fix(client, seeded):
    auth = driver_headers(client)
    driver = seeded.scalar(select(Driver).where(Driver.phone == "+77012441832"))
    ws.set_live_position(driver.vehicle.id, 51.1, 71.4, 12)
    response = client.post(
        "/api/v1/drivers/me/camera-events",
        json=[native_event(lat=0, lon=0, gps_valid=False)], headers=auth,
    )
    assert response.status_code == 200, response.text
    before = ws.live_position(driver.vehicle.id)
    response = client.post(
        "/api/v1/drivers/me/camera-heartbeat",
        json={"lat": 1, "lon": 1, "gps_valid": False}, headers=auth,
    )
    assert response.status_code == 200, response.text
    assert ws.live_position(driver.vehicle.id) == before
    assert before == (51.1, 71.4, 12)
