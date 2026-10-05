"""Профиль водителя (BE-9), микрообучения (BE-13) и ручки PWA (APP-2…APP-6): /drivers/me, SOS."""

import uuid as uuid_mod
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session, joinedload

from app import scoring, stats, storage, ws
from app.db import get_db
from app.models import (
    AuditLog,
    Break,
    Checklist,
    Device,
    Driver,
    DriverTraining,
    Event,
    Heartbeat,
    Setting,
    Training,
    Trip,
)
from app.routers.directories import ONLINE_WINDOW
from app.routers.events import _trip_at, event_out, ws_manager
from app.schemas import CameraEventIn, CameraHeartbeatIn, SosIn, TrainingAssignIn
from app.security import get_current_user, phone_for, require_roles

router = APIRouter(prefix="/drivers", tags=["профиль водителя"])
trainings_router = APIRouter(prefix="/trainings", tags=["обучение"])
STAFF_ROLES = ("admin", "coordinator")
DEFAULT_RETENTION = {"events_months": 12, "clips_days": 90, "photos_days": 180, "audit_years": 3}


def _masked(out, user):
    """SEC-5: viewer не видит телефоны водителей и в ленте событий профиля."""
    out.driver_phone = phone_for(user, out.driver_phone)
    return out


def _own_driver(db: Session, user) -> Driver:
    driver = db.scalar(select(Driver).where(Driver.user_id == user.id))
    if driver is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Учётка не привязана к водителю")
    return driver


def _check_driver_write(user, driver: Driver) -> None:
    """Действия от имени водителя: сотрудники — за любого, водитель — только за себя."""
    if user.role in STAFF_ROLES:
        return
    if user.role == "driver" and driver.user_id == user.id:
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Доступно только собственному водителю")


def _active_trip(db: Session, driver_id: int, now: datetime) -> dict | None:
    trip = db.scalar(select(Trip).where(Trip.driver_id == driver_id, Trip.status == "active"))
    if trip is None:
        return None
    open_break = db.scalar(
        select(Break)
        .where(Break.trip_id == trip.id, Break.ended_at.is_(None))
        .order_by(Break.started_at.desc())
    )
    last_break_end = db.scalar(
        select(func.max(Break.ended_at)).where(
            Break.trip_id == trip.id, Break.ended_at.is_not(None)
        )
    )
    return {
        "id": trip.id,
        "vehicle_id": trip.vehicle_id,
        "started_at": trip.started_at,
        "distance_km": trip.distance_km,
        "break": (
            {"id": open_break.id, "reason": open_break.reason, "started_at": open_break.started_at}
            if open_break
            else None
        ),
        "last_break_end": last_break_end,
    }


@router.get("/me")
def my_profile(db: Session = Depends(get_db), user=Depends(get_current_user)):
    """Профиль текущего водителя для PWA — без знания driver_id на клиенте."""
    return driver_profile(_own_driver(db, user).id, db, user)


WEB_SERIAL = "WEB-{driver_id:04d}"
CAMERA_BATCH_MAX = 20


def _web_device(db: Session, driver: Driver, now: datetime) -> Device | None:
    """Виртуальное устройство «телефон в кабине»: то, что закреплено за машиной водителя,
    иначе создаётся WEB-<id>. Без машины событие всё равно принимается (device=None)."""
    if driver.vehicle is None:
        return None
    device = db.scalar(
        select(Device).where(Device.vehicle_id == driver.vehicle.id).order_by(Device.id)
    )
    if device is None:
        # Первый heartbeat и первый батч событий приходят одновременно: вставка идемпотентна
        # по serial (unique), проигравший гонку просто перечитывает устройство
        db.execute(
            pg_insert(Device)
            .values(
                serial=WEB_SERIAL.format(driver_id=driver.id),
                secret_hash="-",  # вход только под токеном водителя, device-токена у него нет
                vehicle_id=driver.vehicle.id,
                fw_version="web",
                model_version="browser",
                status="active",
            )
            .on_conflict_do_nothing(index_elements=["serial"])
        )
        device = db.scalar(
            select(Device).where(Device.vehicle_id == driver.vehicle.id).order_by(Device.id)
        )
        if device is None:  # serial занят другой машиной — событие примем без устройства
            return None
    device.last_seen = now
    return device


