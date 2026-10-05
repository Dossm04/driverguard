"""Справочники: депо, водители, машины, устройства (BE-2)."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from app import storage
from app.db import get_db
from app.models import AuditLog, Depot, Device, Driver, Heartbeat, Setting, Trip, User, Vehicle
from app.schemas import (
    DepotOut,
    DeviceIn,
    DeviceOut,
    DevicePatch,
    DriverIn,
    DriverOut,
    DriverPatch,
    HeartbeatIn,
    VehicleIn,
    VehicleOut,
    VehiclePatch,
)
from app.security import get_device_or_user, hash_secret, phone_for, require_roles

router = APIRouter(tags=["справочники"])

_staff = Depends(require_roles("admin", "coordinator"))
# Чтение справочников доступно и роли viewer (SEC-1: read-only), запись — нет
_staff_read = Depends(require_roles("admin", "coordinator", "viewer"))
ONLINE_WINDOW = timedelta(minutes=5)  # BE-17: нет heartbeat >5 мин → офлайн


def _commit_or_409(db: Session, message: str) -> None:
    """Дубликат уникального поля — честный 409, а не 500 (правило 8 CLAUDE.md)."""
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, message) from exc


def _flush_or_409(db: Session, message: str) -> None:
    """То же для промежуточного flush: дубль телефона учётки PWA всплывает уже здесь."""
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, message) from exc


def _driver_out(d: Driver) -> DriverOut:
    out = DriverOut.model_validate(d)
    out.depot_name = d.depot.name if d.depot else None
    out.vehicle_plate = d.vehicle.plate if d.vehicle else None
    out.vehicle_id = d.vehicle.id if d.vehicle else None
    out.photo_url = storage.presigned_photo_download(d.photo_key) if d.photo_key else None
    return out


@router.get("/depots", response_model=list[DepotOut], dependencies=[_staff_read])
def list_depots(db: Session = Depends(get_db)):
    return db.scalars(select(Depot).order_by(Depot.id)).all()


@router.get("/drivers", response_model=list[DriverOut])
def list_drivers(db: Session = Depends(get_db), user=_staff_read):
    # депо и машина — одним запросом на список, а не по запросу на водителя (N+1 при 40+)
    stmt = (
        select(Driver)
        .options(selectinload(Driver.depot), selectinload(Driver.vehicle))
        .order_by(Driver.id)
    )
    rows = [_driver_out(d) for d in db.scalars(stmt).all()]
    for row in rows:
        row.phone = phone_for(user, row.phone)
    return rows


@router.post("/drivers", response_model=DriverOut, status_code=201)
def create_driver(body: DriverIn, db: Session = Depends(get_db), user=_staff):
    now = datetime.now(UTC)
    if body.depot_id is not None and db.get(Depot, body.depot_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Депо не найдено")
    account = None
    if body.phone:
        account = User(
            role="driver",
            phone=body.phone,
            pin_hash=hash_secret(body.pin) if body.pin else None,
            name=body.name,
            created_at=now,
        )
        db.add(account)
        _flush_or_409(db, "Водитель с таким телефоном уже существует")
    driver = Driver(
        name=body.name,
        depot_id=body.depot_id,
        phone=body.phone,
        user_id=account.id if account else None,
        created_at=now,
    )
    db.add(driver)
    _commit_or_409(db, "Водитель с таким телефоном уже существует")
    db.refresh(driver)
    return _driver_out(driver)


def _assign_vehicle(db: Session, driver: Driver, vehicle_id: int | None) -> None:
    """Закрепить/открепить машину: у машины один водитель, у водителя одна машина."""
    if driver.vehicle is not None and driver.vehicle.id != vehicle_id:
        driver.vehicle.driver_id = None
        db.flush()
    if not vehicle_id:
        return
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Машина не найдена")
    if vehicle.driver_id not in (None, driver.id):
        raise HTTPException(status.HTTP_409_CONFLICT, "Машина уже закреплена за другим водителем")
    vehicle.driver_id = driver.id


PHOTO_TYPES = {"image/jpeg": "jpg", "image/png": "png", "image/webp": "webp"}
PHOTO_MAX_BYTES = 5 * 1024 * 1024


@router.post("/drivers/{driver_id}/photo", response_model=DriverOut, dependencies=[_staff])
async def upload_driver_photo(
    driver_id: int, file: UploadFile = File(...), db: Session = Depends(get_db)
):
    """Фото водителя (аватар): JPEG/PNG/WebP до 5 МБ → бакет photos, ключ drivers/{id}/avatar.*"""
    driver = db.get(Driver, driver_id)
    if driver is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Водитель не найден")
    ext = PHOTO_TYPES.get((file.content_type or "").lower())
    if ext is None:
        raise HTTPException(status.HTTP_415_UNSUPPORTED_MEDIA_TYPE, "Нужно фото JPEG, PNG или WebP")
    data = await file.read(PHOTO_MAX_BYTES + 1)
    if len(data) > PHOTO_MAX_BYTES:
        raise HTTPException(status.HTTP_413_REQUEST_ENTITY_TOO_LARGE, "Фото больше 5 МБ")
    if not data:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Пустой файл")
    key = f"drivers/{driver.id}/avatar-{int(datetime.now(UTC).timestamp())}.{ext}"
    storage.put_photo(key, data, file.content_type or "image/jpeg")
    driver.photo_key = key
    db.commit()
    db.refresh(driver)
    return _driver_out(driver)


@router.delete("/drivers/{driver_id}/photo", response_model=DriverOut, dependencies=[_staff])
def delete_driver_photo(driver_id: int, db: Session = Depends(get_db)):
    driver = db.get(Driver, driver_id)
    if driver is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Водитель не найден")
    driver.photo_key = None
    db.commit()
    db.refresh(driver)
    return _driver_out(driver)


@router.patch("/drivers/{driver_id}", response_model=DriverOut, dependencies=[_staff])
def patch_driver(driver_id: int, body: DriverPatch, db: Session = Depends(get_db)):
    driver = db.get(Driver, driver_id)
    if driver is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Водитель не найден")
    payload = body.model_dump(exclude_unset=True)
    pin = payload.pop("pin", None)
    if payload.get("depot_id") is not None and db.get(Depot, payload["depot_id"]) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Депо не найдено")
    if "vehicle_id" in payload:
        _assign_vehicle(db, driver, payload.pop("vehicle_id"))
    for field, value in payload.items():
        setattr(driver, field, value)
    # Учётка PWA обязана следовать за справочником: телефон для входа и сброс PIN
    account = db.get(User, driver.user_id) if driver.user_id else None
    if account is None and driver.phone and ("phone" in payload or pin):
        # Водителю без учётки задали телефон/PIN — создаём вход в PWA, а не молчим (APP-1)
        account = User(
            role="driver",
            phone=driver.phone,
            pin_hash=hash_secret(pin) if pin else None,
            name=driver.name,
            created_at=datetime.now(UTC),
        )
        db.add(account)
        _flush_or_409(db, "Телефон уже используется другим водителем")
        driver.user_id = account.id
    elif account is not None:
        if "phone" in payload:
            account.phone = payload["phone"]
        if "name" in payload:
            account.name = payload["name"]
        if pin:
            account.pin_hash = hash_secret(pin)
    _commit_or_409(db, "Телефон уже используется другим водителем")
    db.refresh(driver)
    return _driver_out(driver)


@router.get("/vehicles", response_model=list[VehicleOut], dependencies=[_staff_read])
def list_vehicles(db: Session = Depends(get_db)):
    return db.scalars(select(Vehicle).order_by(Vehicle.id)).all()


@router.post("/vehicles", response_model=VehicleOut, status_code=201, dependencies=[_staff])
def create_vehicle(body: VehicleIn, db: Session = Depends(get_db)):
    if body.driver_id is not None and db.get(Driver, body.driver_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Водитель не найден")
    vehicle = Vehicle(**body.model_dump())
    db.add(vehicle)
    _commit_or_409(db, "Номер занят или водитель уже закреплён за другой машиной")
    db.refresh(vehicle)
    return vehicle


@router.patch("/vehicles/{vehicle_id}", response_model=VehicleOut, dependencies=[_staff])
def patch_vehicle(vehicle_id: int, body: VehiclePatch, db: Session = Depends(get_db)):
    vehicle = db.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Машина не найдена")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(vehicle, field, value)
    _commit_or_409(db, "Номер занят или водитель уже закреплён за другой машиной")
    db.refresh(vehicle)
    return vehicle


def device_out(d: Device, now: datetime | None = None) -> DeviceOut:
    now = now or datetime.now(UTC)
    out = DeviceOut.model_validate(d)
    out.online = bool(d.last_seen and now - d.last_seen <= ONLINE_WINDOW)
    out.vehicle_plate = d.vehicle.plate if d.vehicle else None
    return out


@router.get("/devices", response_model=list[DeviceOut], dependencies=[_staff_read])
def list_devices(db: Session = Depends(get_db)):
    now = datetime.now(UTC)
    stmt = select(Device).options(selectinload(Device.vehicle)).order_by(Device.id)
    return [device_out(d, now) for d in db.scalars(stmt).all()]


@router.post("/devices", response_model=DeviceOut, status_code=201, dependencies=[_staff])
def create_device(body: DeviceIn, db: Session = Depends(get_db)):
    device = Device(
        serial=body.serial,
        secret_hash=hash_secret(body.secret),
        vehicle_id=body.vehicle_id,
        fw_version=body.fw_version,
        model_version=body.model_version,
    )
    db.add(device)
    _commit_or_409(db, "Устройство с таким serial уже существует")
    db.refresh(device)
    return device_out(device)


@router.patch("/devices/{device_id}", response_model=DeviceOut, dependencies=[_staff])
def patch_device(device_id: int, body: DevicePatch, db: Session = Depends(get_db)):
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Устройство не найдено")
    for field, value in body.model_dump(exclude_unset=True).items():
        setattr(device, field, value)
    _commit_or_409(db, "Устройство с таким serial уже существует")
    db.refresh(device)
    return device_out(device)


@router.post("/devices/{device_id}/reboot", response_model=DeviceOut)
def reboot_device(device_id: int, db: Session = Depends(get_db), user=_staff):
    """«Перезагрузить» (WEB-9): команда доставляется устройству при следующем /config."""
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Устройство не найдено")
    now = datetime.now(UTC)
    before = device.status
    device.status = "reboot_requested"
    db.add(
        AuditLog(
            user_id=user.id,
            action="device_reboot",
            entity=f"device:{device.serial}",
            before={"status": before},
            after={"status": device.status},
            ts=now,
        )
    )
    db.commit()
    db.refresh(device)
    return device_out(device, now)


@router.post("/devices/{device_id}/heartbeat")
def device_heartbeat(
    device_id: int,
    body: HeartbeatIn | None = None,
    db: Session = Depends(get_db),
    sender=Depends(get_device_or_user),
):
    """Телеметрия устройства (BE-17, DEV-23): раз в 10 минут + обновление last_seen.

    Heartbeat из офлайн-очереди приходит со своим ts: аптайм считается по нему, а км
    прибавляются к рейсу, который шёл в тот момент; last_seen — серверное «сейчас»
    (сам запрос доказывает, что устройство на связи).
    """
    if isinstance(sender, Device) and sender.id != device_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Чужое устройство")
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Устройство не найдено")
    now = datetime.now(UTC)
    body = body or HeartbeatIn()
    ts = body.ts if body.ts and body.ts <= now else now
    device.last_seen = now
    if body.fw_version:
        device.fw_version = body.fw_version
    if body.model_version:
        device.model_version = (
            body.model_version
        )  # ML-4: версия модели, с которой работает устройство
    # Пробег: километры с прошлого heartbeat (GPS/OBD) → рейс этой машины на момент ts
    # (APP-2 «км» в PWA, BE-14 отчёты)
    if body.trip_km_delta and device.vehicle_id:
        trip = db.scalar(
            select(Trip)
            .where(
                Trip.vehicle_id == device.vehicle_id,
                Trip.started_at <= ts,
                (Trip.ended_at.is_(None)) | (Trip.ended_at >= ts),
            )
            .order_by(Trip.started_at.desc())
        )
        if trip is not None:
            trip.distance_km = round((trip.distance_km or 0.0) + body.trip_km_delta, 2)
    db.add(
        Heartbeat(
            device_id=device_id,
            ts=ts,
            temp_c=body.temp_c,
            fps=body.fps,
            disk_free=body.disk_free,
            gps_fix=body.gps_fix,
            net=body.net,
        )
    )
    db.commit()
    return {"status": "ok", "server_time": now}


@router.get("/devices/{device_id}/config")
def device_config(
    device_id: int,
    db: Session = Depends(get_db),
    sender=Depends(get_device_or_user),
):
    """Конфигурация для устройства (DEV-24, SYS-4): пороги и версия настроек."""
    if isinstance(sender, Device) and sender.id != device_id:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Чужое устройство")
    device = db.get(Device, device_id)
    if device is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Устройство не найдено")
    thresholds = db.get(Setting, "thresholds")
    scoring_cfg = db.get(Setting, "scoring")
    reboot = device.status == "reboot_requested"
    if reboot and isinstance(sender, Device):  # команда доставлена — сбрасываем
        device.status = "active"
        db.commit()
    return {
        "thresholds": thresholds.value if thresholds else {},
        "thresholds_version": thresholds.version if thresholds else 0,
        "scoring_version": scoring_cfg.version if scoring_cfg else 0,
        "reboot": reboot,
    }
