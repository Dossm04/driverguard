"""Чек-листы предрейсового осмотра (BE-10, WEB-7).

POST: 7 фото (multipart) → приватный бакет MinIO → ИИ-вердикт по строгой JSON-схеме
(app.ai_checklist) + анкета v2 (app.checklist_items) → итоговый вердикт.
Согласование координатором: approve / approve_with_note / send_to_repair (аудит SEC-4).
"""

import functools
import io
import json
import logging
import time
import uuid
from datetime import UTC, datetime
from urllib.parse import urlparse

from fastapi import APIRouter, Depends, File, Form, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import ai_checklist, storage
from app.ai_checklist import AI_ITEMS, AiError, PhotoIn, compute_verdict
from app.checklist_items import (
    ANSWERABLE_IDS,
    ITEMS,
    SECTIONS,
    SLOT_LABELS,
    effective_items,
    effective_slots,
    questionnaire_verdict,
    validate_answers,
    worst_verdict,
)
from app.config import get_settings
from app.db import get_db
from app.models import AuditLog, Checklist, Driver, Setting, User, Vehicle
from app.schemas import (
    ChecklistAiItemOut,
    ChecklistAnswerIssueOut,
    ChecklistItemCatalogOut,
    ChecklistListOut,
    ChecklistOut,
    ChecklistPhotoOut,
    ChecklistReviewIn,
    ChecklistSlotOut,
    ChecklistStatus,
    ChecklistTemplateOut,
    ChecklistVerdict,
)
from app.security import get_current_user, require_roles

log = logging.getLogger(__name__)
# 1×1 PNG для проверки ключа ИИ (важен сам ответ провайдера, а не содержимое)
TEST_PNG = (
    b"\x89PNG\r\n\x1a\n\x00\x00\x00\rIHDR\x00\x00\x00\x01\x00\x00\x00\x01\x08\x06\x00\x00\x00\x1f\x15\xc4"
    b"\x89\x00\x00\x00\rIDATx\x9cc\xf8\x0f\x00\x01\x01\x01\x00\x18\xdd\x8d\xb4\x00\x00\x00\x00IEND\xaeB`\x82"
)

logger = logging.getLogger(__name__)


@functools.lru_cache(maxsize=1)
def test_image() -> tuple[bytes, str]:
    """Тестовое «фото» для проверки ключа: 640×480 JPEG с кабиной и двумя фарами.
    Крошечный 1×1 PNG серверы моделей (vLLM/litellm) не загружают — «Error while loading
    IMAGE data»; реальные фото из PWA — JPEG до 1600 px, тест должен быть похож на них."""
    try:
        from PIL import Image, ImageDraw
    except ImportError:  # Pillow приходит с reportlab; на всякий случай — старый PNG
        return TEST_PNG, "image/png"
    img = Image.new("RGB", (640, 480), (40, 44, 52))
    d = ImageDraw.Draw(img)
    d.rectangle((120, 120, 520, 400), fill=(90, 100, 120), outline=(200, 200, 200), width=4)
    d.rectangle((160, 150, 480, 260), fill=(30, 40, 60))  # лобовое стекло
    for cx in (190, 450):  # фары
        d.ellipse((cx - 30, 330, cx + 30, 390), fill=(250, 230, 120), outline="white", width=3)
    d.rectangle((100, 400, 540, 430), fill=(60, 60, 60))  # бампер
    d.text((20, 20), "DriverGuard test", fill=(220, 220, 220))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return buf.getvalue(), "image/jpeg"


router = APIRouter(prefix="/checklists", tags=["чек-листы"])

_staff = Depends(require_roles("admin", "coordinator"))
_staff_read = Depends(require_roles("admin", "coordinator", "viewer"))