@router.post("/me/camera-events")
def my_camera_events(
    batch: list[CameraEventIn], db: Session = Depends(get_db), user=Depends(get_current_user)
):
    """События DMS из браузера телефона (PWA «Камера»): идемпотентно по UUID, как с устройства.
    Водитель говорит только за себя: driver_id — из токена."""
    if len(batch) > CAMERA_BATCH_MAX:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, "Не более 20 событий за раз")
    driver = _own_driver(db, user)
    now = datetime.now(UTC)
    device = _web_device(db, driver, now)
    rows = []
    for item in batch:
        has_gps = item.lat is not None and item.lon is not None
        rows.append(
            {
                "uuid": item.uuid,
                "trip_id": _trip_at(db, driver.id, item.ts),
                "device_id": device.id if device else None,
                "driver_id": driver.id,
                "type": item.type,
                "severity": item.severity,
                "confidence": item.confidence,
                "ts": min(item.ts, now),
                "lat": item.lat if has_gps else None,
                "lon": item.lon if has_gps else None,
                "gps_valid": bool(has_gps and item.gps_valid),
                "speed_kmh": item.speed_kmh,
                "value": item.value,
                "context": {"source": "pwa_camera", "note": item.note},
                "status": "new",
                "is_demo": False,
                "created_at": now,
            }
        )
    inserted: list = []
    if rows:
        stmt = (
            pg_insert(Event)
            .values(rows)
            .on_conflict_do_nothing(index_elements=["uuid"])
            .returning(Event.uuid)
        )
        inserted = [r[0] for r in db.execute(stmt).fetchall()]
    db.commit()
    last = next((r for r in reversed(rows) if r["lat"] is not None), None)
    if last and driver.vehicle is not None:
        ws.set_live_position(driver.vehicle.id, last["lat"], last["lon"], last["speed_kmh"])
    if inserted:
        fresh = db.scalars(
            select(Event)
            .where(Event.uuid.in_(inserted))
            .options(joinedload(Event.driver).joinedload(Driver.vehicle))
        ).all()
        for e in fresh:
            ws_manager.broadcast_threadsafe(
                {"type": "event", "event": event_out(e).model_dump(mode="json")}
            )
    return {"accepted": len(inserted), "duplicates": len(rows) - len(inserted)}


@router.post("/me/camera-heartbeat")
def my_camera_heartbeat(
    body: CameraHeartbeatIn, db: Session = Depends(get_db), user=Depends(get_current_user)
):
    """Телефон в кабине на связи: устройство онлайн, позиция — на Live-карте."""
    driver = _own_driver(db, user)
    now = datetime.now(UTC)
    device = _web_device(db, driver, now)
    if device is not None:
        # Строка телеметрии — не чаще раза в 10 минут (аптайм в KPI), сам heartbeat — каждые 15 с
        last_ts = db.scalar(select(func.max(Heartbeat.ts)).where(Heartbeat.device_id == device.id))
        if last_ts is None or now - last_ts >= timedelta(minutes=10):
            db.add(
                Heartbeat(
                    device_id=device.id,
                    ts=now,
                    fps=body.fps,
                    gps_fix=bool(body.lat is not None and body.gps_valid),
                    net="web",
                )
            )
    db.commit()
    if driver.vehicle is not None and body.lat is not None and body.lon is not None:
        ws.set_live_position(driver.vehicle.id, body.lat, body.lon, body.speed_kmh)
    return {
        "ok": True,
        "device": device.serial if device else None,
        "vehicle": driver.vehicle.plate if driver.vehicle else None,
    }


def _check_profile_access(user, driver: Driver) -> None:
    """Сотрудники видят всех, водитель — только себя (SEC-1, ТЗ 3.2)."""
    if user.role == "driver" and driver.user_id != user.id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Доступен только собственный профиль")


