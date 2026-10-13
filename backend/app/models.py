"""ORM-модели по модели данных ТЗ 6.2.1.

Enum-поля хранятся строками (см. docs/decisions.md): допустимые значения
валидируются на уровне Pydantic-схем.
"""

import uuid as uuid_mod
from datetime import datetime

from sqlalchemy import Boolean, DateTime, Float, ForeignKey, Index, Integer, String, Text, Uuid
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db import Base

# Справочники допустимых значений (используются схемами и seed'ом)
ROLES = ("admin", "coordinator", "driver", "viewer")
EVENT_TYPES = (
    "microsleep",
    "distraction",
    "phone",
    "smoking",
    "seatbelt",
    "speeding",
    "fatigue",
    "head_nod",
    "camera_sabotage",
    "yawn",
    "camera_unavailable",
    "rest_started",
    "rest_ended",
    "harsh_braking",
    "sos",
)
SEVERITIES = ("critical", "warning", "info")
EVENT_STATUSES = ("new", "confirmed", "false_positive")


class User(Base):
    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    role: Mapped[str] = mapped_column(String(20))
    email: Mapped[str | None] = mapped_column(String(255), unique=True)
    phone: Mapped[str | None] = mapped_column(String(32), unique=True)
    password_hash: Mapped[str | None] = mapped_column(String(255))
    pin_hash: Mapped[str | None] = mapped_column(String(255))
    name: Mapped[str] = mapped_column(String(120))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    # Последний авторизованный запрос (обновляется не чаще раза в минуту) — «кто онлайн»
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Depot(Base):
    __tablename__ = "depots"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(120), unique=True)


class Driver(Base):
    __tablename__ = "drivers"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    name: Mapped[str] = mapped_column(String(120))
    depot_id: Mapped[int | None] = mapped_column(ForeignKey("depots.id"))
    phone: Mapped[str | None] = mapped_column(String(32))
    consent_signed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    photo_key: Mapped[str | None] = mapped_column(String(255))  # аватар в бакете photos

    depot: Mapped[Depot | None] = relationship()
    vehicle: Mapped["Vehicle | None"] = relationship(back_populates="driver")


class Vehicle(Base):
    __tablename__ = "vehicles"

    id: Mapped[int] = mapped_column(primary_key=True)
    plate: Mapped[str] = mapped_column(String(20), unique=True)
    model: Mapped[str] = mapped_column(String(120))
    depot_id: Mapped[int | None] = mapped_column(ForeignKey("depots.id"))
    # Закрепление машины за водителем (как в эталонном прототипе)
    driver_id: Mapped[int | None] = mapped_column(ForeignKey("drivers.id"), unique=True)
    profile: Mapped[str] = mapped_column(String(20), default="trassa")

    driver: Mapped[Driver | None] = relationship(back_populates="vehicle")


class Device(Base):
    __tablename__ = "devices"

    id: Mapped[int] = mapped_column(primary_key=True)
    serial: Mapped[str] = mapped_column(String(40), unique=True)
    secret_hash: Mapped[str] = mapped_column(String(255))
    vehicle_id: Mapped[int | None] = mapped_column(ForeignKey("vehicles.id"))
    fw_version: Mapped[str | None] = mapped_column(String(20))
    model_version: Mapped[str | None] = mapped_column(String(20))
    last_seen: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(20), default="active")

    vehicle: Mapped[Vehicle | None] = relationship()


class Trip(Base):
    __tablename__ = "trips"

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id"))
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"))
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    distance_km: Mapped[float] = mapped_column(Float, default=0)
    status: Mapped[str] = mapped_column(String(20), default="active")

    __table_args__ = (Index("ix_trips_driver_started", "driver_id", "started_at"),)


