"""Учётки для менторов/жюри: каждому — координатор панели + водитель PWA со своей машиной.

Ментор входит в панель как координатор (видит всё, кроме управления пользователями) и в PWA
как водитель: проходит чек-лист, смотрит Score, включает камеру телефона (страница «Камера»).
Виртуальное устройство WEB-M<n> закрепляется за машиной ментора, поэтому события с телефона
попадают на Live-карту и в «События» как с настоящего блока.

  cd backend
  .venv/bin/python scripts/mentors.py --count 5              # Ментор 1…5
  .venv/bin/python scripts/mentors.py --names "Асель,Данияр" # по именам
  .venv/bin/python scripts/mentors.py --count 5 --reset      # новые пароли/PIN тем же учёткам
  .venv/bin/python scripts/mentors.py --remove               # удалить все учётки менторов
  .venv/bin/python scripts/mentors.py --count 5 --out mentors.csv   # + файл для раздачи

Пароли и PIN генерируются случайно и печатаются ОДИН раз (в базе — только bcrypt-хэши).
Файл --out не коммитить: backend/mentors*.csv в .gitignore. Подключение к базе — DATABASE_URL
(как у backend; на ноутбуке запускать через `make mentors N=5`, который читает infra/.env).
"""

import argparse
import csv
import secrets
import string
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select, update  # noqa: E402
from sqlalchemy.orm import Session  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import (  # noqa: E402
    AuditLog,
    Break,
    Checklist,
    Depot,
    Device,
    Driver,
    DriverTraining,
    Event,
    Heartbeat,
    RetrainQueueItem,
    Setting,
    Trip,
    User,
    Vehicle,
)
from app.security import hash_secret  # noqa: E402

EMAIL_DOMAIN = "demo.driverguard.kz"
ROLE_LABEL = {"coordinator": "координатор", "viewer": "наблюдатель"}
PHONE_PREFIX = "+77770"  # +7 7770 00 NNNN — вымышленный диапазон, не совпадает с seed
PLATE_FMT = "KZ 9{n:03d} MT"
SERIAL_FMT = "WEB-M{n:03d}"
_ALPHABET = string.ascii_letters + string.digits


def mentor_email(n: int) -> str:
    return f"mentor{n}@{EMAIL_DOMAIN}"


def mentor_phone(n: int) -> str:
    return f"{PHONE_PREFIX}00{n:04d}"


def new_password() -> str:
    return "".join(secrets.choice(_ALPHABET) for _ in range(10))


def new_pin() -> str:
    return f"{secrets.randbelow(10_000):04d}"


def _depot_id(db: Session) -> int | None:
    return db.scalar(select(Depot.id).order_by(Depot.id).limit(1))


def upsert_mentor(
    db: Session, n: int, name: str, reset: bool, role: str = "coordinator"
) -> dict | None:
    """Создаёт (или при --reset обновляет секреты) комплект ментора. None — уже есть, без reset."""
    now = datetime.now(UTC)
    email, phone = mentor_email(n), mentor_phone(n)
    coord = db.scalar(select(User).where(User.email == email))
    drv_user = db.scalar(select(User).where(User.phone == phone))
    exists = coord is not None or drv_user is not None
    if exists and not reset:
        return None
    password, pin = new_password(), new_pin()

    if coord is None:
        coord = User(role=role, email=email, name=f"{name} · {ROLE_LABEL[role]}", created_at=now)
        db.add(coord)
    coord.role = role  # жюри — viewer: только чтение, без телефонов и чужих PIN
    coord.password_hash = hash_secret(password)

    if drv_user is None:
        drv_user = User(role="driver", phone=phone, name=name, created_at=now)
        db.add(drv_user)
    drv_user.pin_hash = hash_secret(pin)
    db.flush()

    driver = db.scalar(select(Driver).where(Driver.user_id == drv_user.id))
    if driver is None:
        driver = Driver(
            user_id=drv_user.id,
            name=name,
            depot_id=_depot_id(db),
            phone=phone,
            consent_signed_at=now,
            created_at=now - timedelta(days=1),
        )
        db.add(driver)
        db.flush()

    plate = PLATE_FMT.format(n=n)
    vehicle = db.scalar(select(Vehicle).where(Vehicle.plate == plate))
    if vehicle is None:
        vehicle = Vehicle(
            plate=plate,
            model="Демо-машина ментора",
            depot_id=driver.depot_id,
            driver_id=driver.id,
            profile="city",
        )
        db.add(vehicle)
        db.flush()

    serial = SERIAL_FMT.format(n=n)
    device = db.scalar(select(Device).where(Device.serial == serial))
    if device is None:
        # Секрет устройства не нужен: события с телефона идут под токеном водителя
        db.add(
            Device(
                serial=serial,
                secret_hash=hash_secret(secrets.token_hex(16)),
                vehicle_id=vehicle.id,
                fw_version="web",
                model_version="browser",
                status="active",
            )
        )
    return {
        "mentor": name,
        "panel_email": email,
        "panel_password": password,
        "pwa_phone": phone,
        "pwa_pin": pin,
        "plate": plate,
        "device": serial,
    }


