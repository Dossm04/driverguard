import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.models import AuditLog, Driver, Event
from app.scoring import event_weight
from tests.test_native_measurements import driver_headers, native_event


def test_manual_rest_is_neutral_and_retry_safe(client, seeded):
    auth = driver_headers(client)
    for kind in ("rest_started", "rest_ended"):
        event = native_event(type=kind, detector="driver_action", value=90)
        response = client.post("/api/v1/drivers/me/camera-events", json=[event], headers=auth)
        assert response.status_code == 200, response.text
        stored = seeded.get(Event, uuid.UUID(event["uuid"]))
        assert stored.severity == "info" and stored.confidence == 0
        assert event_weight(kind, weights={kind: 99}) == 0
        assert (
            client.post("/api/v1/drivers/me/camera-events", json=[event], headers=auth).json()[
                "duplicates"
            ]
            == 1
        )
        invalid = {**event, "uuid": str(uuid.uuid4()), "detector": "face_rules"}
        assert (
            client.post(
                "/api/v1/drivers/me/camera-events", json=[invalid], headers=auth
            ).status_code
            == 422
        )


def test_feedback_is_owner_scoped_idempotent_and_does_not_rewrite_event(client, seeded):
    auth = driver_headers(client)
    event = native_event()
    assert (
        client.post("/api/v1/drivers/me/camera-events", json=[event], headers=auth).status_code
        == 200
    )
    path = f"/api/v1/drivers/me/camera-events/{event['uuid']}/feedback"
    body = {
        "request_id": str(uuid.uuid4()),
        "comment": "Глаза были открыты, прошу проверить",
        "ts": datetime.now(UTC).isoformat(),
    }
    assert client.put(path, json=body).status_code == 401
    for _ in range(2):
        result = client.put(path, json=body, headers=auth)
        assert result.status_code == 200, result.text
        assert result.json() == {"ok": True, "request_id": body["request_id"]}
    seeded.expire_all()
    stored = seeded.get(Event, uuid.UUID(event["uuid"]))
    assert stored.status == "new" and stored.severity == "critical"
    assert stored.measurements == event["measurements"]
    assert stored.context["driver_feedback"]["comment"] == body["comment"]
    assert (
        seeded.scalar(
            select(func.count())
            .select_from(AuditLog)
            .where(AuditLog.action == "driver_event_feedback")
        )
        == 1
    )
    assert (
        client.put(path, json={**body, "request_id": str(uuid.uuid4())}, headers=auth).status_code
        == 409
    )
    assert client.put(path, json={**body, "comment": " "}, headers=auth).status_code == 422
    other = seeded.scalar(select(Driver).where(Driver.id != stored.driver_id))
    stored.driver_id = other.id
    seeded.commit()
    assert client.put(path, json=body, headers=auth).status_code == 404