class Break(Base):
    __tablename__ = "breaks"

    id: Mapped[int] = mapped_column(primary_key=True)
    trip_id: Mapped[int] = mapped_column(ForeignKey("trips.id"))
    reason: Mapped[str] = mapped_column(String(40))
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Event(Base):
    __tablename__ = "events"

    uuid: Mapped[uuid_mod.UUID] = mapped_column(Uuid, primary_key=True)
    trip_id: Mapped[int | None] = mapped_column(ForeignKey("trips.id"))
    device_id: Mapped[int | None] = mapped_column(ForeignKey("devices.id"))
    driver_id: Mapped[int | None] = mapped_column(ForeignKey("drivers.id"))
    type: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str] = mapped_column(String(10))
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    lat: Mapped[float | None] = mapped_column(Float)
    lon: Mapped[float | None] = mapped_column(Float)
    gps_valid: Mapped[bool] = mapped_column(Boolean, default=True)
    speed_kmh: Mapped[float | None] = mapped_column(Float)
    # Числовая характеристика: секунды закрытия глаз, +км/ч превышения, g торможения
    value: Mapped[float | None] = mapped_column(Float)
    context: Mapped[dict | None] = mapped_column(JSONB)
    measurements: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    clip_key: Mapped[str | None] = mapped_column(String(255))
    status: Mapped[str] = mapped_column(String(20), default="new")
    reviewed_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    driver: Mapped[Driver | None] = relationship()
    device: Mapped[Device | None] = relationship()

    __table_args__ = (
        Index("ix_events_driver_ts", "driver_id", "ts"),
        Index("ix_events_ts", "ts"),
        Index("ix_events_status", "status"),
    )


class Checklist(Base):
    __tablename__ = "checklists"

    id: Mapped[int] = mapped_column(primary_key=True)
    # Mobile outbox retries the same UUID after a lost HTTP response.
    client_uuid: Mapped[str | None] = mapped_column(String(36))
    trip_id: Mapped[int | None] = mapped_column(ForeignKey("trips.id"))
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id"))
    vehicle_id: Mapped[int] = mapped_column(ForeignKey("vehicles.id"))
    photos: Mapped[list | None] = mapped_column(JSONB)
    ai_verdict: Mapped[dict | None] = mapped_column(JSONB)
    # v2 (ШАГ 10): анкета 42 пунктов, итоговый вердикт, отметка координатора
    answers: Mapped[dict | None] = mapped_column(JSONB)
    verdict: Mapped[str | None] = mapped_column(String(20), index=True)
    note: Mapped[str | None] = mapped_column(Text)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    status: Mapped[str] = mapped_column(String(30), default="pending")
    approved_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    __table_args__ = (
        Index("uq_checklists_driver_client_uuid", "driver_id", "client_uuid", unique=True),
    )


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(60), primary_key=True)
    value: Mapped[dict] = mapped_column(JSONB)
    version: Mapped[int] = mapped_column(Integer, default=1)
    updated_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Training(Base):
    __tablename__ = "trainings"

    id: Mapped[int] = mapped_column(primary_key=True)
    title: Mapped[str] = mapped_column(String(200))
    duration_s: Mapped[int] = mapped_column(Integer, default=60)
    url: Mapped[str | None] = mapped_column(String(255))


class DriverTraining(Base):
    __tablename__ = "driver_trainings"

    id: Mapped[int] = mapped_column(primary_key=True)
    driver_id: Mapped[int] = mapped_column(ForeignKey("drivers.id"))
    training_id: Mapped[int] = mapped_column(ForeignKey("trainings.id"))
    assigned_by: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    status: Mapped[str] = mapped_column(String(20), default="assigned")
    assigned_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))

    training: Mapped[Training] = relationship()


class RetrainQueueItem(Base):
    __tablename__ = "retrain_queue"

    id: Mapped[int] = mapped_column(primary_key=True)
    event_uuid: Mapped[uuid_mod.UUID] = mapped_column(ForeignKey("events.uuid"))
    frame_key: Mapped[str | None] = mapped_column(String(255))
    label_hint: Mapped[str | None] = mapped_column(String(120))
    exported_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int | None] = mapped_column(ForeignKey("users.id"))
    action: Mapped[str] = mapped_column(String(60))
    entity: Mapped[str] = mapped_column(Text)
    before: Mapped[dict | None] = mapped_column(JSONB)
    after: Mapped[dict | None] = mapped_column(JSONB)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))


class Heartbeat(Base):
    __tablename__ = "heartbeats"

    id: Mapped[int] = mapped_column(primary_key=True)
    device_id: Mapped[int] = mapped_column(ForeignKey("devices.id"))
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True))
    temp_c: Mapped[float | None] = mapped_column(Float)
    fps: Mapped[float | None] = mapped_column(Float)
    disk_free: Mapped[float | None] = mapped_column(Float)
    gps_fix: Mapped[bool | None] = mapped_column(Boolean)
    net: Mapped[str | None] = mapped_column(String(20))

    __table_args__ = (Index("ix_heartbeats_device_ts", "device_id", "ts"),)
