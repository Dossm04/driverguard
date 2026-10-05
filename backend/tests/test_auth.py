"""Тесты аутентификации: BE-1, SEC-1, SEC-2."""

from datetime import UTC, datetime

from app import security
from app.models import Driver, User
from app.security import hash_secret


def _make_driver_user(db, phone="+77010000009", pin="4321"):
    user = User(
        role="driver",
        phone=phone,
        pin_hash=hash_secret(pin),
        name="Сейткали М.",
        created_at=datetime.now(UTC),
    )
    db.add(user)
    db.flush()
    driver = Driver(user_id=user.id, name="Сейткали М.", phone=phone, created_at=datetime.now(UTC))
    db.add(driver)
    db.commit()
    return user, driver


def test_admin_login_ok(client, admin):
    resp = client.post(
        "/api/v1/auth/login", json={"email": "admin@test.kz", "password": "admin123"}
    )
    assert resp.status_code == 200
    body = resp.json()
    assert body["access_token"] and body["refresh_token"]
    assert body["user"]["role"] == "admin"


def test_admin_login_wrong_password(client, admin):
    resp = client.post("/api/v1/auth/login", json={"email": "admin@test.kz", "password": "нет"})
    assert resp.status_code == 401


def test_driver_login_and_pin_limit(client, db):
    user, driver = _make_driver_user(db)
    security._pin_attempts.clear()

    resp = client.post("/api/v1/auth/driver-login", json={"phone": user.phone, "pin": "4321"})
    assert resp.status_code == 200
    assert resp.json()["driver_id"] == driver.id

    # 5 неверных попыток → шестая блокируется (429), даже с верным PIN
    for _ in range(5):
        bad = client.post("/api/v1/auth/driver-login", json={"phone": user.phone, "pin": "0000"})
        assert bad.status_code == 401
    blocked = client.post("/api/v1/auth/driver-login", json={"phone": user.phone, "pin": "4321"})
    assert blocked.status_code == 429
    security._pin_attempts.clear()


def test_refresh(client, admin):
    login = client.post(
        "/api/v1/auth/login", json={"email": "admin@test.kz", "password": "admin123"}
    ).json()
    resp = client.post("/api/v1/auth/refresh", json={"refresh_token": login["refresh_token"]})
    assert resp.status_code == 200
    assert resp.json()["access_token"]


def test_role_guard(client, db, admin_headers):
    """Водителю справочники недоступны, без токена — 401."""
    user, _ = _make_driver_user(db, phone="+77010000008")
    security._pin_attempts.clear()
    token = client.post(
        "/api/v1/auth/driver-login", json={"phone": user.phone, "pin": "4321"}
    ).json()["access_token"]

    assert client.get("/api/v1/drivers").status_code == 401
    forbidden = client.get("/api/v1/drivers", headers={"Authorization": f"Bearer {token}"})
    assert forbidden.status_code == 403
    ok = client.get("/api/v1/drivers", headers=admin_headers)
    assert ok.status_code == 200


def test_viewer_reads_directories_but_cannot_write(
    client, db, base_fleet, admin_headers, viewer_headers
):
    """SEC-1: viewer — только чтение. Списки открыты, создание — 403,
    телефоны водителей (персональные данные, SEC-5) скрыты."""
    for path in ("/api/v1/drivers", "/api/v1/depots", "/api/v1/vehicles", "/api/v1/devices"):
        assert client.get(path, headers=viewer_headers).status_code == 200, path
    create = client.post("/api/v1/drivers", json={"name": "Тестов Т.Т."}, headers=viewer_headers)
    assert create.status_code == 403

    driver_id = base_fleet["driver"].id
    as_viewer = client.get("/api/v1/drivers", headers=viewer_headers).json()[0]
    as_admin = client.get("/api/v1/drivers", headers=admin_headers).json()[0]
    assert as_viewer["phone"] is None
    assert as_admin["phone"] == "+77010000001"
    profile = client.get(f"/api/v1/drivers/{driver_id}/profile", headers=viewer_headers).json()
    assert profile["driver"]["phone"] is None


def test_driver_phone_and_pin_format_validated_on_server(client, db, base_fleet, admin_headers):
    """Контракт формы (+7XXXXXXXXXX, PIN 4–6 цифр) действует и для прямых запросов."""
    bad_pin = client.post(
        "/api/v1/drivers",
        json={"name": "Тестов Т.Т.", "phone": "+77770001122", "pin": "1"},
        headers=admin_headers,
    )
    assert bad_pin.status_code == 422
    bad_phone = client.post(
        "/api/v1/drivers",
        json={"name": "Тестов Т.Т.", "phone": "87770001122"},
        headers=admin_headers,
    )
    assert bad_phone.status_code == 422
    ok = client.post(
        "/api/v1/drivers",
        json={"name": "Тестов Т.Т.", "phone": "+77770001122", "pin": "4321"},
        headers=admin_headers,
    )
    assert ok.status_code == 201, ok.text
    # Дубль телефона — честный 409 (сообщение показывает форма)
    dup = client.post(
        "/api/v1/drivers",
        json={"name": "Дублёв Д.Д.", "phone": "+77770001122"},
        headers=admin_headers,
    )
    assert dup.status_code == 409
    assert "телефоном" in dup.json()["detail"]


def test_long_secret_gives_422_not_500(client, db, base_fleet, admin_headers):
    """Секрет устройства длиннее 72 байт — понятная ошибка, а не падение сервера.

    bcrypt хэширует только первые 72 байта и на более длинной строке
    выбрасывает исключение. У полей DeviceIn ограничения не было, и обычная
    русская фраза («Секрет-устройства-для-грузовика-номер-один», 79 байт)
    превращалась в HTTP 500 с английским текстом в логе.
    """
    long_ru = "Секрет-устройства-для-грузовика-номер-один"
    assert len(long_ru.encode()) > 72

    bad = client.post(
        "/api/v1/devices",
        json={"serial": "DG-LONG", "secret": long_ru},
        headers=admin_headers,
    )
    assert bad.status_code == 422, bad.text

    short = client.post(
        "/api/v1/devices",
        json={"serial": "DG-LONG", "secret": "s"},
        headers=admin_headers,
    )
    assert short.status_code == 201, short.text


def test_hash_secret_refuses_oversized_input():
    """Вторая линия защиты: прямой вызов в обход API тоже даёт понятную ошибку."""
    import pytest as _pytest

    from app.security import hash_secret

    assert hash_secret("a" * 72)
    with _pytest.raises(ValueError, match="72 байт"):
        hash_secret("a" * 73)
