"""Чек-листы (BE-10): парсер/вердикт ИИ, анкета v2, приём 7 фото, согласование, RBAC."""

import json
import struct
import zlib
from datetime import UTC, datetime

import pytest

from app import ai_checklist, storage
from app.ai_checklist import AiError, ItemCheck, compute_verdict, mock_verdict, normalize
from app.checklist_items import ITEMS, PHOTO_SLOTS, questionnaire_verdict, validate_answers
from app.models import AuditLog, User
from app.security import hash_secret


def _png(size: int = 32) -> bytes:
    rows = b"".join(b"\x00" + b"\x80\x80\x80" * size for _ in range(size))

    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data))

    return (
        b"\x89PNG\r\n\x1a\n"
        + chunk(b"IHDR", struct.pack(">IIBBBBB", size, size, 8, 2, 0, 0, 0))
        + chunk(b"IDAT", zlib.compress(rows))
        + chunk(b"IEND", b"")
    )


PNG = _png()


def _files(skip: str | None = None, content_type: str = "image/png") -> list:
    return [(slot, (f"{slot}.png", PNG, content_type)) for slot, _ in PHOTO_SLOTS if slot != skip]


def _answers(**overrides: str) -> str:
    data = {i["id"]: "да" for i in ITEMS if i["method"] in ("answer", "photo_ai")}
    data["Е7"] = "н-п"
    data["А5"] = "184320"
    data.update(overrides)
    return json.dumps(data, ensure_ascii=False)


def _post(client, headers, files=None, answers=None, driver_id=1):
    data = {"answers": answers or _answers()}
    if driver_id is not None:
        data["driver_id"] = str(driver_id)
    return client.post("/api/v1/checklists", files=files or _files(), data=data, headers=headers)


@pytest.fixture(autouse=True)
def fake_storage(monkeypatch):
    """MinIO в тестах не поднимаем: фиксируем ключи, presigned — детерминированный URL."""
    saved: dict[str, int] = {}
    monkeypatch.setattr(
        storage, "put_photo", lambda key, data, ct: saved.__setitem__(key, len(data))
    )
    monkeypatch.setattr(storage, "presigned_photo_download", lambda key: f"http://minio.test/{key}")
    return saved


# ── Чистые правила ────────────────────────────────────────────────────
def test_catalog_matches_spec():
    ids = [i["id"] for i in ITEMS]
    assert len(ids) == len(set(ids)) == 42
    assert sum(1 for i in ITEMS if i["base"]) == 20
    assert sum(1 for i in ITEMS if i["criticality"] == "critical") == 22
    assert [i["id"] for i in ITEMS if i["method"] == "auto"] == ["А1", "А2", "А3", "А4", "З1"]


def test_ai_verdict_rules_tz_6_1_7():
    v = mock_verdict()
    assert compute_verdict(v) == "допущен"
    # критический fail с confidence ≥0.8 → не допущен
    v.фары = ItemCheck(статус="fail", confidence=0.91, комментарий="левая фара не горит")
    assert compute_verdict(v) == "не_допущен"
    # тот же fail, но confidence 0.7 — только внимание
    v.фары.confidence = 0.7
    assert compute_verdict(v) == "требует_внимания"
    # некритичный fail (лобовое) — внимание (TC-11)
    v = mock_verdict()
    v.лобовое = ItemCheck(статус="fail", confidence=0.89, комментарий="трещина")
    assert compute_verdict(v) == "требует_внимания"
    # confidence <0.6 → «не видно» + просьба повторить фото
    v = normalize(
        mock_verdict().model_copy(update={"шины": ItemCheck(статус="ok", confidence=0.4)})
    )
    assert v.шины.статус == "not_visible"
    assert "повторите фото" in v.шины.комментарий
    assert compute_verdict(v) == "требует_внимания"


