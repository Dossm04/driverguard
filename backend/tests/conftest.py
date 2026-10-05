"""Тестовая инфраструктура: отдельная БД driverguard_test на том же Postgres.

Переменная DATABASE_URL подменяется ДО импорта приложения (engine создаётся
при импорте app.db). SQLite не используем сознательно — см. docs/decisions.md.
"""

import atexit
import os
from datetime import UTC, datetime

import psycopg
import pytest

# База на процесс: два параллельных прогона pytest (CI, IDE, агенты) не ломают друг друга
# drop_all/create_all; удаляется при выходе. DG_TEST_DB — фиксированное имя, если нужно.
TEST_DB = os.environ.get("DG_TEST_DB") or f"driverguard_test_{os.getpid()}"
BASE_URL = os.environ.get(
    "DATABASE_URL", "postgresql+psycopg://driverguard:driverguard@localhost:5432/driverguard"
)
TEST_URL = BASE_URL.rsplit("/", 1)[0] + "/" + TEST_DB
os.environ["DATABASE_URL"] = TEST_URL
os.environ["AI_PROVIDER"] = "mock"  # тесты никогда не ходят в Gemini, даже с ключом в .env
# Rate limit не должен мешать сотням запросов тестов с одного «IP»; сам лимитер проверяется
# в test_hardening.py, временно понижая порог
os.environ.setdefault("RATE_LIMIT_AUTH_PER_MIN", "100000")
os.environ.setdefault("RATE_LIMIT_PER_MIN", "100000")
os.environ.setdefault("DEMO_MODE", "false")  # симулятор движения не нужен в тестах
os.environ.setdefault(
    "JWT_SECRET", "test-" + "0123456789abcdef" * 4
)  # ≥32 байт: слабый секрет = отказ старта
os.environ.setdefault("DG_SEED_KNOWN_SECRETS", "1")  # тесты знают секреты device-secret-N
_ADMIN_DSN = BASE_URL.replace("postgresql+psycopg://", "postgresql://")


def _ensure_test_db() -> None:
    with psycopg.connect(_ADMIN_DSN, autocommit=True) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (TEST_DB,)).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{TEST_DB}"')


def _drop_test_db() -> None:
    if os.environ.get("DG_TEST_DB"):
        return  # именованную базу оставляем (отладка)
    try:
        engine.dispose()
        with psycopg.connect(_ADMIN_DSN, autocommit=True) as conn:
            conn.execute(f'DROP DATABASE IF EXISTS "{TEST_DB}" WITH (FORCE)')
    except Exception:  # noqa: BLE001 — уборка не должна ронять отчёт тестов
        pass


_ensure_test_db()
atexit.register(_drop_test_db)

from fastapi.testclient import TestClient  # noqa: E402

from app.db import Base, SessionLocal, engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models import Depot, Device, Driver, User, Vehicle  # noqa: E402
from app.security import hash_secret  # noqa: E402

# Тестовая БД пересоздаётся из моделей (миграции Alembic — для dev/prod)
Base.metadata.drop_all(engine)
Base.metadata.create_all(engine)

TABLES = (
    "retrain_queue, audit_log, heartbeats, driver_trainings, trainings, checklists, "
    "events, breaks, trips, devices, vehicles, drivers, settings, users, depots"
)


@pytest.fixture()
def db():
    with SessionLocal() as session:
        from sqlalchemy import text

        session.execute(text(f"TRUNCATE {TABLES} RESTART IDENTITY CASCADE"))
        session.commit()
        yield session


@pytest.fixture()
def client(db):
    return TestClient(app)


@pytest.fixture()
def admin(db):
    user = User(
        role="admin",
        email="admin@test.kz",
        password_hash=hash_secret("admin123"),
        name="Тест Админ",
        created_at=datetime.now(UTC),
    )
    db.add(user)
    db.commit()
    return user


@pytest.fixture()
def admin_headers(client, admin):
    resp = client.post(
        "/api/v1/auth/login", json={"email": "admin@test.kz", "password": "admin123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture()
def seeded(db):
    """Полный демо-seed (цифры Figma) — для тестов дашборда, отчётов и настроек."""
    from app import seed as seed_module

    seed_module.run(db)
    return db


@pytest.fixture()
def headers(client, seeded):
    resp = client.post(
        "/api/v1/auth/login", json={"email": "admin@driverguard.kz", "password": "admin123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture()
def viewer_headers(client, db):
    """Роль viewer (SEC-1: только чтение, без телефонов водителей)."""
    db.add(
        User(
            role="viewer",
            email="viewer@test.kz",
            password_hash=hash_secret("viewer123"),
            name="Наблюдатель",
            created_at=datetime.now(UTC),
        )
    )
    db.commit()
    resp = client.post(
        "/api/v1/auth/login", json={"email": "viewer@test.kz", "password": "viewer123"}
    )
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture()
def base_fleet(db):
    """Минимальный парк: депо, водитель, машина, устройство."""
    now = datetime.now(UTC)
    depot = Depot(name="Астана")
    db.add(depot)
    db.flush()
    driver = Driver(name="Иванов А.С.", depot_id=depot.id, phone="+77010000001", created_at=now)
    db.add(driver)
    db.flush()
    vehicle = Vehicle(
        plate="KZ 4521 AB", model="КамАЗ-5490", depot_id=depot.id, driver_id=driver.id
    )
    db.add(vehicle)
    db.flush()
    device = Device(
        serial="DG-0001",
        secret_hash=hash_secret("secret-1"),
        vehicle_id=vehicle.id,
        last_seen=now,
    )
    db.add(device)
    db.commit()
    return {"depot": depot, "driver": driver, "vehicle": vehicle, "device": device}
