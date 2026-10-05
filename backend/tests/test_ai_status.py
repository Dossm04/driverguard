"""Статус и проверка ИИ-провайдера из панели (демо-режим без ключа, ошибка провайдера, RBAC)."""

from app import ai_checklist
from app.ai_checklist import AiError


def test_ai_status_mock_explains(client, admin_headers, monkeypatch):
    monkeypatch.setattr(ai_checklist, "resolve_provider", lambda: "mock")
    r = client.get("/api/v1/checklists/ai-status", headers=admin_headers)
    assert r.status_code == 200
    assert r.json()["provider"] == "mock" and r.json()["configured"] is False
    assert "OPENAI_COMPAT_API_KEY" in r.json()["hint"]


def test_ai_test_mock_and_error(client, admin_headers, viewer_headers, monkeypatch):
    monkeypatch.setattr(ai_checklist, "resolve_provider", lambda: "mock")
    r = client.post("/api/v1/checklists/ai-test", headers=admin_headers)
    assert r.status_code == 200 and r.json()["ok"] and r.json()["demo"] is True

    def boom(_photos):
        raise AiError("HTTP 401: неверный ключ")

    monkeypatch.setattr(ai_checklist, "verify_photos", boom)
    r = client.post("/api/v1/checklists/ai-test", headers=admin_headers)
    assert r.status_code == 200 and r.json()["ok"] is False and "401" in r.json()["error"]
    assert client.post("/api/v1/checklists/ai-test", headers=viewer_headers).status_code == 403
    assert client.get("/api/v1/checklists/ai-status", headers=viewer_headers).status_code == 200


def test_masked_key_reports_clear_error(client, admin_headers, monkeypatch):
    """Ключ «sk-…•••» (замаскированная вставка) → понятная ошибка, не UnicodeEncodeError."""
    from app import ai_checklist
    from app.config import get_settings

    monkeypatch.setattr(ai_checklist, "resolve_provider", lambda: "openai_compat")
    monkeypatch.setattr(get_settings(), "openai_compat_api_key", "sk-V9D14•••••••••••••••••")
    status = client.get("/api/v1/checklists/ai-status", headers=admin_headers).json()
    assert status["configured"] is False and "испорчен" in status["hint"]
    result = client.post("/api/v1/checklists/ai-test", headers=admin_headers).json()
    assert result["ok"] is False and "недопустимые символы" in result["error"]