def test_questionnaire_rules():
    assert questionnaire_verdict({"Б1": "нет"})[0] == "требует_внимания"
    assert questionnaire_verdict({"Г3": "нет", "Б1": "нет"})[0] == "не_допущен"
    assert questionnaire_verdict({"Е7": "н-п", "Г3": "да"})[0] == "допущен"
    errors = validate_answers({"XX": "да", "А1": "да", "Г3": "может", "Г1": "н-п", "А5": ""})
    assert len(errors) == 5


def test_gemini_invalid_json_retried_once(monkeypatch):
    monkeypatch.setattr(ai_checklist, "resolve_provider", lambda: "gemini")
    replies = iter(['{"мусор": true}', mock_verdict().model_dump_json()])
    calls = []
    monkeypatch.setattr(
        ai_checklist,
        "_gemini_generate",
        lambda parts: (calls.append(len(parts)), (next(replies), {"totalTokenCount": 7}))[1],
    )
    verdict, meta = ai_checklist.verify_photos([ai_checklist.PhotoIn("tires", PNG, "image/png")])
    assert verdict.фары.статус == "ok"
    assert meta["attempts"] == 2 and meta["provider"] == "gemini"
    assert calls[1] == calls[0] + 1  # повтор — с корректирующей подсказкой

    monkeypatch.setattr(ai_checklist, "_gemini_generate", lambda parts: ("not json", {}))
    with pytest.raises(AiError, match="дважды"):
        ai_checklist.verify_photos([ai_checklist.PhotoIn("tires", PNG, "image/png")])


def test_openai_compat_format_ladder_and_cleanup(monkeypatch):
    """alem.ai (OpenAI-совместимый): json_schema отвергнут → json_object; ответ с
    <think> и ```json-обёрткой всё равно парсится; meta несёт формат и хост."""
    monkeypatch.setattr(ai_checklist, "resolve_provider", lambda: "openai_compat")
    settings = ai_checklist.get_settings()
    monkeypatch.setattr(settings, "openai_compat_base_url", "https://llm.alem.ai/v1")
    monkeypatch.setattr(settings, "openai_compat_model", "qwen3-8")
    seen: list[str | None] = []

    def fake_chat(messages, response_format):
        seen.append(response_format["type"] if response_format else None)
        if response_format and response_format["type"] == "json_schema":
            raise ai_checklist._UnsupportedFormat("response_format not supported")
        assert messages[0]["role"] == "system" and "JSON Schema" in messages[0]["content"]
        assert messages[1]["content"][1]["image_url"]["url"].startswith("data:image/png;base64,")
        body = mock_verdict().model_dump_json()
        return f"<think>смотрю фары…</think>```json\n{body}\n```", {"total_tokens": 42}

    monkeypatch.setattr(ai_checklist, "_openai_chat", fake_chat)
    verdict, meta = ai_checklist.verify_photos([ai_checklist.PhotoIn("tires", PNG, "image/png")])
    assert verdict.фары.статус == "ok"
    assert seen == ["json_schema", "json_object"]
    assert meta["provider"] == "openai_compat" and meta["format"] == "json_object"
    assert meta["host"] == "llm.alem.ai" and meta["tokens"] == 42 and meta["attempts"] == 1


def test_openai_compat_retry_then_error(monkeypatch):
    monkeypatch.setattr(ai_checklist, "resolve_provider", lambda: "openai_compat")
    calls = []

    def fake_chat(messages, fmt):
        calls.append(len(messages))
        return "нет", {}

    monkeypatch.setattr(ai_checklist, "_openai_chat", fake_chat)
    with pytest.raises(AiError, match="дважды"):
        ai_checklist.verify_photos([ai_checklist.PhotoIn("tires", PNG, "image/png")])
    assert calls == [2, 3]  # вторая попытка — с корректирующей подсказкой


