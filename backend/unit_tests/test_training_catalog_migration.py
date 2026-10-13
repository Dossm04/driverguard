"""The catalog migration adds reference content, never synthetic driver history."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace

import sqlalchemy as sa


def test_catalog_preserves_customization_and_is_idempotent(monkeypatch):
    path = Path(__file__).resolve().parents[1] / "alembic/versions/a8b9c0d1e2f3_training_catalog.py"
    spec = importlib.util.spec_from_file_location("catalog_migration", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = sa.create_engine("sqlite://")
    with engine.begin() as db:
        db.execute(
            sa.text(
                "CREATE TABLE trainings (id INTEGER PRIMARY KEY, "
                "title TEXT, duration_s INTEGER, url TEXT)"
            )
        )
        db.execute(
            sa.text(
                "INSERT INTO trainings (title,duration_s,url) VALUES (:title,90,'https://example.test/company')"
            ),
            {"title": migration.TITLES[0]},
        )
        monkeypatch.setattr(migration, "op", SimpleNamespace(get_bind=lambda: db))
        migration.upgrade()
        migration.upgrade()
        assert db.execute(sa.text("SELECT count(*) FROM trainings")).scalar_one() == 3
        original = db.execute(
            sa.text("SELECT duration_s,url FROM trainings WHERE title=:title"),
            {"title": migration.TITLES[0]},
        ).one()
        assert original == (90, "https://example.test/company")
        migration.downgrade()
        assert db.execute(sa.text("SELECT count(*) FROM trainings")).scalar_one() == 3