@router.get("/{driver_id}/profile")
def driver_profile(driver_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)):
    driver = db.get(Driver, driver_id)
    if driver is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Водитель не найден")
    _check_profile_access(user, driver)
    now = datetime.now(UTC)
    weights, modifiers = stats.load_scoring(db)
    streak = stats.streaks_by_driver(db, now, driver_id=driver_id).get(driver_id, 0)

    # Одним запросом берём события водителя за 8 недель и раскладываем по окнам
    events56 = db.scalars(
        select(Event).where(
            Event.driver_id == driver_id,
            Event.ts > now - timedelta(days=56),
            Event.status.in_(scoring.SCORED_STATUSES),
        )
    ).all()
    scored56 = [
        (e.ts, scoring.ScoredEvent(e.type, e.ts, e.speed_kmh, e.value, e.status, e.severity))
        for e in events56
    ]

    def window_score(weeks_ago: int) -> tuple[int, int]:
        since = now - timedelta(days=(weeks_ago + 1) * 7)
        until = now - timedelta(days=weeks_ago * 7)
        evs = [se for ts, se in scored56 if since < ts <= until]
        return scoring.score(evs, 7, streak, weights, modifiers), len(evs)

    week_value, week_events = window_score(0)
    week = stats.DriverScore(score=week_value, events=week_events, zone=scoring.zone(week_value))
    score_by_week = [{"weeks_ago": w, "score": window_score(w)[0]} for w in range(7, -1, -1)]

    breakdown = db.execute(
        select(Event.type, func.count())
        .where(
            Event.driver_id == driver_id,
            Event.ts > now - timedelta(days=30),
            Event.status.in_(scoring.SCORED_STATUSES),
        )
        .group_by(Event.type)
        .order_by(func.count().desc())
    ).all()

    recent_events = db.scalars(
        select(Event)
        .where(Event.driver_id == driver_id)
        .options(joinedload(Event.driver).joinedload(Driver.vehicle))
        .order_by(Event.ts.desc())
        .limit(10)
    ).all()

    trips = db.scalars(
        select(Trip).where(Trip.driver_id == driver_id).order_by(Trip.started_at.desc()).limit(10)
    ).all()

    trainings = db.scalars(
        select(DriverTraining)
        .where(DriverTraining.driver_id == driver_id)
        .options(joinedload(DriverTraining.training))
        .order_by(DriverTraining.assigned_at.desc())
    ).all()

    # Для PWA (APP-2/APP-3/SEC-5): устройство в кабине, активный рейс, последний чек-лист,
    # сроки хранения данных о водителе
    device = (
        db.scalar(select(Device).where(Device.vehicle_id == driver.vehicle.id))
        if driver.vehicle
        else None
    )
    last_checklist = db.scalar(
        select(Checklist)
        .where(Checklist.driver_id == driver_id)
        .order_by(Checklist.created_at.desc())
        .limit(1)
    )
    retention_row = db.get(Setting, "retention")

    return {
        "driver": {
            "id": driver.id,
            "name": driver.name,
            "photo_url": storage.presigned_photo_download(driver.photo_key)
            if driver.photo_key
            else None,
            "phone": phone_for(user, driver.phone),
            "depot": driver.depot.name if driver.depot else None,
            "depot_id": driver.depot_id,
            "vehicle": {
                "id": driver.vehicle.id,
                "plate": driver.vehicle.plate,
                "model": driver.vehicle.model,
            }
            if driver.vehicle
            else None,
        },
        "device": (
            {
                "id": device.id,
                "serial": device.serial,
                "status": device.status,
                "online": bool(device.last_seen and now - device.last_seen <= ONLINE_WINDOW),
                "last_seen": device.last_seen,
            }
            if device
            else None
        ),
        "active_trip": _active_trip(db, driver_id, now),
        "last_checklist": (
            {
                "id": last_checklist.id,
                "created_at": last_checklist.created_at,
                "verdict": last_checklist.verdict,
                "status": last_checklist.status,
            }
            if last_checklist
            else None
        ),
        "retention": {**DEFAULT_RETENTION, **(retention_row.value if retention_row else {})},
        "score": {
            "value": week.score,
            "zone": week.zone,
            "streak": streak,
            # первая неделя без событий — Score ещё «не заработан», PWA показывает «Первая неделя»
            "is_new": (
                driver.created_at is not None
                and driver.created_at > now - timedelta(days=7)
                and week_events == 0
            ),
        },
        "score_by_week": score_by_week,
        "breakdown_30d": [{"type": t, "count": c} for t, c in breakdown],
        "recent_events": [_masked(event_out(e), user) for e in recent_events],
        "trips": [
            {
                "id": t.id,
                "started_at": t.started_at,
                "ended_at": t.ended_at,
                "distance_km": t.distance_km,
                "status": t.status,
            }
            for t in trips
        ],
        "trainings": [
            {
                "id": dt.id,
                "training_id": dt.training_id,
                "title": dt.training.title,
                "duration_s": dt.training.duration_s,
                "status": dt.status,
                "assigned_at": dt.assigned_at,
            }
            for dt in trainings
        ],
    }


