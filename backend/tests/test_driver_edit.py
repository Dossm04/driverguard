"""Редактирование водителя: машина, телефон/PIN, фото (валидация типа и размера)."""

import pytest

from app import storage
from app.models import Vehicle


@pytest.fixture(autouse=True)
def fake_storage(monkeypatch):
    saved: dict[str, int] = {}
    monkeypatch.setattr(
        storage, "put_photo", lambda key, data, ct: saved.__setitem__(key, len(data))
    )
    monkeypatch.setattr(storage, "presigned_photo_download", lambda key: f"http://minio.test/{key}")
    return saved


def test_patch_vehicle_reassign_and_conflict(client, db, base_fleet, admin_headers):
    driver = base_fleet["driver"]
    other = Vehicle(plate="KZ 1111 ZZ", model="Volvo FH", depot_id=base_fleet["depot"].id)
    db.add(other)
    db.commit()
    r = client.patch(
        f"/api/v1/drivers/{driver.id}", json={"vehicle_id": other.id}, headers=admin_headers
    )
    assert r.status_code == 200, r.text
    assert r.json()["vehicle_plate"] == "KZ 1111 ZZ" and r.json()["vehicle_id"] == other.id
    db.expire_all()
    assert db.get(Vehicle, base_fleet["vehicle"].id).driver_id is None  # старая машина откреплена

    r2 = client.post(
        "/api/v1/drivers",
        json={"name": "Петров П.П.", "phone": "+77010000098"},
        headers=admin_headers,
    )
    second = r2.json()["id"]
    r = client.patch(
        f"/api/v1/drivers/{second}", json={"vehicle_id": other.id}, headers=admin_headers
    )
    assert r.status_code == 409  # машина уже закреплена
    r = client.patch(
        f"/api/v1/drivers/{driver.id}", json={"vehicle_id": None}, headers=admin_headers
    )
    assert r.status_code == 200 and r.json()["vehicle_id"] is None
    assert (
        client.patch(
            f"/api/v1/drivers/{driver.id}", json={"vehicle_id": 999}, headers=admin_headers
        ).status_code
        == 404
    )


def test_photo_upload_validation_and_delete(client, base_fleet, admin_headers, fake_storage):
    driver = base_fleet["driver"]
    url = f"/api/v1/drivers/{driver.id}/photo"
    r = client.post(
        url,
        files={"file": ("a.jpg", b"\xff\xd8\xff" + b"x" * 100, "image/jpeg")},
        headers=admin_headers,
    )
    assert r.status_code == 200, r.text
    assert r.json()["photo_url"].startswith("http://minio.test/drivers/") and fake_storage
    assert (
        client.post(
            url, files={"file": ("a.txt", b"hello", "text/plain")}, headers=admin_headers
        ).status_code
        == 415
    )
    big = b"x" * (5 * 1024 * 1024 + 1)
    assert (
        client.post(
            url, files={"file": ("b.png", big, "image/png")}, headers=admin_headers
        ).status_code
        == 413
    )
    assert (
        client.post(
            url, files={"file": ("c.png", b"", "image/png")}, headers=admin_headers
        ).status_code
        == 400
    )
    prof = client.get(f"/api/v1/drivers/{driver.id}/profile", headers=admin_headers).json()
    assert prof["driver"]["photo_url"].startswith("http://minio.test/")
    r = client.delete(url, headers=admin_headers)
    assert r.status_code == 200 and r.json()["photo_url"] is None


def test_photo_requires_staff(client, base_fleet, viewer_headers):
    r = client.post(
        f"/api/v1/drivers/{base_fleet['driver'].id}/photo",
        files={"file": ("a.jpg", b"xx", "image/jpeg")},
        headers=viewer_headers,
    )
    assert r.status_code == 403
