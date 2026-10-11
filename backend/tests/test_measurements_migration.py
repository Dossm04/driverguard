"""Append-only migration keeps existing events and leaves missing readings null."""

from pathlib import Path

from alembic.config import Config
from sqlalchemy import text

from alembic import command


def test_measurements_upgrade_preserves_existing_events(seeded):
    # conftest creates a dedicated per-process test database, never the working DB.
    before = seeded.execute(
        text("SELECT uuid, type, ts, value FROM events ORDER BY uuid")
    ).all()
    assert before
    seeded.execute(text("ALTER TABLE events DROP COLUMN measurements"))
    seeded.commit()
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.stamp(config, "e5f6a7b8c9d0")
    command.upgrade(config, "f6a7b8c9d0e1")
    after = seeded.execute(
        text("SELECT uuid, type, ts, value FROM events ORDER BY uuid")
    ).all()
    assert after == before
    assert seeded.execute(
        text("SELECT count(*) FROM events WHERE measurements IS NOT NULL")
    ).scalar_one() == 0
