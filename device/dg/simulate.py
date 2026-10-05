"""Режим --simulate (DEV-25): без камеры генерирует реалистичные события и движение по трассе."""

from __future__ import annotations

import logging
import random
import time
import uuid
from datetime import UTC, datetime

from dg.config import Config
from dg.gps import SimGps
from dg.store import Store

log = logging.getLogger("dg.sim")

# Средний интервал между событиями типа, с (при speedup=1); severity и value-генератор
PROFILE = {
    "microsleep": (420, "critical", lambda r: round(r.uniform(1.6, 3.2), 1)),
    "distraction": (180, "warning", lambda r: r.choice([8, 9, 11, 12])),
    "phone": (600, "critical", lambda r: None),
    "head_nod": (240, "warning", lambda r: round(r.uniform(0.14, 0.3), 2)),
    "fatigue": (300, "warning", lambda r: r.randint(20, 34)),
    "smoking": (900, "warning", lambda r: r.randint(3, 8)),
    "seatbelt": (1500, "warning", lambda r: r.randint(30, 90)),
    "harsh_braking": (400, "info", lambda r: round(r.uniform(0.4, 0.7), 2)),
}


class Simulator:
    def __init__(self, cfg: Config, store: Store, speedup: float = 1.0, seed: int | None = None, on_event=None):
        self.cfg, self.store, self.speedup = cfg, store, speedup
        self.rng = random.Random(seed)
        # позиция — общий SimGps устройства (app.run_simulate подставляет dev.gps); свой — запасной
        self.gps = SimGps(speedup=speedup, seed=0.0 if seed is not None else self.rng.random())
        self.on_event = on_event
        self.speeding_since: float | None = None
        self.last_speeding = -1e9
        self.generated = 0

    def _event(self, type_: str, severity: str, value, fix) -> dict:
        return {
            "uuid": str(uuid.uuid4()),
            "type": type_,
            "severity": severity,
            "ts": datetime.now(UTC).isoformat(),
            "lat": fix.lat,
            "lon": fix.lon,
            "gps_valid": fix.valid,
            "speed_kmh": fix.speed_kmh,
            "speed_source": "sim",
            "confidence": round(self.rng.uniform(0.72, 0.98), 2),
            "value": value,
            "context": {"simulated": True},
        }

    def tick(self, dt_s: float) -> list[dict]:
        """Один шаг симуляции длиной dt_s секунд модельного времени; возвращает события."""
        fix = self.gps.read()
        out = []
        for type_, (interval, severity, gen) in PROFILE.items():
            if self.rng.random() < dt_s / interval:
                sev = severity
                if type_ == "microsleep" and (fix.speed_kmh or 0) < 5:
                    continue  # стоим — микросон не событие
                out.append(self._event(type_, sev, gen(self.rng), fix))
        limit = self.cfg.speed_limit
        now = time.monotonic() * self.speedup
        if fix.speed_kmh and fix.speed_kmh > limit:
            self.speeding_since = self.speeding_since or now
            if now - self.speeding_since >= self.cfg.thresholds.SPEEDING_MS / 1000 and now - self.last_speeding > 60:
                over = round(fix.speed_kmh - limit)
                out.append(self._event("speeding", "critical" if over >= 30 else "warning", over, fix))
                self.last_speeding = now
        else:
            self.speeding_since = None
        for e in out:
            self.store.add_event(e)
            self.generated += 1
            log.info(
                "Событие: %s (%s) %s км/ч @ %.4f,%.4f", e["type"], e["severity"], e["speed_kmh"], e["lat"], e["lon"]
            )
            if self.on_event:
                self.on_event(e)
        return out
