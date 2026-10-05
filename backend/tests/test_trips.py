"""Рейсы: BE-3 — старт/стоп/перерывы."""


def test_trip_lifecycle(client, base_fleet, admin_headers):
    body = {"driver_id": base_fleet["driver"].id, "vehicle_id": base_fleet["vehicle"].id}

    started = client.post("/api/v1/trips/start", json=body, headers=admin_headers)
    assert started.status_code == 201
    trip = started.json()
    assert trip["status"] == "active"

    # Второй активный рейс того же водителя запрещён
    dup = client.post("/api/v1/trips/start", json=body, headers=admin_headers)
    assert dup.status_code == 409

    brk = client.post(
        f"/api/v1/trips/{trip['id']}/breaks", json={"reason": "устал"}, headers=admin_headers
    )
    assert brk.status_code == 201
    ended_break = client.post(f"/api/v1/trips/{trip['id']}/breaks/end", headers=admin_headers)
    assert ended_break.status_code == 200

    stopped = client.post(f"/api/v1/trips/{trip['id']}/stop", headers=admin_headers)
    assert stopped.status_code == 200
    assert stopped.json()["status"] == "finished"
    assert stopped.json()["ended_at"] is not None
