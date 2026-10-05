"""Кольцевой буфер и клип (DEV-17), симулятор (DEV-25), конфиг (DEV-24)."""

import os
from datetime import UTC, datetime

import numpy as np

from dg import config
from dg.config import Config
from dg.gps import SimGps, route_point
from dg.recorder import Recorder, RingBuffer
from dg.simulate import Simulator
from dg.store import Store


def frame(v: int) -> np.ndarray:
    return np.full((480, 640, 3), v % 255, dtype=np.uint8)


def test_ring_buffer_keeps_last_seconds():
    ring = RingBuffer(seconds=2, fps=10)
    for i in range(50):
        ring.push(i * 100, frame(i))
    assert len(ring.frames) == 20 and ring.frames[0][0] == 3000
    assert len(ring.between(4000, 4500)) == 6


def test_recorder_writes_clip_pre_and_post(tmp_path):
    written = {}
    rec = Recorder(tmp_path, fps=10, buffer_s=20, pre_s=1, post_s=1, on_clip=lambda u, p: written.__setitem__(u, p))
    for i in range(30):  # 3 с видео
        rec.push(i * 100, frame(i))
        if i == 15:
            rec.on_event("evt-1", 1500)
    rec.flush()
    import time

    for _ in range(50):  # запись идёт в фоновом потоке
        if "evt-1" in written:
            break
        time.sleep(0.1)
    path = written["evt-1"]
    assert path.endswith("evt-1.mp4") and os.path.getsize(path) > 0
    assert rec.pending == []


def test_simulator_generates_valid_events(tmp_path):
    cfg = Config(db_path=str(tmp_path / "dg.sqlite"))
    store = Store(cfg.db_path)
    sim = Simulator(cfg, store, speedup=60, seed=7)
    for _ in range(120):  # 2 модельных часа
        sim.tick(60)
    events = store.recent_events(500)
    assert len(events) >= 10
    types = {e["type"] for e in events}
    assert types <= {
        "microsleep",
        "distraction",
        "phone",
        "head_nod",
        "fatigue",
        "smoking",
        "seatbelt",
        "harsh_braking",
        "speeding",
    }
    assert all(e["gps_valid"] and 49.7 < e["lat"] < 51.2 and 0.6 <= e["confidence"] <= 1 for e in events)
    assert store.counts()["pending"] == len(events)


def test_sim_gps_moves_along_route():
    gps = SimGps(speedup=600)
    a = gps.read()
    import time

    time.sleep(0.2)
    b = gps.read()
    assert a.valid and b.valid and (a.lat, a.lon) != (b.lat, b.lon)
    assert route_point(0) == (51.128, 71.43) and route_point(1) == (49.806, 73.085)
    assert 0 <= b.speed_kmh <= 140


def test_config_yaml_and_env(tmp_path, monkeypatch):
    y = tmp_path / "config.yaml"
    y.write_text(
        "device:\n  serial: DG-0009\nthresholds:\n  MICROSLEEP_MS: 2500\nclip:\n  pre_s: 7\n", encoding="utf-8"
    )
    monkeypatch.setenv("DG_API_URL", "http://backend:8000/api/v1/")
    cfg = config.load(y)
    assert cfg.serial == "DG-0009" and cfg.thresholds.MICROSLEEP_MS == 2500 and cfg.clip_pre_s == 7
    assert cfg.api_url == "http://backend:8000/api/v1" and cfg.speed_limit == 90
    cfg.profile = "city"
    assert cfg.speed_limit == 60
    assert datetime.now(UTC).tzinfo is UTC


def test_odometer_accumulates_between_valid_fixes():
    from datetime import UTC, datetime

    from dg.gps import Fix, Odometer, haversine_km

    odo = Odometer()
    now = datetime.now(UTC)
    assert odo.update(Fix(None, None, None, False, now)) == 0.0
    odo.update(Fix(51.128, 71.430, 80, True, now))
    d = odo.update(Fix(51.02, 71.62, 80, True, now))
    assert abs(d - haversine_km(51.128, 71.430, 51.02, 71.62)) < 1e-9 and 17 < d < 19
    odo.update(Fix(49.8, 73.0, 80, True, now))  # скачок ~160 км — потеря фикса, не считаем
    assert abs(odo.take_delta() - d) < 1e-3 and odo.pending_km == 0.0 and odo.total_km > 0  # delta округлён до метров