ALLOWED_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
MAX_PHOTO_BYTES = 4 * 1024 * 1024  # PWA сжимает фото до ~1 МБ; лимит Gemini на запрос — 20 МБ
MAX_EXTRA_PHOTOS = 10  # свои слоты парка (Настройки → Чек-лист) — разумный потолок
# Тег ИИ на плитке фото — по пункту вердикта, который это фото подтверждает
SLOT_AI_KEY = {
    "front_lights": "фары",
    "rear_lights": "фары",
    "tires": "шины",
    "windshield": "лобовое",
    "under_engine": "утечки",
    "left_side": "кузов",
    "right_side": "кузов",
}
SIDE_WORDS = {"left_side": "лев", "right_side": "прав"}
STATUS_AFTER = {
    "approve": "approved",
    "approve_with_note": "approved_with_note",
    "send_to_repair": "sent_to_repair",
}
VERDICT_HUMAN = {
    "допущен": "допущен",
    "требует_внимания": "требует внимания",
    "не_допущен": "не допущен",
}


def _own_driver(db: Session, user: User) -> Driver | None:
    return db.scalar(select(Driver).where(Driver.user_id == user.id))


def _slot_tag(ai: dict, slot: str) -> str:
    item = ai.get(SLOT_AI_KEY.get(slot)) if ai else None
    if not item:
        return "none"
    item_status = item.get("статус", "none")
    if slot in SIDE_WORDS:
        damages = ai.get("повреждения_кузова") or []
        if damages:  # подсвечиваем только тот борт, где найдено повреждение
            word = SIDE_WORDS[slot]
            hit = any(word in (d.get("зона") or "").lower() for d in damages)
            return item_status if hit else "ok"
    return item_status


def _discrepancies(ai: dict, answers: dict) -> list[str]:
    """Пункты «фото-ИИ»: ответ водителя против вердикта модели (docs/checklist_v2.md)."""
    out = []
    for item in ITEMS:
        key = item["ai_key"]
        answer = answers.get(item["id"]) if answers else None
        check = ai.get(key) if (key and ai) else None
        if not check or answer not in ("да", "нет"):
            continue
        comment = check.get("комментарий") or ""
        if answer == "да" and check.get("статус") == "fail":
            out.append(f"{item['id']}: водитель ответил «да», ИИ видит неисправность — {comment}")
        elif answer == "нет" and check.get("статус") == "ok":
            out.append(
                f"{item['id']}: водитель ответил «нет», ИИ проблемы не увидел — проверьте лично"
            )
    return out


def _items_index(db: Session) -> dict:
    """Пункты анкеты по шаблону парка — для расшифровки ответов и вердикта по анкете."""
    return {i["id"]: i for i in effective_items(_template_cfg(db))}


def checklist_out(
    c: Checklist,
    driver: Driver | None,
    vehicle: Vehicle | None,
    reviewer: User | None,
    items_by_id: dict | None = None,
) -> ChecklistOut:
    ai = c.ai_verdict or {}
    answers = c.answers or {}
    photos = []
    for p in c.photos or []:
        slot, key = p["slot"], p.get("key")
        photos.append(
            ChecklistPhotoOut(
                slot=slot,
                label=p.get("label") or SLOT_LABELS.get(slot, slot),
                key=key,
                url=storage.presigned_photo_download(key) if key else None,
                ai=_slot_tag(ai, slot),
            )
        )
    ai_items = [
        ChecklistAiItemOut(
            key=key,
            title=title,
            critical=critical,
            status=ai[key]["статус"],
            confidence=ai[key]["confidence"],
            comment=ai[key].get("комментарий", ""),
        )
        for key, title, critical in AI_ITEMS
        if key in ai
    ]
    _, issues = questionnaire_verdict(answers, items_by_id)
    answerable = (
        {k for k, i in items_by_id.items() if i["method"] in ("answer", "photo_ai")}
        if items_by_id
        else set(ANSWERABLE_IDS)
    )
    answered = sum(1 for k, v in answers.items() if k in answerable and v in ("да", "нет", "н-п"))
    return ChecklistOut(
        id=c.id,
        driver_id=c.driver_id,
        driver_name=driver.name if driver else None,
        vehicle_plate=vehicle.plate if vehicle else None,
        vehicle_model=vehicle.model if vehicle else None,
        created_at=c.created_at,
        verdict=c.verdict or "допущен",
        status=c.status,
        note=c.note,
        reviewed_at=c.reviewed_at,
        reviewed_by_name=reviewer.name if reviewer else None,
        photos=photos,
        ai_items=ai_items,
        body_damage=ai.get("повреждения_кузова") or [],
        ai_meta=ai.get("meta") or {},
        answers=answers or None,
        answered=answered,
        answer_issues=[
            ChecklistAnswerIssueOut(id=i["id"], text=i["text"], criticality=i["criticality"])
            for i in issues
        ],
        discrepancies=_discrepancies(ai, answers),
    )


