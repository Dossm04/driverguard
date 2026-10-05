"""ШАГ 13: ручки PWA водителя — /drivers/me, рейс с перерывами, SOS, обучение (APP-2…APP-6)."""

from datetime import UTC, datetime

from app.seed import PHONES


def driver_login(client, index: int = 0) -> dict:
    resp = client.post("/api/v1/auth/driver-login", json={"phone": PHONES[index], "pin": "1234"})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


def test_driver_me_profile_has_pwa_fields(client, seeded):
    me = client.get("/api/v1/drivers/me", headers=driver_login(client)).json()
    assert me["driver"]["id"] == 1 and me["driver"]["vehicle"]["plate"] == "KZ 4521 AB"
    assert me["driver"]["vehicle"]["id"] == 1
    assert me["device"]["serial"] == "DG-0001" and me["device"]["online"] is True
    assert me["retention"]["clips_days"] == 90
    assert me["last_checklist"] is None or me["last_checklist"]["verdict"] in (
        "допущен",
        "требует_внимания",
        "не_допущен",
    )
    assert me["trainings"][0]["status"] == "assigned"
    assert me["driver"]["phone"] == PHONES[0]  # свой телефон водитель видит


def test_trip_flow_with_breaks(client, seeded):
    h = driver_login(client)
    me = client.get("/api/v1/drivers/me", headers=h).json()
    if me["active_trip"]:  # seed мог оставить активный рейс — закрываем
        assert (
            client.post(f"/api/v1/trips/{me['active_trip']['id']}/stop", headers=h).status_code
            == 200
        )
    started = client.post(
        "/api/v1/trips/start",
        json={"driver_id": 1, "vehicle_id": me["driver"]["vehicle"]["id"]},
        headers=h,
    )
    assert started.status_code == 201
    trip_id = started.json()["id"]
    me = client.get("/api/v1/drivers/me", headers=h).json()
    assert me["active_trip"]["id"] == trip_id and me["active_trip"]["break"] is None

    assert (
        client.post(
            f"/api/v1/trips/{trip_id}/breaks", json={"reason": "еда"}, headers=h
        ).status_code
        == 201
    )
    me = client.get("/api/v1/drivers/me", headers=h).json()
    assert me["active_trip"]["break"]["reason"] == "еда"
    assert client.post(f"/api/v1/trips/{trip_id}/breaks/end", headers=h).status_code == 200
    me = client.get("/api/v1/drivers/me", headers=h).json()
    assert me["active_trip"]["break"] is None and me["active_trip"]["last_break_end"] is not None

    assert client.post(f"/api/v1/trips/{trip_id}/stop", headers=h).status_code == 200
    assert client.get("/api/v1/drivers/me", headers=h).json()["active_trip"] is None
    # чужой рейс стартовать нельзя
    other = client.post("/api/v1/trips/start", json={"driver_id": 2, "vehicle_id": 2}, headers=h)
    assert other.status_code == 403


def test_sos_creates_critical_event_for_own_driver_only(client, seeded, headers):
    h = driver_login(client)
    resp = client.post(
        "/api/v1/drivers/1/sos",
        json={"reason": "Здоровье", "lat": 51.128, "lon": 71.43, "comment": "кружится голова"},
        headers=h,
    )
    assert resp.status_code == 201, resp.text
    ev = resp.json()
    assert ev["type"] == "sos" and ev["severity"] == "critical" and ev["driver_id"] == 1
    assert ev["vehicle_plate"] == "KZ 4521 AB" and ev["lat"] == 51.128 and ev["gps_valid"] is True
    assert ev["context"]["reason"] == "Здоровье"  # BOT-2: причина доходит до бота через API

    listed = client.get("/api/v1/events", params={"type": "sos"}, headers=headers).json()
    assert any(e["uuid"] == ev["uuid"] for e in listed["items"])
    full = client.get(f"/api/v1/events/{ev['uuid']}", headers=headers).json()
    assert full["status"] == "new"

    no_gps = client.post("/api/v1/drivers/1/sos", json={"reason": "Другое"}, headers=h).json()
    assert no_gps["gps_valid"] is False and no_gps["lat"] is None
    assert (
        client.post("/api/v1/drivers/2/sos", json={"reason": "ДТП"}, headers=h).status_code == 403
    )
    assert (
        client.post("/api/v1/drivers/1/sos", json={"reason": "Пожар"}, headers=h).status_code == 422
    )


