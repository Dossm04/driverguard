"""Тесты ручки /api/v1/health."""

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)


def test_health_ok() -> None:
    """Ручка health возвращает 200 и корректное тело."""
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json() == {
        "status": "ok",
        "service": "driverguard-backend",
        "version": "0.1.0",
    }