def _related(db: Session, rows: list[Checklist]) -> tuple[dict, dict, dict]:
    driver_ids = {c.driver_id for c in rows}
    vehicle_ids = {c.vehicle_id for c in rows}
    user_ids = {c.approved_by for c in rows if c.approved_by}
    drivers = {d.id: d for d in db.scalars(select(Driver).where(Driver.id.in_(driver_ids)))}
    vehicles = {v.id: v for v in db.scalars(select(Vehicle).where(Vehicle.id.in_(vehicle_ids)))}
    users = (
        {u.id: u for u in db.scalars(select(User).where(User.id.in_(user_ids)))} if user_ids else {}
    )
    return drivers, vehicles, users


@router.get(
    "/items",
    response_model=list[ChecklistItemCatalogOut],
    dependencies=[Depends(get_current_user)],
)
def checklist_items(db: Session = Depends(get_db)):
    """Анкета для PWA и панели: каталог v2 с правками парка (Настройки → Чек-лист)."""
    return [
        ChecklistItemCatalogOut(**i, section_title=SECTIONS.get(i["section"], i["section"]))
        for i in effective_items(_template_cfg(db))
    ]


def _template_cfg(db: Session) -> dict:
    row = db.get(Setting, "checklist")
    return dict(row.value) if row and isinstance(row.value, dict) else {}


@router.get("/ai-status", dependencies=[_staff_read])
def ai_status():
    """Какой ИИ проверяет фото и почему: провайдер, модель, хост; mock — ключ не задан (демо)."""
    s = get_settings()
    provider = ai_checklist.resolve_provider()
    info: dict = {
        "provider": provider,
        "configured": provider != "mock",
        "model": None,
        "host": None,
    }
    if provider == "openai_compat":
        info["model"] = s.openai_compat_model
        info["host"] = urlparse(s.openai_compat_base_url).netloc
    elif provider == "gemini":
        info["model"] = s.gemini_model
        info["host"] = urlparse(s.gemini_base_url).netloc
    info["hint"] = (
        None
        if provider != "mock"
        else "Ключ не задан: в infra/.env укажите OPENAI_COMPAT_API_KEY и OPENAI_COMPAT_MODEL "
        "(alem.ai, модель с картинками — gemma4) и перезапустите backend"
    )
    if provider == "openai_compat" and not ai_checklist.key_is_valid(s.openai_compat_api_key):
        info["configured"] = False
        info["hint"] = "Ключ испорчен: " + ai_checklist.BAD_KEY_MSG
    return info


@router.post("/ai-test", dependencies=[Depends(require_roles("admin"))])
def ai_test():
    """Проверка ключа: отправляет ИИ одно тестовое изображение и возвращает результат/ошибку."""
    started = time.monotonic()
    try:
        verdict, meta = ai_checklist.verify_photos(
            [PhotoIn("front_lights", *test_image(), "Перёд + фары (тест)")]
        )
    except AiError as exc:
        latency = int((time.monotonic() - started) * 1000)
        return {"ok": False, "error": str(exc)[:300], "latency_ms": latency}
    except Exception as exc:  # noqa: BLE001 — сетевые/HTTP-ошибки провайдера показываем админу
        log.warning("Проверка ИИ не удалась: %s", exc)
        return {
            "ok": False,
            "error": f"{exc.__class__.__name__}: {str(exc)[:200]}",
            "latency_ms": 0,
        }
    return {
        "ok": True,
        "provider": meta.get("provider"),
        "model": meta.get("model"),
        "latency_ms": meta.get("latency_ms", 0),
        "verdict": verdict.вердикт,
        "demo": meta.get("provider") == "mock",
    }


