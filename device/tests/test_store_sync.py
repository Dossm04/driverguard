"""SQLite-очередь и синхронизация с фейковым backend: накопление офлайн → доставка при сети (DEV-18/19)."""

import json
import threading
import uuid
from datetime import UTC, datetime
from http.server import BaseHTTPRequestHandler, HTTPServer

import pytest

from dg.config import Config
from dg.store import Store
from dg.sync import Sync

TOKEN = "x." + __import__("base64").urlsafe_b64encode(b'{"sub":"7","typ":"device"}').decode().rstrip("=") + ".y"


class FakeBackend(BaseHTTPRequestHandler):
    calls: list = []
    events: dict = {}
    clips: dict = {}
    thresholds_version = 3
    reboot = False
    down = False
    clip_fail = False
    last_heartbeat: dict = {}

    def log_message(self, *a):  # тихо
        pass

    def _json(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return self.rfile.read(n) if n else b""

    def do_POST(self):
        body = self._body()
        if FakeBackend.down:
            self.send_response(503)
            self.end_headers()
            return
        FakeBackend.calls.append(("POST", self.path))
        if self.path.endswith("/auth/device"):
            data = json.loads(body)
            if data["secret"] != "device-secret-1":
                return self._json(401, {"detail": "Неверный serial или секрет"})
            return self._json(200, {"access_token": TOKEN})
        if self.headers.get("Authorization") != f"Bearer {TOKEN}":
            return self._json(401, {"detail": "нет токена"})
        if self.path.endswith("/events"):
            batch = json.loads(body)
            inserted = 0
            for e in batch:
                if e["uuid"] not in FakeBackend.events:
                    FakeBackend.events[e["uuid"]] = e
                    inserted += 1
            return self._json(200, {"accepted": inserted, "duplicates": len(batch) - inserted})
        if self.path.endswith("/clip-upload-url"):
            if FakeBackend.clip_fail:
                return self._json(503, {"detail": "minio down"})
            uid = self.path.split("/")[-2]
            return self._json(
                200,
                {
                    "upload_url": f"http://{self.headers['Host']}/put/{uid}",
                    "clip_key": f"clips/DG-0001/{uid}.mp4",
                    "expires_in": 600,
                },
            )
        if "/heartbeat" in self.path:
            FakeBackend.last_heartbeat = json.loads(body)
            return self._json(200, {"status": "ok"})
        return self._json(404, {"detail": "нет"})

    def do_PUT(self):
        data = self._body()
        FakeBackend.clips[self.path.split("/")[-1]] = len(data)
        self.send_response(200)
        self.end_headers()

    def do_GET(self):
        if FakeBackend.down:
            self.send_response(503)
            self.end_headers()
            return
        if self.path.endswith("/config"):
            return self._json(
                200,
                {
                    "thresholds": {"MICROSLEEP_MS": 2000},
                    "thresholds_version": FakeBackend.thresholds_version,
                    "scoring_version": 1,
                    "reboot": FakeBackend.reboot,
                },
            )
        return self._json(404, {})


@pytest.fixture
def backend():
    FakeBackend.calls, FakeBackend.events, FakeBackend.clips = [], {}, {}
    FakeBackend.down, FakeBackend.reboot = False, False
    srv = HTTPServer(("127.0.0.1", 0), FakeBackend)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}/api/v1"
    srv.shutdown()


def make_event(**kw) -> dict:
    return {
        "uuid": str(uuid.uuid4()),
        "type": "microsleep",
        "severity": "critical",
        "ts": datetime.now(UTC).isoformat(),
        "lat": 51.1,
        "lon": 71.4,
        "gps_valid": True,
        "speed_kmh": 84,
        "confidence": 0.93,
        "value": 1.7,
        "context": {"note": "тест"},
        **kw,
    }


def test_store_queue_and_idempotent_insert(tmp_path):
    store = Store(tmp_path / "dg.sqlite")
    e = make_event()
    store.add_event(e)
    store.add_event(e)  # повтор не дублирует
    assert store.counts() == {"events": 1, "pending": 1, "clips_pending": 0}
    assert store.pending_events()[0]["context"] == {"note": "тест"}
    store.mark_sent([e["uuid"]])
    assert store.counts()["pending"] == 0
    store.set_config("thresholds_version", 5)
    assert store.get_config("thresholds_version") == 5
    store.add_heartbeat({"fps": 29})
    assert store.pending_heartbeats()[0]["payload"] == {"fps": 29}


