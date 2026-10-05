"""CORS: панель на localhost и телефон в локальной сети (по IP ноутбука) получают заголовки."""


def test_cors_allows_localhost_and_lan_origins(client):
    for origin in ("http://localhost:3000", "http://192.168.1.42:3000", "http://10.0.0.7:3000"):
        resp = client.options(
            "/api/v1/auth/login",
            headers={
                "Origin": origin,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "content-type,authorization",
            },
        )
        assert resp.status_code == 200, origin
        assert resp.headers.get("access-control-allow-origin") == origin
    denied = client.options(
        "/api/v1/auth/login",
        headers={"Origin": "http://evil.example", "Access-Control-Request-Method": "POST"},
    )
    assert denied.headers.get("access-control-allow-origin") is None
