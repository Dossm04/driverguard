"""Deployment safeguards without contacting databases or hosting services."""

import importlib.util
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock
from urllib.parse import urlsplit

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(name):
    spec = importlib.util.spec_from_file_location(name, ROOT / "railway" / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


START = load("start_backend")
CHECK = load("check_deployment")


@pytest.mark.parametrize(
    "prefix", ["postgres://", "postgresql://", "postgresql+psycopg://"]
)
def test_railway_database_url_uses_installed_psycopg_driver(prefix):
    suffix = "user:p%40ss@postgres.railway.internal:5432/railway?sslmode=require"
    assert (
        START.normalize_database_url(prefix + suffix)
        == "postgresql+psycopg://" + suffix
    )


def valid_env():
    return {
        "DATABASE_URL": "postgresql://user:pass@postgres:5432/db",
        "JWT_SECRET": "1" * 64,
        "MINIO_ENDPOINT": "https://storage.example.test",
        "MINIO_ROOT_USER": "access",
        "MINIO_ROOT_PASSWORD": "private",
        "MINIO_BUCKET_PHOTOS": "media-id",
        "MINIO_BUCKET_CLIPS": "media-id",
        "CORS_ORIGINS": "https://driverguard.example.test",
        "SEED": "never",
        "DEMO_MODE": "false",
    }


def test_cloud_environment_accepts_explicit_settings():
    START.validate_environment(valid_env())


@pytest.mark.parametrize(
    "key,value",
    [
        ("JWT_SECRET", "weak"),
        ("MINIO_ENDPOINT", "http://storage.test"),
        ("CORS_ORIGINS", "*"),
        ("SEED", "always"),
        ("DEMO_MODE", "true"),
        ("MINIO_ROOT_PASSWORD", "${{Media.SECRET_ACCESS_KEY}}"),
        ("CORS_ORIGINS", "https://REPLACE_WEB_DOMAIN.up.railway.app"),
    ],
)
def test_cloud_start_rejects_incomplete_or_destructive_settings(key, value):
    env = valid_env()
    env[key] = value
    with pytest.raises(ValueError):
        START.validate_environment(env)


@pytest.mark.parametrize(
    "address",
    [
        "http://external.test",
        "https://user:password@host.test",
        "https://host.test?token=secret",
        "https://host.test/other",
        "file:///etc/passwd",
    ],
)
def test_health_check_rejects_unsafe_or_ambiguous_addresses(address):
    with pytest.raises(ValueError):
        CHECK.origin(address)


def test_health_check_accepts_phone_api_address():
    assert (
        CHECK.origin("https://api.example.test/api/v1/") == "https://api.example.test"
    )


def test_health_check_fails_if_login_route_is_public_driver_data(monkeypatch):
    replies = iter(
        [
            (200, b'{"service":"driverguard-backend"}'),
            (200, b'{"status":"ready","db":"ok","storage":"ok"}'),
            (200, b"[]"),
            (200, b"DriverGuard"),
            (200, b"DriverGuard"),
        ]
    )
    monkeypatch.setattr(CHECK, "get", lambda url: next(replies))
    results = dict(CHECK.check("https://api.test", "https://web.test"))
    assert results["Database and object storage"]
    assert not results["Driver directory requires authentication"]


@pytest.mark.parametrize("virtual", [False, True])
def test_s3_style_applies_to_upload_signing_and_health(monkeypatch, virtual):
    # Imported only inside this test: the rest of this file needs no backend packages.
    monkeypatch.syspath_prepend(str(ROOT.parent / "backend"))
    monkeypatch.setenv("JWT_SECRET", "test-only-" + "x" * 64)
    from app import storage

    settings = SimpleNamespace(
        minio_endpoint="https://s3.example.test",
        minio_public_endpoint="",
        minio_root_user="access",
        minio_root_password="secret",
        minio_region="auto",
        minio_virtual_host_style=virtual,
        minio_bucket_photos="media",
    )
    created = []

    def factory(*args, **kwargs):
        client = MagicMock()
        client.bucket_exists.return_value = True
        created.append(client)
        return client

    monkeypatch.setattr(storage, "get_settings", lambda: settings)
    monkeypatch.setattr(storage, "Minio", factory)
    storage._client.cache_clear()
    try:
        storage._client(False)
        storage._client(True)
        storage.ping()
        assert len(created) == 3
        assert all(
            c.enable_virtual_style_endpoint.call_count == int(virtual) for c in created
        )
    finally:
        storage._client.cache_clear()


@pytest.mark.parametrize(
    "virtual,expected_host,expected_path",
    [
        (False, "s3.example.test", "/media/checklists/photo.jpg"),
        (True, "media.s3.example.test", "/checklists/photo.jpg"),
    ],
)
def test_real_presigned_url_matches_hosting_bucket_style(
    monkeypatch, virtual, expected_host, expected_path
):
    monkeypatch.syspath_prepend(str(ROOT.parent / "backend"))
    monkeypatch.setenv("JWT_SECRET", "test-only-" + "x" * 64)
    from app import storage

    settings = SimpleNamespace(
        minio_endpoint="https://s3.example.test",
        minio_public_endpoint="",
        minio_root_user="test-access",
        minio_root_password="test-secret",
        minio_region="auto",
        minio_virtual_host_style=virtual,
        minio_bucket_photos="media",
    )
    monkeypatch.setattr(storage, "get_settings", lambda: settings)
    storage._client.cache_clear()
    try:
        signed = urlsplit(
            storage._client(True).presigned_get_object("media", "checklists/photo.jpg")
        )
        assert signed.hostname == expected_host
        assert signed.path == expected_path
        assert "X-Amz-Signature=" in signed.query
    finally:
        storage._client.cache_clear()


def test_bootstrap_preserves_existing_accounts_and_passwords(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT.parent / "backend"))
    monkeypatch.setenv("JWT_SECRET", "test-only-" + "x" * 64)
    from app import db as app_db

    session = MagicMock()
    session.scalar.return_value = 17
    manager = MagicMock()
    manager.__enter__.return_value = session
    monkeypatch.setattr(app_db, "SessionLocal", lambda: manager)
    # Existing databases start without a bootstrap password, and must not be reset.
    monkeypatch.delenv("DG_BOOTSTRAP_ADMIN_PASSWORD", raising=False)
    START.bootstrap_empty_database()
    session.add.assert_not_called()
    session.commit.assert_not_called()


def test_bootstrap_creates_only_admin_and_depot_on_empty_database(monkeypatch):
    monkeypatch.syspath_prepend(str(ROOT.parent / "backend"))
    monkeypatch.setenv("JWT_SECRET", "test-only-" + "x" * 64)
    monkeypatch.setenv("DG_BOOTSTRAP_ADMIN_EMAIL", "owner@example.test")
    monkeypatch.setenv("DG_BOOTSTRAP_ADMIN_PASSWORD", "test-only-bootstrap-password")
    monkeypatch.setenv("DG_BOOTSTRAP_DEPOT_NAME", "Astana")
    from app import db as app_db
    from app import security

    session = MagicMock()
    session.scalar.return_value = None
    manager = MagicMock()
    manager.__enter__.return_value = session
    monkeypatch.setattr(app_db, "SessionLocal", lambda: manager)
    monkeypatch.setattr(security, "hash_secret", lambda secret: "hashed-test-value")
    START.bootstrap_empty_database()
    added = [call.args[0] for call in session.add.call_args_list]
    assert [type(item).__name__ for item in added] == ["User", "Depot"]
    assert added[0].role == "admin"
    assert added[0].password_hash == "hashed-test-value"
    session.commit.assert_called_once()
