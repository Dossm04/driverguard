"""Production-стандарты (docs/ARCHITECTURE.md): rate limit, security-заголовки, request-id,
readiness, метрики, обработка необработанных ошибок."""

import pytest
from fastapi import APIRouter
from fastapi.testclient import TestClient

from app import observability
from app.main import app


@pytest.fixture()
def limiters():
    """Лимитеры общие на процесс — после теста возвращаем порог и чистим окна."""
    auth_limit = observability.auth_limiter.limit
    general_limit = observability.general_limiter.limit
    observability.auth_limiter.reset()
    observability.general_limiter.reset()
    yield observability.auth_limiter, observability.general_limiter
    observability.auth_limiter.limit = auth_limit
    observability.general_limiter.limit = general_limit
    observability.auth_limiter.reset()
    observability.general_limiter.reset()


def test_security_headers_and_request_id(client):
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    assert resp.headers["x-content-type-options"] == "nosniff"
    assert resp.headers["x-frame-options"] == "DENY"
    assert resp.headers["referrer-policy"] == "no-referrer"
    assert resp.headers["cache-control"] == "no-store"
    assert len(resp.headers["x-request-id"]) == 12

    # входящий X-Request-Id пробрасывается в ответ (трассировка через прокси/панель)
    resp = client.get("/api/v1/health", headers={"X-Request-Id": "trace-abc-123"})
    assert resp.headers["x-request-id"] == "trace-abc-123"


def test_auth_rate_limit_returns_429_with_retry_after(client, limiters):
    auth_limiter, _ = limiters
    auth_limiter.limit = 3
    body = {"email": "nobody@test.kz", "password": "wrong"}
    for _ in range(3):
        assert client.post("/api/v1/auth/login", json=body).status_code == 401
    resp = client.post("/api/v1/auth/login", json=body)
    assert resp.status_code == 429
    assert "Слишком много запросов" in resp.json()["detail"]
    assert int(resp.headers["retry-after"]) >= 1
    assert resp.headers["x-request-id"]
    # лимит входа не трогает остальные маршруты
    assert client.get("/api/v1/health").status_code == 200


def test_general_rate_limit_is_per_token(client, admin_headers, viewer_headers, limiters):
    _, general_limiter = limiters
    general_limiter.limit = 2
    general_limiter.reset()
    assert client.get("/api/v1/drivers", headers=admin_headers).status_code == 200
    assert client.get("/api/v1/drivers", headers=admin_headers).status_code == 200
    assert client.get("/api/v1/drivers", headers=admin_headers).status_code == 429
    # другой пользователь (другой токен) за тем же NAT не заблокирован
    assert client.get("/api/v1/drivers", headers=viewer_headers).status_code == 200


def test_sliding_window_limiter_unit():
    lim = observability.SlidingWindowLimiter(limit=2, window_s=60)
    assert lim.allow("a") == (True, 0)
    assert lim.allow("a") == (True, 0)
    allowed, retry = lim.allow("a")
    assert not allowed and 1 <= retry <= 61
    assert lim.allow("b")[0]  # другой ключ независим
    lim.reset()
    assert lim.allow("a")[0]


def test_ready_reports_db_and_storage(client):
    resp = client.get("/api/v1/health/ready")
    assert resp.status_code in (200, 503)
    body = resp.json()
    assert body["db"] == "ok"  # БД в тестах точно есть
    assert body["storage"] in ("ok", "error")  # MinIO в CI может отсутствовать
    assert body["status"] == ("ready" if body["storage"] == "ok" else "not_ready")


def test_metrics_admin_only_and_route_templates(client, admin_headers, viewer_headers):
    assert client.get("/api/v1/health/metrics").status_code == 401
    assert client.get("/api/v1/health/metrics", headers=viewer_headers).status_code == 403
    client.get("/api/v1/drivers/999/profile", headers=admin_headers)
    resp = client.get("/api/v1/health/metrics", headers=admin_headers)
    assert resp.status_code == 200
    snap = resp.json()
    assert snap["requests_total"] >= 3
    routes = snap["routes"]
    # маршруты агрегируются по шаблону, а не по конкретному id (иначе метрики разрастаются)
    assert "GET /api/v1/drivers/{driver_id}/profile" in routes
    assert routes["GET /api/v1/drivers/{driver_id}/profile"]["count"] >= 1
    assert "p95_ms" in routes["GET /api/v1/health/metrics"] or "GET /api/v1/health" in routes
    assert "Pool size" in snap["db_pool"]
    assert snap["thread_limiter"]["total"] >= 1


