"""Аудит (безопасность): viewer без телефонов, отключённое устройство, лимит /auth/login."""

from app.seed import PHONES


def _login(client, email, password):
    r = client.post("/api/v1/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}, r.json()["access_token"]


def _make_viewer(client, headers):
    r = client.post(
        "/api/v1/users",
        json={
            "name": "Наблюдатель Н.Н.",
            "email": "viewer@driverguard.kz",
            "role": "viewer",
            "password": "viewer123",
        },
        headers=headers,
    )
    assert r.status_code == 201
    return _login(client, "viewer@driverguard.kz", "viewer123")


def test_viewer_sees_no_phones_in_profile_dashboard_and_ws(client, seeded, headers):
    vh, vtoken = _make_viewer(client, headers)
    profile = client.get("/api/v1/drivers/1/profile", headers=vh).json()
    assert profile["driver"]["phone"] is None
    assert all(e["driver_phone"] is None for e in profile["recent_events"])
    latest = client.get("/api/v1/dashboard/critical-latest", headers=vh).json()
    assert latest and all(e["driver_phone"] is None for e in latest)
    with client.websocket_connect(f"/ws/live?token={vtoken}") as ws:
        snap = ws.receive_json()
    assert snap["type"] == "positions" and all(v["driver_phone"] is None for v in snap["vehicles"])
    # у координатора/админа телефоны есть
    admin_profile = client.get("/api/v1/drivers/1/profile", headers=headers).json()
    assert admin_profile["driver"]["phone"] == PHONES[0]
    assert any(
        e["driver_phone"]
        for e in client.get("/api/v1/dashboard/critical-latest", headers=headers).json()
    )


def test_disabled_device_loses_access(client, seeded, headers):
    devices = client.get("/api/v1/devices", headers=headers).json()
    dev = next(d for d in devices if d["serial"] == "DG-0002")
    token = client.post(
        "/api/v1/auth/device", json={"serial": "DG-0002", "secret": "device-secret-2"}
    ).json()["access_token"]
    dh = {"Authorization": f"Bearer {token}"}
    assert client.get(f"/api/v1/devices/{dev['id']}/config", headers=dh).status_code == 200
    assert (
        client.patch(
            f"/api/v1/devices/{dev['id']}", json={"status": "disabled"}, headers=headers
        ).status_code
        == 200
    )
    assert client.get(f"/api/v1/devices/{dev['id']}/config", headers=dh).status_code == 403
    assert (
        client.patch(
            f"/api/v1/devices/{dev['id']}", json={"status": "weird"}, headers=headers
        ).status_code
        == 422
    )


def test_login_rate_limited_after_failures(client, seeded):
    for _ in range(5):
        assert (
            client.post(
                "/api/v1/auth/login", json={"email": "limit@driverguard.kz", "password": "x"}
            ).status_code
            == 401
        )
    assert (
        client.post(
            "/api/v1/auth/login", json={"email": "LIMIT@driverguard.kz", "password": "x"}
        ).status_code
        == 429
    )
