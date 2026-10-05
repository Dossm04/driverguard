"""Рейсы: старт/стоп/перерывы (BE-3).

Доступ (SEC-1): сотрудники — любые рейсы; водитель — только собственные.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Break, Device, Driver, Trip, User, Vehicle
from app.schemas import BreakIn, TripOut, TripStartIn
from app.security import get_current_user

router = APIRouter(prefix="/trips", tags=["рейсы"])

STAFF_ROLES = ("admin", "coordinator")


def _own_driver_id(db: Session, user: User) -> int | None:
    driver = db.scalar(select(Driver).where(Driver.user_id == user.id))
    return driver.id if driver else None


def _check_driver_access(db: Session, user: User, driver_id: int) -> None:
    if user.role in STAFF_ROLES:
        return
    if user.role == "driver" and _own_driver_id(db, user) == driver_id:
        return
    raise HTTPException(status.HTTP_403_FORBIDDEN, "Можно управлять только своим рейсом")


def _get_trip_checked(db: Session, user: User, trip_id: int) -> Trip:
    trip = db.get(Trip, trip_id)
    if trip is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Рейс не найден")
    _check_driver_access(db, user, trip.driver_id)
    return trip


@router.post("/start", response_model=TripOut, status_code=201)
def start_trip(
    body: TripStartIn, db: Session = Depends(get_db), user: User = Depends(get_current_user)
):
    _check_driver_access(db, user, body.driver_id)
    if db.get(Vehicle, body.vehicle_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Машина не найдена")
    if user.role == "driver":
        # Водитель стартует рейс только на своей машине — чужие километры и устройство
        # не должны попадать в его рейс (и наоборот)
        own = db.scalar(select(Vehicle.id).where(Vehicle.driver_id == body.driver_id))
        if own is None or own != body.vehicle_id:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Рейс можно начать только на своей машине"
            )
        if body.device_id is not None:
            dev_vehicle = db.scalar(select(Device.vehicle_id).where(Device.id == body.device_id))
            if dev_vehicle != body.vehicle_id:
                raise HTTPException(
                    status.HTTP_403_FORBIDDEN, "Устройство закреплено за другой машиной"
                )
    if body.device_id is not None and db.get(Device, body.device_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Устройство не найдено")
    active = db.scalar(
        select(Trip).where(Trip.driver_id == body.driver_id, Trip.status == "active")
    )
    if active is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "У водителя уже есть активный рейс")
    trip = Trip(
        driver_id=body.driver_id,
        vehicle_id=body.vehicle_id,
        device_id=body.device_id,
        started_at=datetime.now(UTC),
        status="active",
    )
    db.add(trip)
    db.commit()
    db.refresh(trip)
    return trip


@router.post("/{trip_id}/stop", response_model=TripOut)
def stop_trip(trip_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    trip = _get_trip_checked(db, user, trip_id)
    if trip.status != "active":
        raise HTTPException(status.HTTP_409_CONFLICT, "Рейс уже завершён")
    trip.status = "finished"
    trip.ended_at = datetime.now(UTC)
    db.commit()
    db.refresh(trip)
    return trip


@router.post("/{trip_id}/breaks", status_code=201)
def start_break(
    trip_id: int,
    body: BreakIn,
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    trip = _get_trip_checked(db, user, trip_id)
    if trip.status != "active":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Активный рейс не найден")
    brk = Break(trip_id=trip_id, reason=body.reason, started_at=datetime.now(UTC))
    db.add(brk)
    db.commit()
    return {"id": brk.id, "reason": brk.reason, "started_at": brk.started_at}


@router.post("/{trip_id}/breaks/end")
def end_break(trip_id: int, db: Session = Depends(get_db), user: User = Depends(get_current_user)):
    _get_trip_checked(db, user, trip_id)
    brk = db.scalar(
        select(Break)
        .where(Break.trip_id == trip_id, Break.ended_at.is_(None))
        .order_by(Break.started_at.desc())
    )
    if brk is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Открытый перерыв не найден")
    brk.ended_at = datetime.now(UTC)
    db.commit()
    return {"id": brk.id, "ended_at": brk.ended_at}


@router.get("", response_model=list[TripOut])
def list_trips(
    driver_id: int | None = None,
    trip_status: str | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    db: Session = Depends(get_db),
    user: User = Depends(get_current_user),
):
    if user.role == "driver":
        # водитель видит только свои рейсы
        driver_id = _own_driver_id(db, user)
        if driver_id is None:
            return []
    q = select(Trip).order_by(Trip.started_at.desc()).limit(min(limit, 500))
    if driver_id is not None:
        q = q.where(Trip.driver_id == driver_id)
    if trip_status is not None:
        q = q.where(Trip.status == trip_status)
    return db.scalars(q).all()
