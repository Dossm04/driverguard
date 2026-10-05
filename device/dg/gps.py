"""GPS (DEV-20): gpsd по TCP-JSON; без gpsd — симуляция движения по трассе или «нет фикса»."""

from __future__ import annotations

import json
import math
import select
import socket
import time
from dataclasses import dataclass
from datetime import UTC, datetime

# Трасса Астана → Караганда — та же, что в backend/app/geo.py (Live-карта)
ROUTE: list[tuple[float, float]] = [
    (51.128, 71.430),
    (51.02, 71.62),
    (50.90, 71.83),
    (50.76, 72.06),
    (50.60, 72.28),
    (50.42, 72.47),
    (50.23, 72.66),
    (50.055, 72.964),
    (49.93, 73.03),
    (49.806, 73.085),
]


@dataclass
class Fix:
    lat: float | None
    lon: float | None
    speed_kmh: float | None
    valid: bool
    ts: datetime
    source: str = "gps"


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Расстояние между двумя точками, км (для пробега рейса из GPS-фиксов)."""
    r = 6371.0
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dphi, dl = math.radians(lat2 - lat1), math.radians(lon2 - lon1)
    a = math.sin(dphi / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


class Odometer:
    """Накапливает км между валидными фиксами; delta отдаётся в heartbeat (trip_km_delta)."""

    def __init__(self, max_jump_km: float = 20.0):
        self.total_km = 0.0
        self.pending_km = 0.0
        self._last: tuple[float, float] | None = None
        self.max_jump_km = max_jump_km  # скачок больше (потеря фикса / телепорт) — не считаем

    def update(self, fix: Fix) -> float:
        if not fix.valid or fix.lat is None or fix.lon is None:
            self._last = None
            return 0.0
        d = 0.0
        if self._last is not None:
            d = haversine_km(self._last[0], self._last[1], fix.lat, fix.lon)
            if d > self.max_jump_km:
                d = 0.0
        self._last = (fix.lat, fix.lon)
        self.total_km += d
        self.pending_km += d
        return d

    def take_delta(self) -> float:
        delta, self.pending_km = round(self.pending_km, 3), 0.0
        return delta


def route_point(t: float) -> tuple[float, float]:
    t = max(0.0, min(1.0, t))
    s = t * (len(ROUTE) - 1)
    i = min(int(s), len(ROUTE) - 2)
    f = s - i
    return (
        round(ROUTE[i][0] + (ROUTE[i + 1][0] - ROUTE[i][0]) * f, 5),
        round(ROUTE[i][1] + (ROUTE[i + 1][1] - ROUTE[i][1]) * f, 5),
    )


class NoGps:
    """Нет приёмника: события уходят с gps_valid=false."""

    def read(self) -> Fix:
        return Fix(None, None, None, False, datetime.now(UTC), "none")


class SimGps:
    """Движение по трассе: скорость плавно меняется 55…125 км/ч, круг ~40 мин на speedup=1."""

    def __init__(self, speedup: float = 1.0, seed: float = 0.0):
        self.t0 = time.monotonic()
        self.speedup = speedup
        self.seed = seed

    def read(self) -> Fix:
        elapsed = (time.monotonic() - self.t0) * self.speedup
        pos = (elapsed / 2400.0 + self.seed) % 1.0
        lat, lon = route_point(pos)
        speed = 90 + 35 * math.sin(elapsed / 90.0 + self.seed * 6.28) + 8 * math.sin(elapsed / 7.0)
        return Fix(lat, lon, round(max(0.0, speed), 1), True, datetime.now(UTC), "sim")


class GpsdGps:
    """Минимальный клиент gpsd (порт 2947, ?WATCH json): читает TPV, при отсутствии фикса — valid=False."""

    def __init__(self, host: str = "127.0.0.1", port: int = 2947, timeout: float = 1.0):
        self.host, self.port, self.timeout = host, port, timeout
        self._sock: socket.socket | None = None
        self._buf = b""
        self._last = Fix(None, None, None, False, datetime.now(UTC), "gps")

    def _connect(self) -> None:
        self._sock = socket.create_connection((self.host, self.port), timeout=self.timeout)
        self._sock.sendall(b'?WATCH={"enable":true,"json":true}\n')

    def read(self) -> Fix:
        """Не блокирует поток кадров: читает только уже пришедшие данные (select с нулевым ожиданием)."""
        try:
            if self._sock is None:
                self._connect()
            assert self._sock is not None
            ready, _, _ = select.select([self._sock], [], [], 0)
            if not ready:
                return self._last
            chunk = self._sock.recv(65536)
            if not chunk:  # gpsd закрыл соединение
                raise OSError("gpsd closed")
            self._buf += chunk
            while b"\n" in self._buf:
                line, self._buf = self._buf.split(b"\n", 1)
                try:
                    msg = json.loads(line)
                except ValueError:
                    continue
                if msg.get("class") == "TPV":
                    mode = int(msg.get("mode", 0))
                    if mode >= 2 and "lat" in msg and "lon" in msg:
                        speed = msg.get("speed")
                        self._last = Fix(
                            float(msg["lat"]),
                            float(msg["lon"]),
                            round(float(speed) * 3.6, 1) if speed is not None else None,
                            True,
                            datetime.now(UTC),
                            "gps",
                        )
                    else:
                        self._last = Fix(None, None, None, False, datetime.now(UTC), "gps")
        except (OSError, TimeoutError):
            self._sock = None
            self._last = Fix(self._last.lat, self._last.lon, None, False, datetime.now(UTC), "gps")
        return self._last


def make_gps(mode: str, speedup: float = 1.0):
    if mode == "sim":
        return SimGps(speedup=speedup)
    if mode == "gpsd":
        return GpsdGps()
    return NoGps()
