"""WebSocket /ws/live (BE-16): позиции машин, новые события, статусы устройств.

Для демо (SYS: режим «Симуляция») фоновая задача двигает машины по маршруту
М-36 каждые 2 секунды — как в эталонном прототипе.
"""

import asyncio
import contextlib
import logging
from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Query, WebSocket, WebSocketDisconnect
from sqlalchemy import select, update
from sqlalchemy.orm import joinedload

from app import scoring, stats
from app.db import SessionLocal
from app.geo import route_point
from app.models import Device, Event, Heartbeat, User
from app.security import decode_token

logger = logging.getLogger(__name__)
router = APIRouter()

ONLINE_WINDOW = timedelta(minutes=5)
TICK_S = 2.0
SCORE_REFRESH_TICKS = 15  # пересчёт Score раз в ~30 секунд


def mask_phones(payload: dict) -> dict:
    """SEC-5: копия сообщения без телефонов водителей (для соединений роли viewer)."""
    masked = dict(payload)
    if isinstance(masked.get("vehicles"), list):
        masked["vehicles"] = [{**v, "driver_phone": None} for v in masked["vehicles"]]
    if isinstance(masked.get("event"), dict):
        masked["event"] = {**masked["event"], "driver_phone": None}
    return masked


class ConnectionManager:
    MAX_PER_USER = 6  # вкладки одного координатора; защита от утечки соединений

    def __init__(self) -> None:
        self.connections: list[WebSocket] = []
        self.roles: dict[WebSocket, str] = {}
        self.users: dict[WebSocket, int] = {}
        self.loop: asyncio.AbstractEventLoop | None = None

    async def connect(self, ws: WebSocket, role: str = "coordinator", user_id: int = 0) -> None:
        await ws.accept()
        self.connections.append(ws)
        self.roles[ws] = role
        self.users[ws] = user_id

    def disconnect(self, ws: WebSocket) -> None:
        if ws in self.connections:
            self.connections.remove(ws)
        self.roles.pop(ws, None)
        self.users.pop(ws, None)

    def for_role(self, payload: dict, role: str) -> dict:
        return mask_phones(payload) if role == "viewer" else payload

    SEND_TIMEOUT_S = 3.0  # зависшая панель (плохой Wi-Fi) не должна тормозить карту у остальных

    async def _send_one(self, ws: WebSocket, payload: dict, masked: dict) -> None:
        try:
            await asyncio.wait_for(
                ws.send_json(masked if self.roles.get(ws) == "viewer" else payload),
                self.SEND_TIMEOUT_S,
            )
        except Exception:
            self.disconnect(ws)
            with contextlib.suppress(Exception):
                await ws.close(code=1011, reason="Соединение не отвечает")

    async def broadcast(self, payload: dict) -> None:
        masked = mask_phones(payload)
        conns = list(self.connections)
        if conns:
            await asyncio.gather(*(self._send_one(ws, payload, masked) for ws in conns))

    def connections_of(self, user_id: int) -> int:
        return sum(1 for ws in self.connections if self.users.get(ws) == user_id)

    def broadcast_threadsafe(self, payload: dict) -> None:
        """Публикация из sync-эндпоинтов (пул потоков FastAPI)."""
        if self.loop is None or not self.connections:
            return
        asyncio.run_coroutine_threadsafe(self.broadcast(payload), self.loop)


manager = ConnectionManager()

# Доли пути машин на маршруте (стартовые позиции — как VPOS в прототипе)
_positions: dict[int, float] = {}

# Живые позиции от PWA «Камера» (телефон в кабине): vehicle_id → (lat, lon, км/ч, когда).
# Пока телефон шлёт heartbeat (≤2 мин), машина на карте стоит там, где телефон, а не на
# демо-маршруте. Состояние процесса — один backend-процесс (см. docs/decisions.md).
LIVE_TTL = timedelta(minutes=2)
_live: dict[int, tuple[float, float, float, datetime]] = {}
_live_swept_at = datetime.now(UTC)


def set_live_position(vehicle_id: int, lat: float, lon: float, speed_kmh: float | None) -> None:
    global _live_swept_at
    now = datetime.now(UTC)
    _live[vehicle_id] = (lat, lon, speed_kmh or 0.0, now)
    # Раз в минуту убираем протухшие позиции (машины, которые больше никто не читает,
    # иначе словарь рос бы на каждую удалённую машину)
    if now - _live_swept_at > timedelta(minutes=1):
        _live_swept_at = now
        for vid in [vid for vid, item in _live.items() if now - item[3] > LIVE_TTL]:
            _live.pop(vid, None)


