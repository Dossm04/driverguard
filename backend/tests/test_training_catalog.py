"""Run the catalog migration against PostgreSQL, including parameter inference."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import sqlalchemy as sa


def test_catalog_migration_on_postgresql(db, monkeypatch):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/a8b9c0d1e2f3_training_catalog.py"
    spec = importlib.util.spec_from_file_location("pg_catalog_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    db.execute(
        sa.text("INSERT INTO trainings (title, duration_s, url) VALUES (:title, 90, :url)"),
        {"title": migration.TITLES[0], "url": "https://example.test/custom"},
    )
    monkeypatch.setattr(migration, "op", SimpleNamespace(get_bind=lambda: db.connection()))
    migration.upgrade()
    migration.upgrade()
    assert db.execute(sa.text("SELECT count(*) FROM trainings")).scalar_one() == 3
    original = db.execute(
        sa.text("SELECT duration_s, url FROM trainings WHERE title=:title"),
        {"title": migration.TITLES[0]},
    ).one()
    assert original == (90, "https://example.test/custom")
    assert db.execute(sa.text("SELECT count(*) FROM driver_trainings")).scalar_one() == 0
