"""События: батч-приём с идемпотентным upsert по UUID (BE-4), фильтры, клипы (BE-5)."""

import uuid as uuid_mod
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, or_, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, joinedload

from app import storage
from app.db import get_db
from app.models import AuditLog, Device, Driver, Event, RetrainQueueItem, Trip
from app.schemas import (
    ClipDownloadOut,
    ClipUploadOut,
    EventBatchOut,
    EventIn,
    EventListOut,
    EventOut,
    EventStatus,
    EventType,
    ReviewIn,
)
from app.security import get_device_or_user, phone_for, require_roles
from app.ws import manager as ws_manager

router = APIRouter(prefix="/events", tags=["события"])

# Чтение ленты событий — только сотрудники (SEC-1); водитель видит свои события в профиле
_staff_read = Depends(require_roles("admin", "coordinator", "viewer"))


def event_out(e: Event) -> EventOut:
    out = EventOut.model_validate(e)
    if e.driver:
        out.driver_name = e.driver.name
        out.driver_phone = e.driver.phone
        out.vehicle_plate = e.driver.vehicle.plate if e.driver.vehicle else None
    return out


@router.post("", response_model=EventBatchOut)
def ingest_events(
    batch: list[EventIn],
    db: Session = Depends(get_db),
    sender=Depends(get_device_or_user),
):
    """Приём батча (до 100 событий, DEV-19). Повторная отправка не создаёт дубликатов."""
    if len(batch) > 100:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Не более 100 событий")

    devices_by_serial = {
        d.serial: d for d in db.scalars(select(Device).options(joinedload(Device.vehicle))).all()
    }
    now = datetime.now(UTC)
    if isinstance(sender, Device):
        sender.last_seen = now  # поток событий подтверждает, что устройство онлайн
    rows = []
    for item in batch:
        if isinstance(sender, Device):
            # Устройство говорит только за себя: serial/driver_id из тела не доверяем (SEC)
            device = sender
            driver_id = device.vehicle.driver_id if device.vehicle else None
            item_trip_id = item.trip_id
        else:
            device = devices_by_serial.get(item.device_serial) if item.device_serial else None
            driver_id = item.driver_id
            item_trip_id = item.trip_id
            if driver_id is None and item_trip_id is not None:
                trip = db.get(Trip, item_trip_id)
                driver_id = trip.driver_id if trip else None
            if driver_id is None and device is not None and device.vehicle is not None:
                driver_id = device.vehicle.driver_id
        # Рейс — тот, что шёл в момент события (офлайн-очередь может прийти позже),
        # иначе «событий за рейс» в отчётах для реальных устройств всегда 0
        trip_id = None
        if item_trip_id is not None:
            trip = db.get(Trip, item_trip_id)
            if trip is not None and trip.driver_id == driver_id:
                trip_id = trip.id
        if trip_id is None and driver_id is not None:
            trip_id = _trip_at(db, driver_id, item.ts)
        rows.append(
            {
                "uuid": item.uuid,
                "trip_id": trip_id,
                "device_id": device.id if device else None,
                "driver_id": driver_id,
                "type": item.type,
                "severity": item.severity,
                "confidence": item.confidence,
                "ts": item.ts,
                "lat": item.lat,
                "lon": item.lon,
                "gps_valid": item.gps_valid,
                "speed_kmh": item.speed_kmh,
                "value": item.value,
                "context": item.context,
                "measurements": (
                    item.measurements.model_dump(exclude_none=True) if item.measurements else None
                ),
                "status": "new",
                "is_demo": item.is_demo,
                "created_at": now,
            }
        )
    if not rows:
        return EventBatchOut(accepted=0, duplicates=0)

    stmt = (
        pg_insert(Event)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["uuid"])
        .returning(Event.uuid)  # rowcount у executemany ненадёжен — считаем вставленные строки
    )
    inserted = [r[0] for r in db.execute(stmt).fetchall()]
    db.commit()
    if inserted:
        fresh = db.scalars(
            select(Event)
            .where(Event.uuid.in_(inserted))
            .options(joinedload(Event.driver).joinedload(Driver.vehicle))
        ).all()
        for e in fresh:  # live-канал: новые события (BE-16)
            ws_manager.broadcast_threadsafe(
                {"type": "event", "event": event_out(e).model_dump(mode="json")}
            )
    return EventBatchOut(accepted=len(inserted), duplicates=len(rows) - len(inserted))


def _trip_at(db: Session, driver_id: int, ts: datetime) -> int | None:
    """id рейса водителя, шедшего в момент ts (активный или уже завершённый позже ts)."""
    trip = db.scalar(
        select(Trip)
        .where(
            Trip.driver_id == driver_id,
            Trip.started_at <= ts,
            or_(Trip.ended_at.is_(None), Trip.ended_at >= ts),
        )
        .order_by(Trip.started_at.desc())
    )
    return trip.id if trip else None


