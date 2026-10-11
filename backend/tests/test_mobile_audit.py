"""A disconnected phone may retry an audit without creating duplicates."""

import uuid

import pytest
from test_checklists import _answers, _files

from app import storage


@pytest.fixture
def mobile_storage(monkeypatch):
    saved = []
    monkeypatch.setattr(storage, "put_photo", lambda key, data, ct: saved.append(key))
    monkeypatch.setattr(
        storage, "presigned_photo_download", lambda key: f"https://storage.test/{key}"
    )
    return saved


def test_mobile_capability_requires_account(client, admin_headers):
    assert client.get("/api/v1/checklists/mobile-capabilities").status_code == 401
    response = client.get("/api/v1/checklists/mobile-capabilities", headers=admin_headers)
    assert response.status_code == 200
    assert response.json()["idempotent_uploads"] is True


def test_same_client_uuid_returns_original_without_reupload(
    client, base_fleet, admin_headers, mobile_storage
):
    client_uuid = str(uuid.uuid4())
    data = {"answers": _answers(), "driver_id": "1", "client_uuid": client_uuid}
    first = client.post("/api/v1/checklists", data=data, files=_files(), headers=admin_headers)
    assert first.status_code == 201, first.text
    # Replay even works without photo parts: the first response could have been lost.
    retry = client.post(
        "/api/v1/checklists",
        data={"driver_id": "1", "client_uuid": client_uuid},
        headers=admin_headers,
    )
    assert retry.status_code == 201, retry.text
    assert retry.json()["id"] == first.json()["id"]
    assert len(mobile_storage) == 7
    assert client.get("/api/v1/checklists", headers=admin_headers).json()["total"] == 1


def test_distinct_mobile_inspections_are_not_collapsed(
    client, base_fleet, admin_headers, mobile_storage
):
    ids = []
    for _ in range(2):
        response = client.post(
            "/api/v1/checklists",
            data={"answers": _answers(), "driver_id": "1", "client_uuid": str(uuid.uuid4())},
            files=_files(),
            headers=admin_headers,
        )
        assert response.status_code == 201, response.text
        ids.append(response.json()["id"])
    assert ids[0] != ids[1]


def test_invalid_mobile_uuid_does_not_store_photos(
    client, base_fleet, admin_headers, mobile_storage
):
    response = client.post(
        "/api/v1/checklists",
        data={"answers": _answers(), "driver_id": "1", "client_uuid": "invalid"},
        files=_files(),
        headers=admin_headers,
    )
    assert response.status_code == 422
    assert mobile_storage == []


def test_unconfigured_photo_ai_requires_manual_review_note(
    client, base_fleet, admin_headers, mobile_storage
):
    response = client.post(
        "/api/v1/checklists",
        data={"answers": _answers(), "driver_id": "1", "client_uuid": str(uuid.uuid4())},
        files=_files(),
        headers=admin_headers,
    )
    assert response.status_code == 201, response.text
    audit = response.json()
    assert audit["verdict"] == "требует_внимания"
    assert audit["ai_meta"]["provider"] == "unavailable"
    endpoint = f"/api/v1/checklists/{audit['id']}/approve"
    assert (
        client.post(endpoint, json={"action": "approve"}, headers=admin_headers).status_code == 409
    )
    approved = client.post(
        endpoint,
        json={"action": "approve_with_note", "note": "Фотографии проверены координатором"},
        headers=admin_headers,
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["note"] == "Фотографии проверены координатором"
