"""Нагрузочный тест стенда для жюри (PRODUCTION_STANDARDS 9, 11): N «телефонов» с PWA «Камера»
и M панелей координаторов одновременно — так, как это будет в зале.

  cd backend && .venv/bin/python scripts/load_test.py --drivers 40 --admins 5 --duration 60
  make load-test N=40 ADMINS=5 DURATION=60          # то же, читает infra/.env

Что делает каждый «телефон» (как components/driver/dms-camera.tsx): вход по PIN, heartbeat
каждые 15 с с координатами, событие DMS каждые --event-every с, профиль /drivers/me каждые 30 с.
Каждая «панель»: вход, WebSocket /ws/live (считает сообщения), опрос сводки/событий/лидерборда
каждые 30 с, графиков — каждые 60 с (интервалы TanStack Query из панели).

Учётки создаются прямо в базе (DATABASE_URL, как у backend) и удаляются в конце (--keep —
оставить). Итог: таблица латентности p50/p95/max и ошибок по маршрутам, сообщения WS,
серверные метрики /health/metrics (если есть учётка admin), код выхода 1 при превышении
--max-error-rate или --max-p95-ms.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import random
import secrets
import statistics
import sys
import time
import uuid
from collections import defaultdict
from datetime import UTC, datetime, timedelta
from pathlib import Path

import httpx

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import delete, select  # noqa: E402

from app.db import SessionLocal  # noqa: E402
from app.models import Depot, Device, Driver, Event, Heartbeat, Trip, User, Vehicle  # noqa: E402
from app.security import hash_secret  # noqa: E402

PHONE_PREFIX = "+77771"  # +7 7771 NNNNNN — не пересекается с seed и менторами (+77770)
EMAIL_DOMAIN = "load.driverguard.kz"
PIN = f"{secrets.randbelow(10_000):04d}"  # случайный на запуск: учётки нагрузки не угадать
PASSWORD = "load-" + secrets.token_hex(4)
ASTANA = (51.1605, 71.4704)
EVENT_TYPES = [
    ("head_nod", "warning"),
    ("distraction", "warning"),
    ("fatigue", "warning"),
    ("microsleep", "critical"),
    ("camera_sabotage", "critical"),
]


# ── учётки ────────────────────────────────────────────────────────────────────
def setup_accounts(drivers: int, admins: int) -> None:
    now = datetime.now(UTC)
    with SessionLocal() as db:
        depot_id = db.scalar(select(Depot.id).order_by(Depot.id).limit(1))
        if depot_id is None:
            depot = Depot(name="Нагрузка")
            db.add(depot)
            db.flush()
            depot_id = depot.id
        for n in range(1, drivers + 1):
            phone = f"{PHONE_PREFIX}{n:06d}"
            user = db.scalar(select(User).where(User.phone == phone))
            if user is None:
                user = User(role="driver", phone=phone, name=f"Нагрузка {n}", created_at=now)
                db.add(user)
            user.pin_hash = hash_secret(PIN)
            db.flush()
            driver = db.scalar(select(Driver).where(Driver.user_id == user.id))
            if driver is None:
                driver = Driver(
                    user_id=user.id,
                    name=f"Нагрузка {n}",
                    depot_id=depot_id,
                    phone=phone,
                    consent_signed_at=now,
                    created_at=now - timedelta(days=1),
                )
                db.add(driver)
                db.flush()
            plate = f"KZ 8{n:03d} LT"
            if db.scalar(select(Vehicle.id).where(Vehicle.plate == plate)) is None:
                db.add(
                    Vehicle(
                        plate=plate,
                        model="Нагрузочная машина",
                        depot_id=depot_id,
                        driver_id=driver.id,
                        profile="city",
                    )
                )
        for m in range(1, admins + 1):
            email = f"load-admin{m}@{EMAIL_DOMAIN}"
            user = db.scalar(select(User).where(User.email == email))
            if user is None:
                user = User(role="coordinator", email=email, name=f"Панель {m}", created_at=now)
                db.add(user)
            user.password_hash = hash_secret(PASSWORD)
        db.commit()


def remove_accounts() -> int:
    removed = 0
    with SessionLocal() as db:
        for user in db.scalars(select(User).where(User.phone.like(f"{PHONE_PREFIX}%"))).all():
            driver = db.scalar(select(Driver).where(Driver.user_id == user.id))
            if driver is not None:
                db.execute(delete(Event).where(Event.driver_id == driver.id))
                db.execute(delete(Trip).where(Trip.driver_id == driver.id))
                vehicle = db.scalar(select(Vehicle).where(Vehicle.driver_id == driver.id))
                if vehicle is not None:
                    dev_ids = select(Device.id).where(Device.vehicle_id == vehicle.id)
                    db.execute(delete(Heartbeat).where(Heartbeat.device_id.in_(dev_ids)))
                    db.execute(delete(Event).where(Event.device_id.in_(dev_ids)))
                    db.execute(delete(Device).where(Device.vehicle_id == vehicle.id))
                    db.delete(vehicle)
                    db.flush()
                db.delete(driver)
                db.flush()  # у моделей нет relationship user↔driver — порядок удаления задаём сами
            db.delete(user)
            removed += 1
        db.execute(delete(User).where(User.email.like(f"%@{EMAIL_DOMAIN}")))
        db.commit()
    return removed


# ── статистика ────────────────────────────────────────────────────────────────
class Stats:
    def __init__(self) -> None:
        self.lat: dict[str, list[float]] = defaultdict(list)
        self.status: dict[str, dict[int, int]] = defaultdict(lambda: defaultdict(int))
        self.exceptions: dict[str, int] = defaultdict(int)
        self.ws_messages = 0
        self.ws_errors = 0

    def add(self, route: str, status: int, ms: float) -> None:
        self.lat[route].append(ms)
        self.status[route][status] += 1

    @staticmethod
    def pct(values: list[float], p: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        return ordered[min(len(ordered) - 1, int(round((len(ordered) - 1) * p)))]

    def total(self) -> tuple[int, int, float]:
        all_lat = [v for vs in self.lat.values() for v in vs]
        count = len(all_lat)
        errors = sum(
            n
            for by_status in self.status.values()
            for st, n in by_status.items()
            if st >= 500 or st == 0
        ) + sum(self.exceptions.values())
        return count, errors, self.pct(all_lat, 0.95)

    def report(self) -> str:
        lines = [
            f"{'маршрут':<44}{'запросов':>9}{'ошибок':>8}{'p50 мс':>9}{'p95 мс':>9}{'max мс':>9}"
        ]
        for route in sorted(self.lat):
            vals = self.lat[route]
            errs = (
                sum(n for st, n in self.status[route].items() if st >= 400) + self.exceptions[route]
            )
            lines.append(
                f"{route:<44}{len(vals):>9}{errs:>8}{statistics.median(vals):>9.0f}"
                f"{self.pct(vals, 0.95):>9.0f}{max(vals):>9.0f}"
            )
        bad = {r: dict(s) for r, s in self.status.items() if any(st >= 400 for st in s)}
        if bad:
            lines.append(f"статусы ≥400: {bad}")
        exceptions = {r: n for r, n in self.exceptions.items() if n}
        if exceptions:
            lines.append(f"сетевые исключения: {exceptions}")
        lines.append(f"WebSocket: сообщений {self.ws_messages}, ошибок {self.ws_errors}")
        return "\n".join(lines)


stats = Stats()


async def call(
    client: httpx.AsyncClient, route: str, method: str, url: str, **kw
) -> httpx.Response | None:
    started = time.perf_counter()
    try:
        resp = await client.request(method, url, **kw)
    except httpx.HTTPError as exc:
        stats.exceptions[route] += 1
        stats.add(route, 0, (time.perf_counter() - started) * 1000)
        print(f"  ! {route}: {type(exc).__name__}: {exc}", file=sys.stderr)
        return None
    stats.add(route, resp.status_code, (time.perf_counter() - started) * 1000)
    if resp.status_code >= 400:
        print(f"  ! {route}: {resp.status_code} {resp.text[:120]}", file=sys.stderr)
    return resp


# ── сценарии ──────────────────────────────────────────────────────────────────
async def driver_session(
    client: httpx.AsyncClient, api: str, n: int, deadline: float, event_every: float
) -> None:
    await asyncio.sleep(random.uniform(0, 10))  # телефоны включаются не одновременно
    resp = await call(
        client,
        "POST /auth/driver-login",
        "POST",
        f"{api}/auth/driver-login",
        json={"phone": f"{PHONE_PREFIX}{n:06d}", "pin": PIN},
    )
    if resp is None or resp.status_code != 200:
        return
    headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
    lat, lon = ASTANA[0] + random.uniform(-0.05, 0.05), ASTANA[1] + random.uniform(-0.05, 0.05)
    await call(client, "GET /drivers/me", "GET", f"{api}/drivers/me", headers=headers)
    next_hb = next_ev = next_me = time.monotonic()
    next_me += 30
    while time.monotonic() < deadline:
        now = time.monotonic()
        if now >= next_hb:
            next_hb = now + 15
            lat += random.uniform(-0.0005, 0.0005)
            lon += random.uniform(-0.0005, 0.0005)
            await call(
                client,
                "POST /drivers/me/camera-heartbeat",
                "POST",
                f"{api}/drivers/me/camera-heartbeat",
                headers=headers,
                json={
                    "lat": lat,
                    "lon": lon,
                    "gps_valid": True,
                    "speed_kmh": random.uniform(0, 80),
                    "fps": 24,
                },
            )
        if now >= next_ev:
            next_ev = now + event_every * random.uniform(0.7, 1.3)
            etype, severity = random.choice(EVENT_TYPES)
            await call(
                client,
                "POST /drivers/me/camera-events",
                "POST",
                f"{api}/drivers/me/camera-events",
                headers=headers,
                json=[
                    {
                        "uuid": str(uuid.uuid4()),
                        "type": etype,
                        "severity": severity,
                        "confidence": round(random.uniform(0.6, 0.98), 2),
                        "ts": datetime.now(UTC).isoformat(),
                        "lat": lat,
                        "lon": lon,
                        "gps_valid": True,
                        "speed_kmh": random.uniform(0, 80),
                        "note": "load-test",
                    }
                ],
            )
        if now >= next_me:
            next_me = now + 30
            await call(client, "GET /drivers/me", "GET", f"{api}/drivers/me", headers=headers)
        await asyncio.sleep(0.5)


ADMIN_FAST = [  # каждые 30 с (refetchInterval панели)
    ("GET /dashboard/summary", "/dashboard/summary?period=today"),
    ("GET /dashboard/critical-latest", "/dashboard/critical-latest?limit=3"),
    ("GET /events", "/events?page_size=50"),
    ("GET /leaderboard", "/leaderboard?period=7"),
]
ADMIN_SLOW = [  # каждые 60 с
    ("GET /dashboard/events-by-day", "/dashboard/events-by-day?days=7"),
    ("GET /dashboard/events-by-type", "/dashboard/events-by-type"),
    ("GET /dashboard/red-zone", "/dashboard/red-zone"),
    ("GET /drivers", "/drivers"),
    ("GET /vehicles", "/vehicles"),
    ("GET /devices", "/devices"),
]


async def ws_listener(ws_url: str, token: str, deadline: float) -> None:
    try:
        import websockets
    except ImportError:
        print("  (websockets не установлен — WS не проверяем)", file=sys.stderr)
        return
    while time.monotonic() < deadline:
        try:
            async with websockets.connect(f"{ws_url}?token={token}", open_timeout=10) as ws:
                while time.monotonic() < deadline:
                    try:
                        msg = await asyncio.wait_for(ws.recv(), timeout=5)
                    except TimeoutError:
                        continue
                    stats.ws_messages += 1
                    json.loads(msg)
        except Exception as exc:  # noqa: BLE001 — считаем и переподключаемся, как браузер
            stats.ws_errors += 1
            print(f"  ! WS: {type(exc).__name__}: {exc}", file=sys.stderr)
            await asyncio.sleep(2)


async def admin_session(
    client: httpx.AsyncClient, api: str, ws_url: str, m: int, deadline: float
) -> None:
    await asyncio.sleep(random.uniform(0, 5))
    resp = await call(
        client,
        "POST /auth/login",
        "POST",
        f"{api}/auth/login",
        json={"email": f"load-admin{m}@{EMAIL_DOMAIN}", "password": PASSWORD},
    )
    if resp is None or resp.status_code != 200:
        return
    token = resp.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    listener = asyncio.create_task(ws_listener(ws_url, token, deadline))
    next_fast = next_slow = time.monotonic()
    while time.monotonic() < deadline:
        now = time.monotonic()
        if now >= next_fast:
            next_fast = now + 30
            for route, path in ADMIN_FAST:
                await call(client, route, "GET", f"{api}{path}", headers=headers)
        if now >= next_slow:
            next_slow = now + 60
            for route, path in ADMIN_SLOW:
                await call(client, route, "GET", f"{api}{path}", headers=headers)
        await asyncio.sleep(0.5)
    listener.cancel()


async def server_metrics(
    client: httpx.AsyncClient, api: str, email: str, password: str
) -> dict | None:
    try:
        resp = await client.post(f"{api}/auth/login", json={"email": email, "password": password})
        if resp.status_code != 200:
            return None
        headers = {"Authorization": f"Bearer {resp.json()['access_token']}"}
        resp = await client.get(f"{api}/health/metrics", headers=headers)
        return resp.json() if resp.status_code == 200 else None
    except httpx.HTTPError:
        return None


async def run(args: argparse.Namespace) -> int:
    api = args.api.rstrip("/")
    ws_url = args.ws or api.replace("/api/v1", "/ws/live").replace("https://", "wss://").replace(
        "http://", "ws://"
    )
    limits = httpx.Limits(
        max_connections=args.drivers + args.admins + 20, max_keepalive_connections=100
    )
    async with httpx.AsyncClient(timeout=httpx.Timeout(15.0), limits=limits) as client:
        ready = await client.get(f"{api}/health/ready")
        print(f"readiness: {ready.status_code} {ready.text}")
        deadline = time.monotonic() + args.duration
        print(
            f"Старт: {args.drivers} телефонов (событие раз в ~{args.event_every:.0f} с), "
            f"{args.admins} панелей, {args.duration} с → {api}"
        )
        tasks = [
            asyncio.create_task(driver_session(client, api, n, deadline, args.event_every))
            for n in range(1, args.drivers + 1)
        ] + [
            asyncio.create_task(admin_session(client, api, ws_url, m, deadline))
            for m in range(1, args.admins + 1)
        ]
        started = time.monotonic()
        while time.monotonic() < deadline:
            await asyncio.sleep(10)
            count, errors, p95 = stats.total()
            print(
                f"  {time.monotonic() - started:5.0f} с: запросов {count}, ошибок {errors}, "
                f"p95 {p95:.0f} мс, WS сообщений {stats.ws_messages}"
            )
        # серверные метрики снимаем, пока WS панелей ещё открыты
        snap = await server_metrics(client, api, args.metrics_login, args.metrics_password)
        await asyncio.gather(*tasks, return_exceptions=True)
        print("\n" + stats.report())
        if snap:
            print(
                f"\nСервер: запросов {snap['requests_total']}, 5xx {snap['errors_5xx_total']}, "
                f"429 {snap['rate_limited_total']}, WS {snap['ws_connections']}, "
                f"живых позиций {snap['live_positions']}, потоки {snap['thread_limiter']}, "
                f"пул БД: {snap['db_pool']}"
            )
        else:
            print("\n(/health/metrics недоступен — нет учётки admin, серверные метрики пропущены)")

    count, errors, p95 = stats.total()
    error_rate = errors / count if count else 1.0
    verdict_ok = (
        error_rate <= args.max_error_rate and p95 <= args.max_p95_ms and stats.ws_errors == 0
    )
    verdict = "OK" if verdict_ok else "ПОРОГ ПРЕВЫШЕН"
    print(
        f"\nИТОГ: {count} запросов, ошибок {errors} ({error_rate:.2%}), p95 {p95:.0f} мс — "
        f"{verdict} (порог: ошибок ≤{args.max_error_rate:.1%}, p95 ≤{args.max_p95_ms} мс)"
    )
    return 0 if verdict_ok else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Нагрузочный тест: телефоны с камерой + панели")
    parser.add_argument("--api", default="http://localhost:8000/api/v1")
    parser.add_argument("--ws", default="", help="адрес WebSocket (по умолчанию из --api)")
    parser.add_argument("--drivers", type=int, default=40)
    parser.add_argument("--admins", type=int, default=5)
    parser.add_argument("--duration", type=int, default=60, help="секунд")
    parser.add_argument(
        "--event-every", type=float, default=20.0, help="секунд между событиями телефона"
    )
    parser.add_argument("--max-error-rate", type=float, default=0.005)
    parser.add_argument("--max-p95-ms", type=float, default=1000)
    parser.add_argument("--metrics-login", default="admin@driverguard.kz")
    parser.add_argument("--metrics-password", default="admin123")
    parser.add_argument("--keep", action="store_true", help="не удалять учётки после теста")
    parser.add_argument("--remove", action="store_true", help="только удалить учётки нагрузки")
    args = parser.parse_args(argv)
    if args.remove:
        print(f"Удалено учёток: {remove_accounts()}")
        return 0
    setup_accounts(args.drivers, args.admins)
    try:
        return asyncio.run(run(args))
    finally:
        if not args.keep:
            print(f"Учётки нагрузки удалены: {remove_accounts()}")


if __name__ == "__main__":
    sys.exit(main())