@router.post("/{driver_id}/sos", status_code=201)
def driver_sos(
    driver_id: int, body: SosIn, db: Session = Depends(get_db), user=Depends(get_current_user)
):
    """SOS из PWA (APP-5, BOT-2): критическое событие «sos» с причиной и координатами."""
    driver = db.get(Driver, driver_id)
    if driver is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Водитель не найден")
    _check_driver_write(user, driver)
    now = datetime.now(UTC)
    trip = db.scalar(select(Trip).where(Trip.driver_id == driver_id, Trip.status == "active"))
    device = (
        db.scalar(select(Device).where(Device.vehicle_id == driver.vehicle.id))
        if driver.vehicle
        else None
    )
    has_gps = body.lat is not None and body.lon is not None
    event = Event(
        uuid=uuid_mod.uuid4(),
        trip_id=trip.id if trip else None,
        device_id=device.id if device else None,
        driver_id=driver_id,
        type="sos",
        severity="critical",
        confidence=1.0,
        ts=now,
        lat=body.lat if has_gps else None,
        lon=body.lon if has_gps else None,
        gps_valid=bool(has_gps and body.gps_valid),
        context={"reason": body.reason, "comment": body.comment, "source": "pwa"},
        status="new",
        is_demo=False,
        created_at=now,
    )
    db.add(event)
    db.commit()
    db.refresh(event)
    out = event_out(event)
    ws_manager.broadcast_threadsafe({"type": "event", "event": out.model_dump(mode="json")})
    return out


@router.post("/{driver_id}/trainings/{item_id}/complete")
def complete_training(
    driver_id: int, item_id: int, db: Session = Depends(get_db), user=Depends(get_current_user)
):
    """Отметка прохождения урока (APP-6): водитель — свои, сотрудники — любые."""
    driver = db.get(Driver, driver_id)
    if driver is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Водитель не найден")
    _check_driver_write(user, driver)
    item = db.get(DriverTraining, item_id)
    if item is None or item.driver_id != driver_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Назначение не найдено")
    item.status = "completed"
    db.commit()
    return {"id": item.id, "status": item.status}


@trainings_router.get("", dependencies=[Depends(get_current_user)])
def list_trainings(db: Session = Depends(get_db)):
    """Каталог 60-секундных уроков (APP-6)."""
    rows = db.scalars(select(Training).order_by(Training.id)).all()
    return [{"id": t.id, "title": t.title, "duration_s": t.duration_s, "url": t.url} for t in rows]


@router.post("/{driver_id}/trainings", status_code=201)
def assign_training(
    driver_id: int,
    body: TrainingAssignIn,
    db: Session = Depends(get_db),
    user=Depends(require_roles("admin", "coordinator")),
):
    driver = db.get(Driver, driver_id)
    if driver is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Водитель не найден")
    if body.training_id is not None:
        training = db.get(Training, body.training_id)
    else:
        training = db.scalar(select(Training).where(Training.title == "Управление усталостью"))
        if training is None:
            training = db.scalar(select(Training).order_by(Training.id))
    if training is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Каталог обучений пуст")
    now = datetime.now(UTC)
    dt = DriverTraining(
        driver_id=driver_id,
        training_id=training.id,
        assigned_by=user.id,
        status="assigned",
        assigned_at=now,
    )
    db.add(dt)
    # Назначение обучения — аудируемое действие (SEC-4)
    db.add(
        AuditLog(
            user_id=user.id,
            action="training_assign",
            entity=f"driver:{driver_id}",
            before=None,
            after={"training_id": training.id, "title": training.title},
            ts=now,
        )
    )
    db.commit()
    return {"id": dt.id, "driver_id": driver_id, "training": training.title, "status": dt.status}