def test_unhandled_error_is_json_with_request_id(client):
    boom = APIRouter()

    @boom.get("/api/v1/_boom")
    def _boom():
        raise RuntimeError("тестовая авария")

    app.include_router(boom)
    try:
        c = TestClient(app, raise_server_exceptions=False)
        resp = c.get("/api/v1/_boom", headers={"X-Request-Id": "boom-1"})
        assert resp.status_code == 500
        assert resp.json() == {"detail": "Внутренняя ошибка сервера", "request_id": "boom-1"}
        assert resp.headers["x-request-id"] == "boom-1"
        assert "тестовая авария" not in resp.text  # трассировка наружу не уходит
    finally:
        app.router.routes[:] = [
            r for r in app.router.routes if getattr(r, "path", "") != "/api/v1/_boom"
        ]


def test_cors_headers_present_on_rate_limited_response(client, limiters):
    auth_limiter, _ = limiters
    auth_limiter.limit = 1
    origin = {"Origin": "http://localhost:3000"}
    body = {"email": "nobody@test.kz", "password": "wrong"}
    client.post("/api/v1/auth/login", json=body, headers=origin)
    resp = client.post("/api/v1/auth/login", json=body, headers=origin)
    assert resp.status_code == 429
    assert resp.headers["access-control-allow-origin"] == "http://localhost:3000"


def test_client_ip_ignores_forwarded_headers_unless_trust_proxy(monkeypatch):
    """Без TRUST_PROXY подделать IP заголовком нельзя (иначе лимит входа обходится)."""
    from app import config

    scope = {
        "client": ("10.0.0.7", 1234),
        "headers": [(b"x-forwarded-for", b"1.2.3.4, 10.0.0.1"), (b"cf-connecting-ip", b"5.6.7.8")],
    }
    settings = config.get_settings()
    monkeypatch.setattr(settings, "trust_proxy", False)
    assert observability.client_ip(scope) == "10.0.0.7"
    monkeypatch.setattr(settings, "trust_proxy", True)
    assert observability.client_ip(scope) == "5.6.7.8"  # Cloudflare важнее X-Forwarded-For
    scope["headers"] = [(b"x-forwarded-for", b"1.2.3.4, 10.0.0.1")]
    assert observability.client_ip(scope) == "1.2.3.4"


def test_limiter_key_uses_only_signed_tokens():
    """Ключ лимитера — пользователь из подписанного токена; случайный Bearer лимит не обходит."""
    from datetime import timedelta

    from app import security

    token = security.create_token("7", "access", timedelta(minutes=5), role="admin")
    scope = {"client": ("10.0.0.7", 1), "headers": [(b"authorization", f"Bearer {token}".encode())]}
    assert observability.limiter_key(scope) == "tok:access:7"
    scope["headers"] = [(b"authorization", b"Bearer " + b"x" * 64)]  # подделка — считаем по IP
    assert observability.limiter_key(scope) == "ip:10.0.0.7"


def test_route_template_collapses_path_params():
    scope = {
        "method": "GET",
        "path": "/api/v1/drivers/42/profile",
        "path_params": {"driver_id": 42},
        "endpoint": object(),
    }
    assert observability.route_template(scope) == "GET /api/v1/drivers/{driver_id}/profile"
    scope = {
        "method": "POST",
        "path": "/api/v1/events/9b1c/review",
        "path_params": {"event_uuid": "9b1c"},
        "endpoint": object(),
    }
    assert observability.route_template(scope) == "POST /api/v1/events/{event_uuid}/review"
    # случайные 404-пути (сканер) не плодят маршруты в метриках
    assert observability.route_template({"method": "GET", "path": "/wp-admin"}) == "GET <unmatched>"


def test_login_lockout_is_progressive_not_permanent(client, db):
    """5 неудач → пауза 1 с, не 15 минут: чужие ошибки не запирают учётку жюри надолго."""
    from app import security

    key = "email:locked@test.kz"
    security.pin_reset(key)
    body = {"email": "locked@test.kz", "password": "nope"}
    for _ in range(5):
        assert client.post("/api/v1/auth/login", json=body).status_code == 401
    resp = client.post("/api/v1/auth/login", json=body)
    assert resp.status_code == 429
    assert int(resp.headers["retry-after"]) >= 1
    assert security.pin_retry_after(key) >= 1
    security.pin_reset(key)


def test_device_login_is_rate_limited_and_body_size_capped(client, base_fleet):
    from app import security

    security.pin_reset("device:DG-0001")
    for _ in range(5):
        r = client.post("/api/v1/auth/device", json={"serial": "DG-0001", "secret": "wrong"})
        assert r.status_code == 401
    r = client.post("/api/v1/auth/device", json={"serial": "DG-0001", "secret": "wrong"})
    assert r.status_code == 429
    security.pin_reset("device:DG-0001")
    # JSON больше 2 МБ отбрасывается до чтения тела
    r = client.post(
        "/api/v1/auth/login",
        content=b"{}",
        headers={"Content-Type": "application/json", "Content-Length": str(3 * 1024 * 1024)},
    )
    assert r.status_code == 413