@router.get(
    "/slots", response_model=list[ChecklistSlotOut], dependencies=[Depends(get_current_user)]
)
def checklist_slots(db: Session = Depends(get_db)):
    """Слоты фото для мастера PWA: стандартные минус скрытые парком плюс добавленные."""
    return [ChecklistSlotOut(**s) for s in effective_slots(_template_cfg(db))]


@router.get("/template", response_model=ChecklistTemplateOut, dependencies=[_staff_read])
def checklist_template(db: Session = Depends(get_db)):
    """Редактор Настройки → Чек-лист: все слоты и пункты с флагами и исходными значениями."""
    cfg = _template_cfg(db)
    row = db.get(Setting, "checklist")
    hidden_items = set(cfg.get("hidden_items") or [])
    items = []
    for i in effective_items(cfg, include_hidden=True):
        base_item = next((c for c in ITEMS if c["id"] == i["id"]), None)
        items.append(
            ChecklistItemCatalogOut(
                **i,
                section_title=SECTIONS.get(i["section"], i["section"]),
                enabled=i["id"] not in hidden_items,
                custom=base_item is None,
                default_text=base_item["text"] if base_item else None,
                default_base=base_item["base"] if base_item else None,
                default_criticality=base_item["criticality"] if base_item else None,
            )
        )
    return ChecklistTemplateOut(
        slots=[ChecklistSlotOut(**s) for s in effective_slots(cfg, include_hidden=True)],
        items=items,
        version=row.version if row else 0,
    )