def test_provider_resolution(monkeypatch):
    settings = ai_checklist.get_settings()
    monkeypatch.setattr(settings, "ai_provider", "auto")
    monkeypatch.setattr(settings, "openai_compat_api_key", "")
    monkeypatch.setattr(settings, "gemini_api_key", "")
    assert ai_checklist.resolve_provider() == "mock"
    monkeypatch.setattr(settings, "gemini_api_key", "g")
    assert ai_checklist.resolve_provider() == "gemini"
    monkeypatch.setattr(settings, "openai_compat_api_key", "sk")
    monkeypatch.setattr(settings, "openai_compat_base_url", "https://llm.alem.ai/v1")
    assert ai_checklist.resolve_provider() == "openai_compat"  # alem.ai в приоритете
    monkeypatch.setattr(settings, "ai_provider", "mock")
    assert ai_checklist.resolve_provider() == "mock"
    schema = ai_checklist.JSON_SCHEMA
    assert schema["type"] == "object" and schema["additionalProperties"] is False
    assert schema["properties"]["фары"]["properties"]["статус"]["enum"][0] == "ok"


# ── API ───────────────────────────────────────────────────────────────
def test_catalog_endpoint(client, admin_headers):
    items = client.get("/api/v1/checklists/items", headers=admin_headers).json()
    assert len(items) == 42
    lamp = next(i for i in items if i["id"] == "Г3")
    assert lamp["ai_key"] == "фары" and lamp["base"] and lamp["section_title"] == "Свет и электрика"


