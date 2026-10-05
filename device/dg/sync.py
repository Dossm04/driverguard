"""Синхронизация с backend (DEV-19): device-токен, батчи ≤100 событий, presigned-клипы,
heartbeat, конфиг с порогами и командой reboot; экспоненциальный retry 30 с → 10 мин."""

from __future__ import annotations

import base64
import json
import logging
import threading
from collections.abc import Callable
from pathlib import Path

import requests

from dg.config import Config
from dg.store import Store

log = logging.getLogger("dg.sync")
MAX_CLIP_ATTEMPTS = 5


class Sync:
    def __init__(
        self,
        cfg: Config,
        store: Store,
        session: requests.Session | None = None,
        on_thresholds: Callable[[dict], None] | None = None,
        on_reboot: Callable[[], None] | None = None,
    ):
        self.cfg = cfg
        self.store = store
        self.http = session or requests.Session()
        self.token: str | None = None
        self.device_id: int | None = None
        self.online = False
        self.last_error = ""
        self.backoff_s = cfg.backoff_min_s
        self.on_thresholds = on_thresholds
        self.on_reboot = on_reboot
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self.stats = {"events_sent": 0, "clips_sent": 0, "heartbeats_sent": 0, "cycles": 0}

    # ── auth ──
    def login(self) -> bool:
        resp = self.http.post(
            f"{self.cfg.api_url}/auth/device",
            json={"serial": self.cfg.serial, "secret": self.cfg.secret},
            timeout=10,
        )
        if resp.status_code != 200:
            raise RuntimeError(f"auth/device {resp.status_code}: {resp.text[:120]}")
        self.token = resp.json()["access_token"]
        payload = self.token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        self.device_id = int(json.loads(base64.urlsafe_b64decode(payload))["sub"])
        return True

    def _headers(self) -> dict:
        if not self.token:
            self.login()
        return {"Authorization": f"Bearer {self.token}"}

    def _request(self, method: str, path: str, **kw) -> requests.Response:
        resp = self.http.request(method, f"{self.cfg.api_url}{path}", headers=self._headers(), timeout=15, **kw)
        if resp.status_code == 401:  # токен отозван/протух — перелогин и один повтор
            self.token = None
            resp = self.http.request(method, f"{self.cfg.api_url}{path}", headers=self._headers(), timeout=15, **kw)
        return resp

    # ── шаги синхронизации ──
    def push_events(self) -> int:
        pending = self.store.pending_events(self.cfg.sync_batch)
        if not pending:
            return 0
        batch = [
            {
                "uuid": e["uuid"],
                "device_serial": self.cfg.serial,
                "type": e["type"],
                "severity": e["severity"],
                "confidence": e["confidence"],
                "ts": e["ts"],
                "lat": e["lat"],
                "lon": e["lon"],
                "gps_valid": e["gps_valid"],
                "speed_kmh": e["speed_kmh"],
                "speed_source": e.get("speed_source"),
                "value": e["value"],
                "context": e["context"] or None,
                "clip": {
                    "available": bool(e.get("clip_path")),
                    "duration_s": self.cfg.clip_pre_s + self.cfg.clip_post_s,
                },
                "fw_version": self.cfg.fw_version,
                "model_version": self.cfg.model_version,
            }
            for e in pending
        ]
        resp = self._request("POST", "/events", json=batch)
        uuids = [e["uuid"] for e in pending]
        if resp.status_code != 200:
            self.store.bump_attempts(uuids)
            raise RuntimeError(f"POST /events {resp.status_code}: {resp.text[:120]}")
        self.store.mark_sent(uuids)  # upsert по uuid идемпотентен — дубликаты backend отбрасывает
        self.stats["events_sent"] += len(uuids)
        return len(uuids)

    def upload_clips(self) -> int:
        """Клипы — по одному: ошибка одного не блокирует heartbeat/конфиг; после
        MAX_CLIP_ATTEMPTS неудач клип исключается (само событие уже доставлено)."""
        sent = 0
        for e in self.store.pending_clips():
            path = Path(e["clip_path"])
            if not path.is_file():
                continue  # клип ещё пишется или удалён — попробуем позже
            try:
                resp = self._request("POST", f"/events/{e['uuid']}/clip-upload-url")
                if resp.status_code != 200:
                    raise RuntimeError(f"clip-upload-url {resp.status_code}: {resp.text[:120]}")
                info = resp.json()
                put = self.http.put(
                    info["upload_url"],
                    data=path.read_bytes(),
                    headers={"Content-Type": "video/mp4"},
                    timeout=60,
                )
                if put.status_code not in (200, 201, 204):
                    raise RuntimeError(f"PUT clip {put.status_code}")
            except (requests.RequestException, RuntimeError, OSError) as exc:
                attempts = self.store.bump_clip_attempts(e["uuid"])
                if attempts >= MAX_CLIP_ATTEMPTS:
                    log.error("Клип %s не загружен после %d попыток — пропускаем: %s", e["uuid"], attempts, exc)
                    self.store.give_up_clip(e["uuid"])
                else:
                    log.warning("Клип %s не загружен (попытка %d): %s", e["uuid"], attempts, exc)
                continue
            self.store.mark_clip_sent(e["uuid"], info["clip_key"])
            sent += 1
        self.stats["clips_sent"] += sent
        return sent

    def push_heartbeats(self) -> int:
        if self.device_id is None:
            self._headers()
        pending = self.store.pending_heartbeats()
        for hb in pending:
            payload = {"ts": hb["ts"], **hb["payload"]}  # время измерения, не доставки
            resp = self._request("POST", f"/devices/{self.device_id}/heartbeat", json=payload)
            if resp.status_code != 200:
                raise RuntimeError(f"heartbeat {resp.status_code}: {resp.text[:120]}")
            self.store.mark_heartbeats_sent([hb["id"]])
            self.stats["heartbeats_sent"] += 1
        return len(pending)

    def pull_config(self) -> dict:
        if self.device_id is None:
            self._headers()
        resp = self._request("GET", f"/devices/{self.device_id}/config")
        if resp.status_code != 200:
            raise RuntimeError(f"config {resp.status_code}")
        data = resp.json()
        version = data.get("thresholds_version", 0)
        if version != self.store.get_config("thresholds_version", -1):
            self.store.set_config("thresholds", data.get("thresholds", {}))
            self.store.set_config("thresholds_version", version)
            if self.on_thresholds:
                self.on_thresholds(data.get("thresholds", {}))
            log.info("Пороги обновлены с backend: версия %s", version)
        if data.get("reboot") and self.on_reboot:
            log.warning("Backend запросил перезагрузку устройства")
            self.on_reboot()
        return data

    def cycle(self) -> bool:
        """Один цикл: события → клипы → heartbeat → конфиг. True — сеть есть, всё ушло."""
        self.stats["cycles"] += 1
        try:
            self.push_events()
            self.upload_clips()
            self.push_heartbeats()
            self.pull_config()
        except (requests.RequestException, RuntimeError, OSError) as exc:
            self.online = False
            self.last_error = str(exc)[:200]
            log.warning("Синхронизация не удалась (%s); повтор через %d с", self.last_error, self.backoff_s)
            return False
        self.online = True
        self.last_error = ""
        self.backoff_s = self.cfg.backoff_min_s
        return True

    # ── фоновый поток ──
    def start(self) -> None:
        self._thread = threading.Thread(target=self._loop, name="dg-sync", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None and self._thread.is_alive():
            self._thread.join(timeout=30)

    def _loop(self) -> None:
        while not self._stop.is_set():
            ok = self.cycle()
            if ok:
                wait = self.cfg.sync_check_s
            else:
                wait = self.backoff_s
                self.backoff_s = min(self.backoff_s * 2, self.cfg.backoff_max_s)
            self._stop.wait(wait)