def live_position(vehicle_id: int) -> tuple[float, float, float] | None:
    item = _live.get(vehicle_id)
    if item is None:
        return None
    lat, lon, speed, ts = item
    if datetime.now(UTC) - ts > LIVE_TTL:
        _live.pop(vehicle_id, None)
        return None
    return lat, lon, speed


_INITIAL_T = [0.16, 0.34, 0.88, 0.30, 0.70, 0.52]


def _snapshot() -> dict:
    """Текущее состояние машин: позиция, скорость, статус, Score, последнее событие."""
    now = datetime.now(UTC)
    with SessionLocal() as db:
        devices = db.scalars(
            select(Device).options(joinedload(Device.vehicle)).order_by(Device.id)
        ).all()
        streaks = stats.streaks_by_driver(db, now)
        scores = stats.scores_by_driver(db, now - timedelta(days=7), now, 7, streaks)
        # Последнее учитываемое событие каждого водителя — для попапа на карте
        last_events = {
            e.driver_id: e
            for e in db.scalars(
                select(Event)
                .where(Event.driver_id.is_not(None), Event.status.in_(scoring.SCORED_STATUSES))
                .order_by(Event.driver_id, Event.ts.desc())
                .distinct(Event.driver_id)
            ).all()
        }
        vehicles = []
        for i, device in enumerate(devices):
            vehicle = device.vehicle
            if vehicle is None:
                continue
            driver = vehicle.driver
            online = bool(device.last_seen and now - device.last_seen <= ONLINE_WINDOW)
            t = _positions.setdefault(vehicle.id, _INITIAL_T[i % len(_INITIAL_T)])
            live = live_position(vehicle.id)
            lat, lon = (live[0], live[1]) if live else route_point(t)
            score = scores[driver.id].score if driver and driver.id in scores else None
            if not online:
                status_ = "offline"
            elif score is not None and score < 70:
                status_ = "danger"
            elif score is not None and score < 85:
                status_ = "warn"
            else:
                status_ = "ok"
            last = last_events.get(driver.id) if driver else None
            vehicles.append(
                {
                    "vehicle_id": vehicle.id,
                    "plate": vehicle.plate,
                    "driver_id": driver.id if driver else None,
                    "driver_name": driver.name if driver else None,
                    "driver_phone": driver.phone if driver else None,
                    "lat": lat,
                    "lon": lon,
                    "speed_kmh": (
                        round(live[2]) if live else 0 if not online else 62 + (vehicle.id * 7) % 25
                    ),
                    "status": status_,
                    "score": score,
                    "last_event": {
                        "type": last.type,
                        "value": last.value,
                        "severity": last.severity,
                        "ts": last.ts.isoformat(),
                    }
                    if last
                    else None,
                }
            )
    return {"type": "positions", "ts": now.isoformat(), "vehicles": vehicles}


# Устройства, которые демо-симулятор держит онлайн. Набор фиксируется ОДИН раз на
# старте по относительной свежести last_seen (в пределах 30 минут от самого свежего):
# так DG-0005 («офлайн 3 часа» из seed) остаётся офлайн, картинка 5/6 переживает
# простой backend любой длины, а реальное устройство, потерявшее связь после старта,
# не «оживляется» навсегда. В пилоте DEMO_MODE=false — keepalive выключен целиком.
_demo_online_ids: list[int] | None = None
_demo_last_heartbeat: datetime | None = None
HEARTBEAT_PERIOD = timedelta(minutes=10)  # REL-5