def test_offline_accumulates_then_delivers(tmp_path, backend):
    cfg = Config(api_url=backend, backoff_min_s=1, backoff_max_s=4, db_path=str(tmp_path / "dg.sqlite"))
    store = Store(cfg.db_path)
    got_thresholds = {}
    sync = Sync(cfg, store, on_thresholds=got_thresholds.update)

    FakeBackend.down = True  # авиарежим
    for _ in range(3):
        store.add_event(make_event())
    assert sync.cycle() is False and sync.online is False
    assert store.counts()["pending"] == 3
    assert sync.last_error and sync.backoff_s == 1

    FakeBackend.down = False  # сеть появилась
    assert sync.cycle() is True and sync.online
    assert store.counts()["pending"] == 0 and len(FakeBackend.events) == 3
    assert FakeBackend.events[next(iter(FakeBackend.events))]["device_serial"] == "DG-0001"
    assert got_thresholds == {"MICROSLEEP_MS": 2000} and store.get_config("thresholds_version") == 3
    # повторный цикл: ничего нового, пороги не переприменяются
    got_thresholds.clear()
    sync.cycle()
    assert got_thresholds == {} and sync.stats["events_sent"] == 3


def test_clip_upload_and_heartbeat_and_reboot(tmp_path, backend):
    cfg = Config(api_url=backend, db_path=str(tmp_path / "dg.sqlite"))
    store = Store(cfg.db_path)
    rebooted = []
    sync = Sync(cfg, store, on_reboot=lambda: rebooted.append(True))
    e = make_event()
    clip = tmp_path / f"{e['uuid']}.mp4"
    clip.write_bytes(b"\x00" * 1024)
    store.add_event({**e, "clip_path": str(clip)})
    store.add_heartbeat({"fps": 28.5, "temp_c": 51.0})
    FakeBackend.reboot = True
    assert sync.cycle()
    assert FakeBackend.clips[e["uuid"]] == 1024
    assert store.pending_clips() == [] and store.recent_events()[0]["clip_key"].endswith(f"{e['uuid']}.mp4")
    assert sync.stats["heartbeats_sent"] == 1 and rebooted == [True]
    assert ("POST", "/api/v1/devices/7/heartbeat") in FakeBackend.calls


def test_bad_secret_reports_error(tmp_path, backend):
    cfg = Config(api_url=backend, secret="wrong", db_path=str(tmp_path / "dg.sqlite"))
    sync = Sync(cfg, Store(cfg.db_path))
    assert sync.cycle() is False and "401" in sync.last_error


def test_failed_clip_does_not_block_heartbeat_and_gives_up(tmp_path, backend):
    cfg = Config(api_url=backend, db_path=str(tmp_path / "dg.sqlite"))
    store = Store(cfg.db_path)
    sync = Sync(cfg, store)
    e = make_event()
    clip = tmp_path / f"{e['uuid']}.mp4"
    clip.write_bytes(b"\x00" * 10)
    store.add_event({**e, "clip_path": str(clip)})
    store.add_heartbeat({"fps": 25})
    FakeBackend.clip_fail = True
    try:
        for _ in range(5):
            assert sync.cycle() is True  # heartbeat и конфиг проходят, клип копит попытки
        assert sync.stats["heartbeats_sent"] == 1 and store.pending_clips() == []  # после 5 попыток — отказ
    finally:
        FakeBackend.clip_fail = False


def test_heartbeat_sends_device_time(tmp_path, backend):
    cfg = Config(api_url=backend, db_path=str(tmp_path / "dg.sqlite"))
    store = Store(cfg.db_path)
    store.add_heartbeat({"fps": 25, "trip_km_delta": 1.5})
    assert Sync(cfg, store).cycle()
    assert "ts" in FakeBackend.last_heartbeat and FakeBackend.last_heartbeat["trip_km_delta"] == 1.5


def test_heartbeat_trim_keeps_unsent(tmp_path):
    store = Store(tmp_path / "dg.sqlite")
    for i in range(600):
        store.add_heartbeat({"i": i})
    assert len(store.pending_heartbeats(limit=1000)) == 600  # неотправленные не удаляются