def test_create_list_detail_mock(client, base_fleet, admin_headers, fake_storage):
    resp = _post(client, admin_headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["verdict"] == "допущен" and body["status"] == "pending"
    assert body["ai_meta"]["provider"] == "mock"
    assert [p["slot"] for p in body["photos"]] == [s for s, _ in PHOTO_SLOTS]
    assert all(
        p["url"].startswith("http://minio.test/checklists/1/") and p["ai"] == "ok"
        for p in body["photos"]
    )
    assert len(fake_storage) == 7
    assert [i["key"] for i in body["ai_items"]] == [
        "фары",
        "шины",
        "утечки",
        "лобовое",
        "зеркала",
        "кузов",
    ]
    assert body["answered"] == 36 and body["answer_issues"] == [] and body["discrepancies"] == []
    assert body["driver_name"] == "Иванов А.С." and body["vehicle_plate"] == "KZ 4521 AB"

    listed = client.get("/api/v1/checklists", headers=admin_headers).json()
    assert listed["total"] == 1 and listed["items"][0]["id"] == body["id"]
    assert (
        client.get("/api/v1/checklists?status=approved", headers=admin_headers).json()["total"] == 0
    )
    detail = client.get(f"/api/v1/checklists/{body['id']}", headers=admin_headers).json()
    assert detail["answers"]["А5"] == "184320"


def test_create_validation(client, base_fleet, admin_headers):
    assert _post(client, admin_headers, files=_files(skip="tires")).status_code == 422
    bad_type = _post(client, admin_headers, files=_files(content_type="text/plain"))
    assert bad_type.status_code == 422 and "JPEG/PNG/WebP" in bad_type.json()["detail"]
    bad_answer = _post(client, admin_headers, answers=json.dumps({"XX": "да"}))
    assert bad_answer.status_code == 422 and "неизвестный пункт" in bad_answer.json()["detail"]
    assert _post(client, admin_headers, answers="{oops").status_code == 422
    assert _post(client, admin_headers, driver_id=None).status_code == 422
    assert _post(client, admin_headers, driver_id=99).status_code == 404


def test_questionnaire_overrides_ai_and_flags_discrepancy(client, base_fleet, admin_headers):
    body = _post(client, admin_headers, answers=_answers(Г3="нет")).json()
    assert body["verdict"] == "не_допущен"
    assert [i["id"] for i in body["answer_issues"]] == ["Г3"]
    assert any(d.startswith("Г3:") for d in body["discrepancies"])


def test_review_rules_and_audit(client, db, base_fleet, admin_headers):
    ok_id = _post(client, admin_headers).json()["id"]
    bad_id = _post(client, admin_headers, answers=_answers(Г3="нет")).json()["id"]

    blocked = client.post(
        f"/api/v1/checklists/{bad_id}/approve", json={"action": "approve"}, headers=admin_headers
    )
    assert blocked.status_code == 409 and "не допущен" in blocked.json()["detail"]
    no_note = client.post(
        f"/api/v1/checklists/{bad_id}/approve",
        json={"action": "approve_with_note"},
        headers=admin_headers,
    )
    assert no_note.status_code == 422
    repair = client.post(
        f"/api/v1/checklists/{bad_id}/approve",
        json={"action": "send_to_repair", "note": "Заменить лампу"},
        headers=admin_headers,
    ).json()
    assert repair["status"] == "sent_to_repair" and repair["note"] == "Заменить лампу"
    assert repair["reviewed_by_name"] == "Тест Админ" and repair["reviewed_at"]

    approved = client.post(
        f"/api/v1/checklists/{ok_id}/approve", json={"action": "approve"}, headers=admin_headers
    ).json()
    assert approved["status"] == "approved"
    again = client.post(
        f"/api/v1/checklists/{ok_id}/approve", json={"action": "approve"}, headers=admin_headers
    )
    assert again.status_code == 409

    from sqlalchemy import select

    audit = db.scalars(select(AuditLog).where(AuditLog.action == "checklist_review")).all()
    assert len(audit) == 2 and audit[0].after["status"] in ("sent_to_repair", "approved")
    assert (
        client.get("/api/v1/checklists?status=pending", headers=admin_headers).json()["total"] == 0
    )


def test_rbac_driver_and_viewer(client, db, base_fleet, admin_headers, viewer_headers):
    driver = base_fleet["driver"]
    account = User(
        role="driver",
        phone=driver.phone,
        pin_hash=hash_secret("4321"),
        name=driver.name,
        created_at=datetime.now(UTC),
    )
    db.add(account)
    db.flush()
    driver.user_id = account.id
    db.commit()
    from app import security

    security._pin_attempts.clear()
    token = client.post(
        "/api/v1/auth/driver-login", json={"phone": driver.phone, "pin": "4321"}
    ).json()["access_token"]
    driver_headers = {"Authorization": f"Bearer {token}"}

    own = _post(client, driver_headers, driver_id=None)  # водитель — только свой чек-лист
    assert own.status_code == 201, own.text
    checklist_id = own.json()["id"]
    assert (
        client.get(f"/api/v1/checklists/{checklist_id}", headers=driver_headers).status_code == 200
    )
    assert client.get("/api/v1/checklists", headers=driver_headers).status_code == 403
    assert (
        client.post(
            f"/api/v1/checklists/{checklist_id}/approve",
            json={"action": "approve"},
            headers=driver_headers,
        ).status_code
        == 403
    )
    assert client.get("/api/v1/checklists", headers=viewer_headers).json()["total"] == 1
    assert (
        client.post(
            f"/api/v1/checklists/{checklist_id}/approve",
            json={"action": "approve"},
            headers=viewer_headers,
        ).status_code
        == 403
    )


def test_create_when_ai_unavailable_keeps_checklist(client, base_fleet, admin_headers, monkeypatch):
    """Провайдер ИИ упал → не 502, а чек-лист «требует внимания» для ручной проверки."""

    def boom(photos):
        raise ai_checklist.AiError("OpenAI-совместимый API недоступен: connection refused")

    monkeypatch.setattr(ai_checklist, "verify_photos", boom)
    resp = _post(client, admin_headers)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["verdict"] == "требует_внимания"
    assert body["ai_meta"]["provider"] == "unavailable"
    assert "connection refused" in body["ai_meta"]["error"]
    assert all(i["status"] == "not_visible" for i in body["ai_items"])