@router.post("", response_model=ChecklistOut, status_code=201)
def create_checklist(
    front_lights: UploadFile | None = File(None, description="Перёд + фары"),
    rear_lights: UploadFile | None = File(None, description="Зад + габариты"),
    left_side: UploadFile | None = File(None, description="Левый борт"),
    right_side: UploadFile | None = File(None, description="Правый борт"),
    tires: UploadFile | None = File(None, description="Шины"),
    windshield: UploadFile | None = File(None, description="Лобовое"),
    under_engine: UploadFile | None = File(None, description="Под двигателем"),
    extra: list[UploadFile] = File(
        [], description="Фото слотов, добавленных парком (по порядку extra_slots)"
    ),
    extra_slots: str = Form("[]", description='JSON: ["cargo", ...] — id слотов для файлов extra'),
    answers: str = Form("{}", description='JSON анкеты: {"Б2": "да", "Г3": "нет", "А5": "184320"}'),
    driver_id: int | None = Form(None, description="Только для сотрудников; водитель — свой"),
    trip_id: int | None = Form(None),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    """Приём 7 фото + анкеты → ИИ-вердикт (KPI-10: ≤30 с на комплект)."""
    if user.role == "driver":
        driver = _own_driver(db, user)
        if driver is None:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Учётка не привязана к водителю")
    elif user.role in ("admin", "coordinator"):
        if driver_id is None:
            raise HTTPException(422, "Укажите driver_id")
        driver = db.get(Driver, driver_id)
        if driver is None:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Водитель не найден")
    else:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав")
    vehicle = driver.vehicle
    if vehicle is None:
        raise HTTPException(status.HTTP_409_CONFLICT, "За водителем не закреплена машина")

    try:
        answers_dict = json.loads(answers or "{}")
    except json.JSONDecodeError as exc:
        raise HTTPException(422, "answers: невалидный JSON") from exc
    if not isinstance(answers_dict, dict):
        raise HTTPException(422, "answers: ожидается объект {пункт: ответ}")
    template_cfg = _template_cfg(db)
    items = effective_items(template_cfg)
    items_by_id = {i["id"]: i for i in items}
    errors = validate_answers(answers_dict, items_by_id)
    if errors:
        raise HTTPException(422, "Анкета: " + "; ".join(errors))
    missing = [
        i["id"]
        for i in items
        if i["base"] and i["method"] != "auto" and i["id"] not in answers_dict
    ]
    if missing:  # без ответа на базовые пункты «допущен» получить нельзя
        raise HTTPException(422, "Анкета: не заполнены обязательные пункты: " + ", ".join(missing))

    uploads: dict[str, UploadFile | None] = {
        "front_lights": front_lights,
        "rear_lights": rear_lights,
        "left_side": left_side,
        "right_side": right_side,
        "tires": tires,
        "windshield": windshield,
        "under_engine": under_engine,
    }
    try:
        extra_names = json.loads(extra_slots or "[]")
    except json.JSONDecodeError as exc:
        raise HTTPException(422, "extra_slots: невалидный JSON") from exc
    if not isinstance(extra_names, list) or len(extra_names) != len(extra):
        raise HTTPException(422, "extra_slots: список id должен совпадать с числом файлов extra")
    if len(extra) > MAX_EXTRA_PHOTOS:
        raise HTTPException(422, f"extra: не более {MAX_EXTRA_PHOTOS} дополнительных фото")
    for name, upload in zip(extra_names, extra, strict=True):
        uploads[str(name)] = upload
    slots = effective_slots(template_cfg)
    photos_in: list[PhotoIn] = []
    for s in slots:
        slot, label = s["slot"], s["label"]
        upload = uploads.get(slot)
        if upload is None or not upload.filename:
            raise HTTPException(422, f"{label}: нет фото")
        content_type = (upload.content_type or "").lower()
        if content_type not in ALLOWED_TYPES:
            raise HTTPException(
                422, f"{label}: нужен JPEG/PNG/WebP, получен {content_type or 'неизвестный тип'}"
            )
        data = upload.file.read(MAX_PHOTO_BYTES + 1)  # не читаем 100 МБ в память ради проверки
        if not data:
            raise HTTPException(422, f"{label}: пустой файл")
        if len(data) > MAX_PHOTO_BYTES:
            raise HTTPException(
                status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, f"{label}: файл больше 4 МБ"
            )
        photos_in.append(PhotoIn(slot, data, content_type, label))

    now = datetime.now(UTC)
    batch = uuid.uuid4().hex
    stored = []
    for photo in photos_in:
        key = storage.photo_key(
            driver.id, batch, photo.slot, ALLOWED_TYPES[photo.content_type], now.strftime("%Y-%m")
        )
        storage.put_photo(key, photo.data, photo.content_type)
        stored.append(
            {
                "slot": photo.slot,
                "key": key,
                "content_type": photo.content_type,
                "label": photo.label,
            }
        )

    try:
        verdict, meta = ai_checklist.verify_photos(photos_in)
    except AiError as exc:
        # Провайдер недоступен — чек-лист не теряем и водителю не показываем техническую
        # ошибку: сохраняем с «требует внимания», фото проверит координатор. Причина — в лог
        # и в meta (видна в панели), но не за «допущен» (правило 8).
        logger.warning("ИИ-проверка не удалась, чек-лист сохранён без ИИ: %s", exc)
        verdict = ai_checklist.normalize(ai_checklist.unavailable_verdict())
        meta = {"provider": "unavailable", "model": None, "latency_ms": 0, "error": str(exc)[:200]}
    ai_verdict = compute_verdict(verdict)
    if verdict.вердикт != ai_verdict:
        meta["model_verdict"] = verdict.вердикт  # сверка: сервер считает вердикт сам
    q_verdict, _ = questionnaire_verdict(answers_dict, items_by_id)

    checklist = Checklist(
        trip_id=trip_id,
        driver_id=driver.id,
        vehicle_id=vehicle.id,
        photos=stored,
        ai_verdict={**verdict.model_dump(), "meta": meta},
        answers=answers_dict,
        verdict=worst_verdict(ai_verdict, q_verdict),
        status="pending",
        created_at=now,
    )
    db.add(checklist)
    db.commit()
    db.refresh(checklist)
    return checklist_out(checklist, driver, vehicle, None, items_by_id)


@router.get("", response_model=ChecklistListOut, dependencies=[_staff_read])
def list_checklists(
    checklist_status: ChecklistStatus | None = Query(default=None, alias="status"),
    verdict: ChecklistVerdict | None = None,
    driver_id: int | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
):
    q = select(Checklist)
    if checklist_status is not None:
        q = q.where(Checklist.status == checklist_status)
    if verdict is not None:
        q = q.where(Checklist.verdict == verdict)
    if driver_id is not None:
        q = q.where(Checklist.driver_id == driver_id)
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(
        q.order_by(Checklist.created_at.desc(), Checklist.id.desc())
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    drivers, vehicles, users = _related(db, rows)
    items_by_id = _items_index(db)
    return ChecklistListOut(
        items=[
            checklist_out(
                c,
                drivers.get(c.driver_id),
                vehicles.get(c.vehicle_id),
                users.get(c.approved_by),
                items_by_id,
            )
            for c in rows
        ],
        total=total,
        page=page,
        page_size=page_size,
    )


@router.get("/{checklist_id}", response_model=ChecklistOut)
def get_checklist(
    checklist_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    checklist = db.get(Checklist, checklist_id)
    if checklist is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Чек-лист не найден")
    if user.role == "driver":
        own = _own_driver(db, user)
        if own is None or own.id != checklist.driver_id:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Доступен только собственный чек-лист")
    elif user.role not in ("admin", "coordinator", "viewer"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав")
    drivers, vehicles, users = _related(db, [checklist])
    return checklist_out(
        checklist,
        drivers.get(checklist.driver_id),
        vehicles.get(checklist.vehicle_id),
        users.get(checklist.approved_by),
        _items_index(db),
    )


@router.post("/{checklist_id}/approve", response_model=ChecklistOut)
def review_checklist(
    checklist_id: int,
    body: ChecklistReviewIn,
    db: Session = Depends(get_db),
    user: User = Depends(require_roles("admin", "coordinator")),
):
    """Согласовать выезд / согласовать с отметкой / отправить на устранение (US-5)."""
    checklist = db.get(Checklist, checklist_id)
    if checklist is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Чек-лист не найден")
    if checklist.status != "pending":
        raise HTTPException(status.HTTP_409_CONFLICT, "Чек-лист уже обработан")
    if body.action == "approve" and checklist.verdict != "допущен":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Вердикт «{VERDICT_HUMAN.get(checklist.verdict, checklist.verdict)}»: "
            "согласуйте с отметкой или отправьте на устранение",
        )
    note = (body.note or "").strip() or None
    if body.action == "approve_with_note" and not note:
        raise HTTPException(422, "Нужна отметка координатора")

    now = datetime.now(UTC)
    checklist.status = STATUS_AFTER[body.action]
    checklist.approved_by = user.id
    checklist.reviewed_at = now
    checklist.note = note
    db.add(
        AuditLog(
            user_id=user.id,
            action="checklist_review",
            entity=f"checklist:{checklist.id}",
            before={"status": "pending"},
            after={"status": checklist.status, "note": note},
            ts=now,
        )
    )
    db.commit()
    db.refresh(checklist)
    drivers, vehicles, _ = _related(db, [checklist])
    return checklist_out(
        checklist,
        drivers.get(checklist.driver_id),
        vehicles.get(checklist.vehicle_id),
        user,
        _items_index(db),
    )
