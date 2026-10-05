"""Очередь дообучения (ML-5): выгрузка ложных срабатываний, отметка об экспорте, RBAC,
heartbeat model_version."""

import uuid
from datetime import UTC, datetime

from sqlalchemy import select

from app.models import AuditLog, Device


def _post_event(client, headers, ev_type="phone"):
    ev = uuid.uuid4()
    r = client.post(
        "/api/v1/events",
        json=[
            {
                "uuid": str(ev),
                "device_serial": "DG-0001",
                "type": ev_type,
                "severity": "critical",
                "confidence": 0.91,
                "ts": datetime.now(UTC).isoformat(),
                "speed_kmh": 72,
                "model_version": "coco-yolov8n",
            }
        ],
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return ev


def test_queue_lists_false_positives_and_marks_exported(client, db, base_fleet, admin_headers):
    device = base_fleet["device"]
    client.post(
        f"/api/v1/devices/{device.id}/heartbeat",
        json={"model_version": "coco-yolov8n"},
        headers=admin_headers,
    )
    ev = _post_event(client, admin_headers)
    assert client.get("/api/v1/retrain-queue", headers=admin_headers).json()["total"] == 0
    r = client.post(
        f"/api/v1/events/{ev}/review", json={"status": "false_positive"}, headers=admin_headers
    )
    assert r.status_code == 200

    data = client.get("/api/v1/retrain-queue", headers=admin_headers).json()
    assert data["total"] == 1
    item = data["items"][0]
    assert (
        item["event_uuid"] == str(ev)
        and item["label_hint"] == "phone"
        and item["event_type"] == "phone"
    )
    assert item["driver_name"] == "Иванов А.С." and item["vehicle_plate"] == "KZ 4521 AB"
    assert (
        item["model_version"] == "coco-yolov8n"
        and item["clip_url"] is None
        and item["exported_at"] is None
    )

    r = client.post(
        "/api/v1/retrain-queue/mark-exported",
        json={"ids": [item["id"], 999]},
        headers=admin_headers,
    )
    assert r.status_code == 200 and r.json() == {"exported": 1, "ids": [item["id"]]}
    assert client.get("/api/v1/retrain-queue", headers=admin_headers).json()["total"] == 0
    exported = client.get("/api/v1/retrain-queue?exported=true", headers=admin_headers).json()
    assert exported["total"] == 1 and exported["items"][0]["exported_at"]
    # повторная отметка — no-op, без второй записи в аудит
    r = client.post(
        "/api/v1/retrain-queue/mark-exported", json={"ids": [item["id"]]}, headers=admin_headers
    )
    assert r.json()["exported"] == 0
    audits = db.scalars(select(AuditLog).where(AuditLog.action == "retrain_export")).all()
    assert len(audits) == 1 and audits[0].after == {"ids": [item["id"]]}
    # выгруженный элемент не удаляется при возврате события в confirmed (история сохраняется)
    client.post(f"/api/v1/events/{ev}/review", json={"status": "confirmed"}, headers=admin_headers)
    assert (
        client.get("/api/v1/retrain-queue?exported=true", headers=admin_headers).json()["total"]
        == 1
    )


def test_queue_requires_staff_role(client, viewer_headers, admin_headers):
    assert client.get("/api/v1/retrain-queue", headers=viewer_headers).status_code == 403
    assert (
        client.post(
            "/api/v1/retrain-queue/mark-exported", json={"ids": [1]}, headers=viewer_headers
        ).status_code
        == 403
    )
    assert client.get("/api/v1/retrain-queue").status_code == 401
    assert (
        client.post(
            "/api/v1/retrain-queue/mark-exported", json={"ids": []}, headers=admin_headers
        ).status_code
        == 422
    )


def test_heartbeat_updates_model_version(client, db, base_fleet, admin_headers):
    device = base_fleet["device"]
    r = client.post(
        f"/api/v1/devices/{device.id}/heartbeat",
        json={"fw_version": "0.3.0", "model_version": "violations-v1", "fps": 12.5},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    db.expire_all()
    fresh = db.get(Device, device.id)
    assert fresh.model_version == "violations-v1" and fresh.fw_version == "0.3.0"
