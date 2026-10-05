"""Настройки (BE-15), пользователи (WEB-9), перезагрузка устройств."""

from sqlalchemy import select

from app.models import AuditLog, Setting


def _leaderboard_score(client, headers, name: str) -> int:
    rows = client.get("/api/v1/leaderboard?period=7", headers=headers).json()["rows"]
    return next(r["score"] for r in rows if r["name"] == name)


def _scoring(client, headers) -> dict:
    return client.get("/api/v1/settings/scoring", headers=headers).json()["value"]


def test_list_and_validation(client, seeded, headers, viewer_headers):
    keys = {s["key"] for s in client.get("/api/v1/settings", headers=viewer_headers).json()}
    assert keys == {"notifications", "retention", "scoring", "thresholds"}
    assert client.get("/api/v1/settings/unknown", headers=headers).status_code == 404

    bad = client.put(
        "/api/v1/settings/thresholds",
        json={
            "value": {
                **client.get("/api/v1/settings/thresholds", headers=headers).json()["value"],
                "MICROSLEEP_MS": 99,
            }
        },
        headers=headers,
    )
    assert bad.status_code == 422 and "MICROSLEEP_MS" in bad.json()["detail"]
    scoring = _scoring(client, headers)
    unknown = client.put(
        "/api/v1/settings/scoring",
        json={"value": {**scoring, "weights": {**scoring["weights"], "teleport": 5}}},
        headers=headers,
    )
    assert unknown.status_code == 422 and "teleport" in unknown.json()["detail"]
    assert (
        client.put("/api/v1/settings/nope", json={"value": {}}, headers=headers).status_code == 404
    )


def test_weight_change_moves_leaderboard_with_version_and_audit(client, db, seeded, headers):
    """«Готово, когда» ШАГ 11: изменение веса события меняет Score в лидерборде."""
    before = _leaderboard_score(client, headers, "Иванов А.С.")
    assert before == 55
    scoring = _scoring(client, headers)
    scoring["weights"]["microsleep"] = 30
    resp = client.put("/api/v1/settings/scoring", json={"value": scoring}, headers=headers)
    assert resp.status_code == 200, resp.text
    assert resp.json()["version"] == 2 and resp.json()["updated_by_name"] == "Айгерим Косанова"
    after = _leaderboard_score(client, headers, "Иванов А.С.")
    assert after < before
    audit = db.scalars(select(AuditLog).where(AuditLog.action == "settings_update")).all()
    assert len(audit) == 1 and audit[0].before["weights"]["microsleep"] == 15
    assert db.get(Setting, "scoring").version == 2


def test_modifiers_are_configurable(client, seeded, headers):
    """Иванов: телефон на 70 км/ч (×1.5). Убираем множитель — Score растёт."""
    before = _leaderboard_score(client, headers, "Иванов А.С.")
    scoring = _scoring(client, headers)
    scoring["modifiers"]["fast_mult"] = 1.0
    assert (
        client.put("/api/v1/settings/scoring", json={"value": scoring}, headers=headers).status_code
        == 200
    )
    assert _leaderboard_score(client, headers, "Иванов А.С.") > before
    bad = client.put(
        "/api/v1/settings/scoring",
        json={"value": {**scoring, "modifiers": {**scoring["modifiers"], "fast_mult": 9}}},
        headers=headers,
    )
    assert bad.status_code == 422


def test_preview_does_not_persist(client, seeded, headers):
    scoring = _scoring(client, headers)
    scoring["weights"]["microsleep"] = 30
    rows = client.post("/api/v1/settings/scoring/preview", json=scoring, headers=headers).json()
    ivanov = next(r for r in rows if r["name"] == "Иванов А.С.")
    assert ivanov["score_now"] == 55 and ivanov["delta"] < 0
    assert ivanov["score_new"] == ivanov["score_now"] + ivanov["delta"]
    assert client.get("/api/v1/settings/scoring", headers=headers).json()["version"] == 1


