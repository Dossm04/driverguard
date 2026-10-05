"""Настройки → Чек-лист: скрыть/поправить/добавить пункты и слоты фото; приём по шаблону."""

import io
import json

import pytest

from app import ai_checklist, storage

PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
    b"\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x01\x01\x01\x00\x18\xdd\x8d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)
FIXED = [
    "front_lights",
    "rear_lights",
    "left_side",
    "right_side",
    "tires",
    "windshield",
    "under_engine",
]


@pytest.fixture(autouse=True)
def fake_infra(monkeypatch):
    monkeypatch.setattr(storage, "put_photo", lambda key, data, ct: None)
    monkeypatch.setattr(storage, "presigned_photo_download", lambda key: f"http://minio.test/{key}")
    monkeypatch.setattr(ai_checklist, "resolve_provider", lambda: "mock")


def _answers(client, headers) -> dict:
    items = client.get("/api/v1/checklists/items", headers=headers).json()
    out = {}
    for i in items:
        if i["method"] == "auto" or not i["base"]:
            continue
        out[i["id"]] = "184320" if i["method"] == "input" else "да"
    return out


def _files(slots):
    return [(slot, (f"{slot}.png", io.BytesIO(PNG), "image/png")) for slot in slots]


TEMPLATE = {
    "hidden_slots": ["under_engine"],
    "custom_slots": [{"slot": "cargo", "label": "Груз и тент", "hint": "Крепление груза целиком"}],
    "hidden_items": ["Б5"],
    "item_overrides": {"Б6": {"text": "АКБ закреплена, клеммы чистые", "criticality": "critical"}},
    "custom_items": [
        {"id": "П1", "text": "Огнетушитель заряжен", "base": True, "criticality": "critical"}
    ],
}


def test_template_applies_to_items_slots_and_editor(client, admin_headers):
    r = client.put("/api/v1/settings/checklist", json={"value": TEMPLATE}, headers=admin_headers)
    assert r.status_code == 200, r.text
    items = {
        i["id"]: i for i in client.get("/api/v1/checklists/items", headers=admin_headers).json()
    }
    assert "Б5" not in items and items["П1"]["section_title"].startswith("Дополнительно")
    assert (
        items["Б6"]["text"] == "АКБ закреплена, клеммы чистые"
        and items["Б6"]["criticality"] == "critical"
    )
    slots = [
        s["slot"] for s in client.get("/api/v1/checklists/slots", headers=admin_headers).json()
    ]
    assert "under_engine" not in slots and slots[-1] == "cargo"
    tpl = client.get("/api/v1/checklists/template", headers=admin_headers).json()
    b6 = next(i for i in tpl["items"] if i["id"] == "Б6")
    assert b6["default_text"].startswith("АКБ") and b6["default_criticality"] == "attention"
    assert next(i for i in tpl["items"] if i["id"] == "Б5")["enabled"] is False
    assert next(s for s in tpl["slots"] if s["slot"] == "under_engine")["enabled"] is False
    assert tpl["version"] == 1


def test_template_validation(client, admin_headers):
    bad = {"hidden_slots": FIXED, "custom_slots": []}
    r = client.put("/api/v1/settings/checklist", json={"value": bad}, headers=admin_headers)
    assert r.status_code == 422 and "хотя бы один слот" in r.text
    bad = {"custom_items": [{"id": "Б9", "text": "неправильный id"}]}
    assert (
        client.put(
            "/api/v1/settings/checklist", json={"value": bad}, headers=admin_headers
        ).status_code
        == 422
    )
    bad = {"hidden_items": ["Я9"]}
    assert (
        client.put(
            "/api/v1/settings/checklist", json={"value": bad}, headers=admin_headers
        ).status_code
        == 422
    )


def test_checklist_follows_template(client, base_fleet, admin_headers):
    client.put("/api/v1/settings/checklist", json={"value": TEMPLATE}, headers=admin_headers)
    driver_id = base_fleet["driver"].id
    answers = _answers(client, admin_headers)
    assert "П1" in answers and "Б5" not in answers
    # без своего слота cargo — 422 с его названием; under_engine скрыт и не нужен
    files = _files([s for s in FIXED if s != "under_engine"])
    r = client.post(
        "/api/v1/checklists",
        files=files,
        data={"answers": json.dumps(answers), "driver_id": driver_id},
        headers=admin_headers,
    )
    assert r.status_code == 422 and "Груз и тент" in r.text
    files = files + [("extra", ("cargo.png", io.BytesIO(PNG), "image/png"))]
    r = client.post(
        "/api/v1/checklists",
        files=files,
        data={
            "answers": json.dumps(answers),
            "driver_id": driver_id,
            "extra_slots": json.dumps(["cargo"]),
        },
        headers=admin_headers,
    )
    assert r.status_code == 201, r.text
    photos = {p["slot"]: p for p in r.json()["photos"]}
    assert "under_engine" not in photos and photos["cargo"]["label"] == "Груз и тент"
    # свой пункт «нет» с критичностью → не допущен
    answers["П1"] = "нет"
    r = client.post(
        "/api/v1/checklists",
        files=files,
        data={
            "answers": json.dumps(answers),
            "driver_id": driver_id,
            "extra_slots": json.dumps(["cargo"]),
        },
        headers=admin_headers,
    )
    assert r.status_code == 201 and r.json()["verdict"] == "не_допущен"
    r = client.get(f"/api/v1/checklists/{r.json()['id']}", headers=admin_headers)
    assert any(i["id"] == "П1" for i in r.json()["answer_issues"])