def test_training_catalog_and_completion(client, seeded):
    h = driver_login(client)
    catalog = client.get("/api/v1/trainings", headers=h).json()
    assert [t["title"] for t in catalog][:1] == ["Управление усталостью"] and len(catalog) == 3
    me = client.get("/api/v1/drivers/me", headers=h).json()
    item = me["trainings"][0]
    done = client.post(f"/api/v1/drivers/1/trainings/{item['id']}/complete", headers=h)
    assert done.status_code == 200 and done.json()["status"] == "completed"
    assert (
        client.get("/api/v1/drivers/me", headers=h).json()["trainings"][0]["status"] == "completed"
    )
    # другой водитель не может закрыть чужой урок
    assert (
        client.post(
            f"/api/v1/drivers/1/trainings/{item['id']}/complete", headers=driver_login(client, 1)
        ).status_code
        == 403
    )
    assert (
        client.get("/api/v1/drivers/me", headers=driver_login(client, 1)).json()["driver"]["id"]
        == 2
    )


def test_device_heartbeat_km_and_events_attach_to_active_trip(client, seeded, headers):
    """Сквозная связка устройство → рейс: км из heartbeat и trip_id у событий без него."""
    from sqlalchemy import select

    from app.models import Event

    h = driver_login(client)
    me = client.get("/api/v1/drivers/me", headers=h).json()
    if me["active_trip"]:
        client.post(f"/api/v1/trips/{me['active_trip']['id']}/stop", headers=h)
    trip = client.post(
        "/api/v1/trips/start",
        json={
            "driver_id": 1,
            "vehicle_id": me["driver"]["vehicle"]["id"],
            "device_id": me["device"]["id"],
        },
        headers=h,
    ).json()
    token = client.post(
        "/api/v1/auth/device", json={"serial": "DG-0001", "secret": "device-secret-1"}
    ).json()["access_token"]
    dev_h = {"Authorization": f"Bearer {token}"}
    dev_id = me["device"]["id"]
    for delta in (12.4, 7.6):
        assert (
            client.post(
                f"/api/v1/devices/{dev_id}/heartbeat",
                json={"fps": 29, "trip_km_delta": delta},
                headers=dev_h,
            ).status_code
            == 200
        )
    me = client.get("/api/v1/drivers/me", headers=h).json()
    assert me["active_trip"]["distance_km"] == 20.0

    resp = client.post(
        "/api/v1/events",
        json=[
            {
                "uuid": "0d3c2b1a-1111-4222-8333-444455556666",
                "device_serial": "DG-0001",
                "type": "head_nod",
                "severity": "warning",
                "confidence": 0.8,
                "ts": datetime.now(UTC).isoformat(),  # рейс подбирается по времени события
                "gps_valid": False,
            }
        ],
        headers=dev_h,
    )
    assert resp.status_code == 200 and resp.json()["accepted"] == 1
    ev = seeded.scalar(select(Event).where(Event.type == "head_nod", Event.is_demo.is_(False)))
    assert ev.trip_id == trip["id"] and ev.driver_id == 1
    # без активного рейса — trip_id пустой
    client.post(f"/api/v1/trips/{trip['id']}/stop", headers=h)
    client.post(
        "/api/v1/events",
        json=[
            {
                **{
                    "uuid": "0d3c2b1a-1111-4222-8333-444455557777",
                    "device_serial": "DG-0001",
                    "type": "smoking",
                    "severity": "warning",
                    "confidence": 0.8,
                    "ts": datetime.now(UTC).isoformat(),
                    "gps_valid": False,
                }
            }
        ],
        headers=dev_h,
    )
    ev2 = seeded.scalar(select(Event).where(Event.type == "smoking", Event.is_demo.is_(False)))
    assert ev2.trip_id is None