def _demo_keepalive() -> None:
    global _demo_online_ids, _demo_last_heartbeat
    now = datetime.now(UTC)
    with SessionLocal() as db:
        if _demo_online_ids is None:
            # Телефоны (fw_version=web) симулятор не «оживляет»: их онлайн — настоящий heartbeat
            rows = db.execute(select(Device.id, Device.last_seen, Device.fw_version)).all()
            seen = [ls for _, ls, _ in rows if ls is not None]
            if not seen:
                _demo_online_ids = []
            else:
                freshest = max(seen)
                _demo_online_ids = [
                    device_id
                    for device_id, ls, fw in rows
                    if ls is not None and fw != "web" and freshest - ls <= timedelta(minutes=30)
                ]
        if not _demo_online_ids:
            return
        db.execute(update(Device).where(Device.id.in_(_demo_online_ids)).values(last_seen=now))
        # «Живые» устройства продолжают слать телеметрию раз в 10 минут — иначе
        # KPI аптайма (скользящее 7-дневное окно heartbeat'ов) дрейфует вниз.
        if _demo_last_heartbeat is None or now - _demo_last_heartbeat >= HEARTBEAT_PERIOD:
            _demo_last_heartbeat = now
            for i, device_id in enumerate(_demo_online_ids):
                db.add(
                    Heartbeat(
                        device_id=device_id,
                        ts=now,
                        temp_c=52.0 + i,
                        fps=14.0,
                        disk_free=40.0,
                        gps_fix=True,
                        net="lte",
                    )
                )
        db.commit()


async def simulator() -> None:
    """Демо-движение машин по трассе + периодический broadcast позиций."""
    tick = 0
    snapshot: dict | None = None
    while True:
        try:
            if snapshot is None or tick % SCORE_REFRESH_TICKS == 0:
                # блокирующую работу с БД уводим с event loop
                await asyncio.to_thread(_demo_keepalive)
                snapshot = await asyncio.to_thread(_snapshot)
            else:
                for v in snapshot["vehicles"]:
                    live = live_position(v["vehicle_id"])
                    if live:
                        v["lat"], v["lon"], v["speed_kmh"] = live[0], live[1], round(live[2])
                    elif v["status"] != "offline":
                        v["lat"], v["lon"] = route_point(_positions.get(v["vehicle_id"], 0.5))
                snapshot["ts"] = datetime.now(UTC).isoformat()
            offline_ids = {
                v["vehicle_id"] for v in snapshot["vehicles"] if v["status"] == "offline"
            }
            for vid, t in list(_positions.items()):
                if vid in offline_ids or vid in _live:
                    continue  # без связи — стоит; с телефоном — там, где телефон
                new_t = t + 0.0011 * TICK_S
                _positions[vid] = 0.02 if new_t > 0.98 else new_t
            await manager.broadcast(snapshot)
        except Exception:
            logger.exception("Симулятор live-карты: ошибка тика")
            snapshot = None  # на следующем тике перечитаем состояние из БД
        tick += 1
        await asyncio.sleep(TICK_S)


def _staff_role(user_id: int) -> str | None:
    with SessionLocal() as db:
        user = db.get(User, user_id)
        if user is None or user.role not in ("admin", "coordinator", "viewer"):
            return None
        return user.role


@router.websocket("/ws/live")
async def ws_live(ws: WebSocket, token: str = Query(default="")) -> None:
    try:
        payload = decode_token(token)
    except Exception:
        payload = {}
    # Явные проверки (не assert): live-карта — только для сотрудников с access-токеном
    if payload.get("typ") != "access" or payload.get("role") not in (
        "admin",
        "coordinator",
        "viewer",
    ):
        await ws.close(code=4401, reason="Требуется access-токен сотрудника")
        return
    # Роль — из базы, а не из claims: удалённый или пониженный до viewer пользователь
    # не должен до истечения токена видеть карту с телефонами
    user_id = int(payload.get("sub", 0) or 0)
    role = await asyncio.to_thread(_staff_role, user_id)
    if role is None:
        await ws.close(code=4401, reason="Учётка не найдена или без доступа к карте")
        return
    if manager.connections_of(user_id) >= manager.MAX_PER_USER:
        await ws.close(code=4429, reason="Слишком много соединений у одного пользователя")
        return
    await manager.connect(ws, role, user_id)
    try:
        snapshot = await asyncio.to_thread(_snapshot)
        await ws.send_json(manager.for_role(snapshot, role))  # мгновенный снимок
        while True:
            await ws.receive_text()  # ping от клиента; данные не используются
    except WebSocketDisconnect:
        pass
    finally:
        manager.disconnect(ws)


@contextlib.asynccontextmanager
async def lifespan(app):  # noqa: ANN001 — сигнатура FastAPI
    from app.config import get_settings

    # loop нужен broadcast_threadsafe и без демо-симулятора (BE-16)
    manager.loop = asyncio.get_running_loop()
    task = None
    if get_settings().demo_mode:
        task = asyncio.create_task(simulator())
    yield
    if task:
        task.cancel()
        with contextlib.suppress(asyncio.CancelledError):
            await task
