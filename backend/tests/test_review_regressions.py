from unittest.mock import Mock

import pytest
from sqlalchemy import update

from app import storage
from app.models import Vehicle
from app.seed import PHONES


@pytest.mark.parametrize("internal", [True, False])
def test_clip_link_selects_endpoint(monkeypatch, internal):
    client = Mock()
    factory = Mock(return_value=client)
    monkeypatch.setattr(storage, "_client", factory)
    storage.presigned_clip_download("clips/test.mp4", internal=internal)
    factory.assert_called_once_with(public=not internal)
    client.presigned_get_object.assert_called_once()


def test_unassigned_driver_cannot_start_trip_on_another_vehicle(client, seeded):
    seeded.execute(update(Vehicle).where(Vehicle.driver_id == 1).values(driver_id=None))
    seeded.commit()
    login = client.post("/api/v1/auth/driver-login", json={"phone": PHONES[0], "pin": "1234"})
    token = login.json()["access_token"]
    result = client.post("/api/v1/trips/start", json={"driver_id": 1, "vehicle_id": 2},
                         headers={"Authorization": f"Bearer {token}"})
    assert result.status_code == 403
