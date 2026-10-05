"""Локальное хранилище (DEV-18): SQLite — события, heartbeats, конфиг; клипы — файлы + очередь."""

from __future__ import annotations

import json
import sqlite3
import threading
from datetime import UTC, datetime
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS events (
    uuid TEXT PRIMARY KEY,
    type TEXT NOT NULL,
    severity TEXT NOT NULL,
    ts TEXT NOT NULL,
    lat REAL, lon REAL, gps_valid INTEGER NOT NULL DEFAULT 0,
    speed_kmh REAL, speed_source TEXT,
    confidence REAL NOT NULL,
    value REAL,
    context TEXT,
    clip_path TEXT, clip_key TEXT,
    status_sent INTEGER NOT NULL DEFAULT 0,
    clip_sent INTEGER NOT NULL DEFAULT 0,
    attempts INTEGER NOT NULL DEFAULT 0,
    clip_attempts INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_events_pending ON events(status_sent, ts);
CREATE TABLE IF NOT EXISTS heartbeats (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    ts TEXT NOT NULL,
    payload TEXT NOT NULL,
    sent INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS config (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""


class Store:
    def __init__(self, path: str | Path = "dg.sqlite"):
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False, isolation_level=None)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._conn.executescript(SCHEMA)
        cols = {r[1] for r in self._conn.execute("PRAGMA table_info(events)").fetchall()}
        if "clip_attempts" not in cols:  # база от прошлой версии
            self._conn.execute("ALTER TABLE events ADD COLUMN clip_attempts INTEGER NOT NULL DEFAULT 0")

    def close(self) -> None:
        self._conn.close()

    # ── события ──
    def add_event(self, event: dict) -> None:
        """event: uuid, type, severity, ts (ISO), lat, lon, gps_valid, speed_kmh, confidence, value, context."""
        with self._lock:
            self._conn.execute(
                """INSERT OR IGNORE INTO events
                   (uuid, type, severity, ts, lat, lon, gps_valid, speed_kmh, speed_source, confidence,
                    value, context, clip_path, created_at)
                   VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (
                    event["uuid"],
                    event["type"],
                    event["severity"],
                    event["ts"],
                    event.get("lat"),
                    event.get("lon"),
                    int(bool(event.get("gps_valid"))),
                    event.get("speed_kmh"),
                    event.get("speed_source"),
                    float(event["confidence"]),
                    event.get("value"),
                    json.dumps(event.get("context") or {}, ensure_ascii=False),
                    event.get("clip_path"),
                    datetime.now(UTC).isoformat(),
                ),
            )

    def set_clip_path(self, uuid: str, path: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE events SET clip_path=? WHERE uuid=?", (path, uuid))

    def pending_events(self, limit: int = 100) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM events WHERE status_sent=0 ORDER BY ts LIMIT ?", (limit,)
            ).fetchall()
        return [self._row(r) for r in rows]

    def mark_sent(self, uuids: list[str]) -> None:
        if not uuids:
            return
        with self._lock:
            self._conn.executemany("UPDATE events SET status_sent=1 WHERE uuid=?", [(u,) for u in uuids])

    def bump_attempts(self, uuids: list[str]) -> None:
        with self._lock:
            self._conn.executemany("UPDATE events SET attempts=attempts+1 WHERE uuid=?", [(u,) for u in uuids])

    def pending_clips(self, limit: int = 10) -> list[dict]:
        """Отправленные события, у которых есть файл клипа, ещё не загруженный."""
        with self._lock:
            rows = self._conn.execute(
                """SELECT * FROM events WHERE status_sent=1 AND clip_sent=0 AND clip_path IS NOT NULL
                   ORDER BY ts LIMIT ?""",
                (limit,),
            ).fetchall()
        return [self._row(r) for r in rows]

    def bump_clip_attempts(self, uuid: str) -> int:
        with self._lock:
            self._conn.execute("UPDATE events SET clip_attempts=clip_attempts+1 WHERE uuid=?", (uuid,))
            row = self._conn.execute("SELECT clip_attempts FROM events WHERE uuid=?", (uuid,)).fetchone()
        return int(row[0]) if row else 0

    def give_up_clip(self, uuid: str) -> None:
        """Клип больше не отправляем (файл остаётся на устройстве для ручного разбора)."""
        with self._lock:
            self._conn.execute("UPDATE events SET clip_sent=-1 WHERE uuid=?", (uuid,))

    def mark_clip_sent(self, uuid: str, clip_key: str) -> None:
        with self._lock:
            self._conn.execute("UPDATE events SET clip_sent=1, clip_key=? WHERE uuid=?", (clip_key, uuid))

    def counts(self) -> dict:
        with self._lock:
            total = self._conn.execute("SELECT COUNT(*) FROM events").fetchone()[0]
            pending = self._conn.execute("SELECT COUNT(*) FROM events WHERE status_sent=0").fetchone()[0]
            clips = self._conn.execute(
                "SELECT COUNT(*) FROM events WHERE clip_path IS NOT NULL AND clip_sent=0"
            ).fetchone()[0]
        return {"events": total, "pending": pending, "clips_pending": clips}

    def recent_events(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM events ORDER BY ts DESC LIMIT ?", (limit,)).fetchall()
        return [self._row(r) for r in rows]

    # ── heartbeats ──
    def add_heartbeat(self, payload: dict) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO heartbeats (ts, payload) VALUES (?, ?)",
                (datetime.now(UTC).isoformat(), json.dumps(payload, ensure_ascii=False)),
            )
            # держим только последние 500 ОТПРАВЛЕННЫХ — неотправленные (офлайн) не теряем
            self._conn.execute(
                "DELETE FROM heartbeats WHERE sent=1 AND id NOT IN "
                "(SELECT id FROM heartbeats ORDER BY id DESC LIMIT 500)"
            )

    def pending_heartbeats(self, limit: int = 20) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT id, ts, payload FROM heartbeats WHERE sent=0 ORDER BY id LIMIT ?", (limit,)
            ).fetchall()
        return [{"id": r["id"], "ts": r["ts"], "payload": json.loads(r["payload"])} for r in rows]

    def mark_heartbeats_sent(self, ids: list[int]) -> None:
        with self._lock:
            self._conn.executemany("UPDATE heartbeats SET sent=1 WHERE id=?", [(i,) for i in ids])

    # ── конфиг ──
    def get_config(self, key: str, default=None):
        with self._lock:
            row = self._conn.execute("SELECT value FROM config WHERE key=?", (key,)).fetchone()
        return json.loads(row["value"]) if row else default

    def set_config(self, key: str, value) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO config (key, value) VALUES (?, ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                (key, json.dumps(value, ensure_ascii=False)),
            )

    @staticmethod
    def _row(r: sqlite3.Row) -> dict:
        d = dict(r)
        d["gps_valid"] = bool(d["gps_valid"])
        d["context"] = json.loads(d["context"]) if d.get("context") else {}
        return d