def _purge_driver(db: Session, driver: Driver) -> None:
    """Удаляет данные водителя-ментора в порядке зависимостей (события, рейсы, чек-листы…)."""
    trip_ids = select(Trip.id).where(Trip.driver_id == driver.id)
    event_uuids = select(Event.uuid).where(Event.driver_id == driver.id)
    db.execute(delete(RetrainQueueItem).where(RetrainQueueItem.event_uuid.in_(event_uuids)))
    db.execute(delete(Event).where(Event.driver_id == driver.id))
    db.execute(delete(Checklist).where(Checklist.driver_id == driver.id))
    db.execute(delete(Break).where(Break.trip_id.in_(trip_ids)))
    db.execute(delete(Trip).where(Trip.driver_id == driver.id))
    db.execute(delete(DriverTraining).where(DriverTraining.driver_id == driver.id))
    vehicle = db.scalar(select(Vehicle).where(Vehicle.driver_id == driver.id))
    if vehicle is not None:
        device_ids = select(Device.id).where(Device.vehicle_id == vehicle.id)
        db.execute(delete(Heartbeat).where(Heartbeat.device_id.in_(device_ids)))
        db.execute(delete(Event).where(Event.device_id.in_(device_ids)))
        db.execute(delete(Trip).where(Trip.vehicle_id == vehicle.id))
        db.execute(delete(Device).where(Device.vehicle_id == vehicle.id))
        db.delete(vehicle)
    db.delete(driver)
    db.flush()


def _detach_staff(db: Session, user_id: int) -> None:
    """Снимает ссылки на сотрудника (кто проверил событие/согласовал чек-лист) перед удалением."""
    db.execute(update(Event).where(Event.reviewed_by == user_id).values(reviewed_by=None))
    db.execute(update(Checklist).where(Checklist.approved_by == user_id).values(approved_by=None))
    db.execute(update(Setting).where(Setting.updated_by == user_id).values(updated_by=None))
    db.execute(update(AuditLog).where(AuditLog.user_id == user_id).values(user_id=None))
    db.execute(
        update(DriverTraining).where(DriverTraining.assigned_by == user_id).values(assigned_by=None)
    )


def remove_mentors(db: Session) -> int:
    """Удаляет все комплекты менторов (по домену email / префиксу телефона) с их данными."""
    removed = 0
    for user in db.scalars(select(User).where(User.email.like(f"%@{EMAIL_DOMAIN}"))).all():
        _detach_staff(db, user.id)
        db.delete(user)
        removed += 1
    db.flush()
    for user in db.scalars(select(User).where(User.phone.like(f"{PHONE_PREFIX}%"))).all():
        driver = db.scalar(select(Driver).where(Driver.user_id == user.id))
        if driver is not None:
            _purge_driver(db, driver)
        db.delete(user)
        removed += 1
    db.flush()
    return removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Учётки менторов: координатор + водитель")
    parser.add_argument("--count", type=int, default=0, help="сколько комплектов «Ментор N»")
    parser.add_argument("--names", default="", help="имена через запятую (вместо --count)")
    parser.add_argument("--reset", action="store_true", help="новые пароли/PIN существующим")
    parser.add_argument("--remove", action="store_true", help="удалить все учётки менторов")
    parser.add_argument("--out", help="CSV с доступами (не коммитить)")
    parser.add_argument(
        "--role",
        choices=sorted(ROLE_LABEL),
        default="coordinator",
        help="роль учётки панели: coordinator (review, правки) или viewer (только смотреть — жюри)",
    )
    args = parser.parse_args(argv)

    names = [s.strip() for s in args.names.split(",") if s.strip()]
    if not names and args.count:
        names = [f"Ментор {i}" for i in range(1, args.count + 1)]
    if not names and not args.remove:
        parser.error("укажите --count N, --names или --remove")

    with SessionLocal() as db:
        if args.remove:
            removed = remove_mentors(db)
            db.commit()
            print(f"Удалено учёток менторов: {removed}")
            return 0
        rows: list[dict] = []
        skipped: list[str] = []
        for i, name in enumerate(names, start=1):
            row = upsert_mentor(db, i, name, args.reset, args.role)
            (rows.append(row) if row else skipped.append(name))
        db.commit()

    if skipped:
        print("Уже существуют (пароли не менялись; --reset — выдать новые):", ", ".join(skipped))
    if rows:
        print(f"\nДоступы менторов ({len(rows)}). Пароли показаны один раз:\n")
        head = ("Ментор", "Панель: email", "Пароль", "PWA: телефон", "PIN", "Машина", "Устройство")
        widths = [max(len(h), *(len(str(r[k])) for r in rows)) for h, k in zip(head, rows[0])]
        print("  ".join(h.ljust(w) for h, w in zip(head, widths)))
        for r in rows:
            print("  ".join(str(v).ljust(w) for v, w in zip(r.values(), widths)))
        if args.out:
            with open(args.out, "w", newline="", encoding="utf-8") as f:
                writer = csv.DictWriter(f, fieldnames=list(rows[0]))
                writer.writeheader()
                writer.writerows(rows)
            print(f"\nСохранено в {args.out} (файл не коммитить)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