def test_users_crud_and_rbac(client, seeded, headers, viewer_headers):
    assert client.post("/api/v1/users", json={}, headers=viewer_headers).status_code == 403
    created = client.post(
        "/api/v1/users",
        json={
            "name": "Тестова Т.Т.",
            "email": "Test@Driverguard.kz",
            "role": "coordinator",
            "password": "secret123",
        },
        headers=headers,
    )
    assert created.status_code == 201, created.text
    uid = created.json()["id"]
    assert created.json()["email"] == "test@driverguard.kz"
    dup = client.post(
        "/api/v1/users",
        json={
            "name": "Дубль Д.Д.",
            "email": "test@driverguard.kz",
            "role": "viewer",
            "password": "secret123",
        },
        headers=headers,
    )
    assert dup.status_code == 409

    # координатор читает настройки, но не пишет
    token = client.post(
        "/api/v1/auth/login", json={"email": "test@driverguard.kz", "password": "secret123"}
    ).json()["access_token"]
    coord = {"Authorization": f"Bearer {token}"}
    assert client.get("/api/v1/settings", headers=coord).status_code == 200
    scoring = _scoring(client, headers)
    assert (
        client.put("/api/v1/settings/scoring", json={"value": scoring}, headers=coord).status_code
        == 403
    )

    patched = client.patch(f"/api/v1/users/{uid}", json={"role": "viewer"}, headers=headers)
    assert patched.status_code == 200 and patched.json()["role"] == "viewer"
    me = next(
        u
        for u in client.get("/api/v1/users", headers=headers).json()
        if u["email"] == "admin@driverguard.kz"
    )
    assert (
        client.patch(
            f"/api/v1/users/{me['id']}", json={"role": "viewer"}, headers=headers
        ).status_code
        == 409
    )
    drivers = [
        u for u in client.get("/api/v1/users", headers=headers).json() if u["role"] == "driver"
    ]
    assert (
        client.patch(
            f"/api/v1/users/{drivers[0]['id']}", json={"name": "Иной И.И."}, headers=headers
        ).status_code
        == 409
    )


def test_device_reboot_delivered_via_config(client, seeded, headers):
    devices = client.get("/api/v1/devices", headers=headers).json()
    dev = next(d for d in devices if d["serial"] == "DG-0001")
    assert dev["vehicle_plate"] == "KZ 4521 AB"
    resp = client.post(f"/api/v1/devices/{dev['id']}/reboot", headers=headers)
    assert resp.status_code == 200 and resp.json()["status"] == "reboot_requested"

    token = client.post(
        "/api/v1/auth/device", json={"serial": "DG-0001", "secret": "device-secret-1"}
    ).json()["access_token"]
    # Сотрудник видит команду, но не «гасит» её — сбрасывает только само устройство
    assert client.get(f"/api/v1/devices/{dev['id']}/config", headers=headers).json()["reboot"]
    dev_headers = {"Authorization": f"Bearer {token}"}
    first = client.get(f"/api/v1/devices/{dev['id']}/config", headers=dev_headers).json()
    second = client.get(f"/api/v1/devices/{dev['id']}/config", headers=dev_headers).json()
    assert first["reboot"] is True and second["reboot"] is False


def test_user_password_bytes_limit_and_login_case(client, seeded, headers):
    """bcrypt: >72 байт — 422 при создании и 401 (не 500) на входе; email без учёта регистра."""
    long_pw = "п" * 40  # 40 символов = 80 байт UTF-8
    payload = {"name": "Длинный П.П.", "email": "Case@DriverGuard.kz", "role": "viewer"}
    resp = client.post("/api/v1/users", json={**payload, "password": long_pw}, headers=headers)
    assert resp.status_code == 422
    ok = client.post("/api/v1/users", json={**payload, "password": "secret123"}, headers=headers)
    assert ok.status_code == 201 and ok.json()["email"] == "case@driverguard.kz"
    login = client.post(
        "/api/v1/auth/login", json={"email": "  CASE@driverguard.kz ", "password": "secret123"}
    )
    assert login.status_code == 200
    bad = client.post(
        "/api/v1/auth/login", json={"email": "case@driverguard.kz", "password": long_pw}
    )
    assert bad.status_code == 401


def test_scoring_preview_422_readable_and_put_merges_defaults(client, seeded, headers):
    from app.scoring import DEFAULT_MODIFIERS, DEFAULT_WEIGHTS

    bad = client.post(
        "/api/v1/settings/scoring/preview",
        json={"weights": {"phone": 99}, "modifiers": DEFAULT_MODIFIERS},
        headers=headers,
    )
    assert bad.status_code == 422 and "scoring" in bad.json()["detail"]  # строка, не список
    partial = client.put(
        "/api/v1/settings/scoring",
        json={"value": {"weights": {"phone": 12}, "modifiers": DEFAULT_MODIFIERS}},
        headers=headers,
    )
    assert partial.status_code == 200
    weights = partial.json()["value"]["weights"]
    assert weights["phone"] == 12 and weights["microsleep"] == DEFAULT_WEIGHTS["microsleep"]
    assert set(weights) == set(DEFAULT_WEIGHTS)