@router.get("", response_model=EventListOut)
def list_events(
    type: EventType | None = None,
    driver_id: int | None = None,
    event_status: EventStatus | None = Query(default=None, alias="status"),
    severity: str | None = None,
    ts_from: datetime | None = None,
    ts_to: datetime | None = None,
    page: int = Query(default=1, ge=1),
    page_size: int = Query(default=50, ge=1, le=200),
    db: Session = Depends(get_db),
    user=_staff_read,
):
    q = select(Event)
    if type is not None:
        q = q.where(Event.type == type)
    if driver_id is not None:
        q = q.where(Event.driver_id == driver_id)
    if event_status is not None:
        q = q.where(Event.status == event_status)
    if severity is not None:
        q = q.where(Event.severity == severity)
    if ts_from is not None:
        q = q.where(Event.ts >= ts_from)
    if ts_to is not None:
        q = q.where(Event.ts < ts_to)

    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    items = db.scalars(
        q.options(joinedload(Event.driver).joinedload(Driver.vehicle))
        .order_by(Event.ts.desc(), Event.uuid.desc())  # детерминированная пагинация
        .offset((page - 1) * page_size)
        .limit(page_size)
    ).all()
    out_items = [event_out(e) for e in items]
    for o in out_items:
        o.driver_phone = phone_for(user, o.driver_phone)
    return EventListOut(items=out_items, total=total, page=page, page_size=page_size)


@router.get("/{event_uuid}", response_model=EventOut)
def get_event(event_uuid: uuid_mod.UUID, db: Session = Depends(get_db), user=_staff_read):
    event = db.scalar(
        select(Event)
        .where(Event.uuid == event_uuid)
        .options(joinedload(Event.driver).joinedload(Driver.vehicle))
    )
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Событие не найдено")
    out = event_out(event)
    out.driver_phone = phone_for(user, out.driver_phone)
    return out


@router.post("/{event_uuid}/review", response_model=EventOut)
def review_event(
    event_uuid: uuid_mod.UUID,
    body: ReviewIn,
    db: Session = Depends(get_db),
    user=Depends(require_roles("admin", "coordinator")),
):
    """Review координатора (BE-8, US-7): «ложное» возвращает баллы водителю,
    кадр уходит в очередь дообучения; всё действие — в аудит (SEC-4)."""
    event = db.scalar(
        select(Event)
        .where(Event.uuid == event_uuid)
        .options(joinedload(Event.driver).joinedload(Driver.vehicle))
    )
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Событие не найдено")
    before = event.status
    now = datetime.now(UTC)
    event.status = body.status
    event.reviewed_by = user.id
    event.reviewed_at = now
    db.add(
        AuditLog(
            user_id=user.id,
            action="event_review",
            entity=f"event:{event_uuid}",
            before={"status": before},
            after={"status": body.status, **({"comment": body.comment} if body.comment else {})},
            ts=now,
        )
    )
    pending_item = db.scalar(
        select(RetrainQueueItem).where(
            RetrainQueueItem.event_uuid == event_uuid,
            RetrainQueueItem.exported_at.is_(None),
        )
    )
    if body.status == "false_positive":
        if pending_item is None:  # без дублей при повторном review
            db.add(
                RetrainQueueItem(
                    event_uuid=event_uuid,
                    frame_key=event.clip_key,
                    label_hint=event.type,
                    created_at=now,
                )
            )
    elif pending_item is not None:
        # событие вернули в confirmed — из очереди дообучения убираем
        db.delete(pending_item)
    db.commit()
    db.refresh(event)
    ws_manager.broadcast_threadsafe(
        {"type": "event_review", "uuid": str(event_uuid), "status": body.status}
    )
    return event_out(event)


@router.get("/{event_uuid}/clip-url", response_model=ClipDownloadOut, dependencies=[_staff_read])
def clip_download_url(
    event_uuid: uuid_mod.UUID, internal: bool = False, db: Session = Depends(get_db)
):
    """Presigned-ссылка на просмотр клипа (BE-5). internal=true — адрес внутри docker-сети
    (minio:9000) для бота/сервисов, которым публичный localhost:9000 недоступен."""
    event = db.get(Event, event_uuid)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Событие не найдено")
    if not event.clip_key:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "У события нет клипа")
    return ClipDownloadOut(url=storage.presigned_clip_download(event.clip_key, internal=internal))


@router.post("/{event_uuid}/clip-upload-url", response_model=ClipUploadOut)
def clip_upload_url(
    event_uuid: uuid_mod.UUID,
    db: Session = Depends(get_db),
    sender=Depends(get_device_or_user),
):
    event = db.get(Event, event_uuid)
    if event is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Событие не найдено")
    if isinstance(sender, Device) and event.device_id != sender.id:
        # устройство может загружать клипы только своих событий
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Событие принадлежит другому устройству")
    device = db.get(Device, event.device_id) if event.device_id else None
    serial = device.serial if device else "unknown"
    key = storage.clip_key(serial, str(event_uuid), event.ts.strftime("%Y-%m"))
    url = storage.presigned_clip_upload(key)
    event.clip_key = key
    db.commit()
    return ClipUploadOut(upload_url=url, clip_key=key, expires_in=storage.PRESIGNED_TTL_S)
