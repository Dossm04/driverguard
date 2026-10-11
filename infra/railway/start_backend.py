"""Cloud entrypoint: migrate, initialize an EMPTY database, then serve.

No demo events, password resets or destructive seed. Environment values are never logged.
"""

from __future__ import annotations

import os
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


def normalize_database_url(value: str) -> str:
    for prefix in ("postgresql://", "postgres://"):
        if value.startswith(prefix):
            return "postgresql+psycopg://" + value[len(prefix) :]
    if value.startswith("postgresql+psycopg://"):
        return value
    raise ValueError("DATABASE_URL must be a PostgreSQL URL")


def validate_environment(env: dict[str, str]) -> None:
    required = (
        "DATABASE_URL",
        "JWT_SECRET",
        "MINIO_ENDPOINT",
        "MINIO_ROOT_USER",
        "MINIO_ROOT_PASSWORD",
        "MINIO_BUCKET_PHOTOS",
        "MINIO_BUCKET_CLIPS",
        "CORS_ORIGINS",
    )
    for name in required:
        value = env.get(name, "").strip()
        if not value or "REPLACE_" in value or "${{" in value:
            raise ValueError(f"Configure {name} in Railway Variables")
    if len(env["JWT_SECRET"].encode()) < 32 or "change-me" in env["JWT_SECRET"]:
        raise ValueError("JWT_SECRET must contain at least 32 random bytes")
    if not env["MINIO_ENDPOINT"].startswith("https://"):
        raise ValueError("Cloud object storage must use HTTPS")
    origins = [origin.strip() for origin in env["CORS_ORIGINS"].split(",")]
    if any(not origin.startswith("https://") or "*" in origin for origin in origins):
        raise ValueError("CORS_ORIGINS must list explicit HTTPS web origins")
    if env.get("SEED", "never") != "never":
        raise ValueError("This deployment must use SEED=never to preserve real data")
    if env.get("DEMO_MODE", "false").lower() != "false":
        raise ValueError("This deployment must use DEMO_MODE=false")


def bootstrap_empty_database() -> None:
    from app.db import SessionLocal
    from app.models import Depot, User
    from app.security import hash_secret
    from sqlalchemy import select, text

    with SessionLocal() as db:
        # Protect overlapping initial deploys without adding any persistent schema object.
        db.execute(text("SELECT pg_advisory_xact_lock(73461011)"))
        if db.scalar(select(User.id).limit(1)) is not None:
            print("[deploy] Existing accounts preserved; bootstrap skipped", flush=True)
            return
        email = os.environ.get("DG_BOOTSTRAP_ADMIN_EMAIL", "").strip().lower()
        password = os.environ.get("DG_BOOTSTRAP_ADMIN_PASSWORD", "")
        if "@" not in email or len(password) < 12 or "REPLACE_" in password:
            raise ValueError(
                "Empty database: set bootstrap email and a unique 12+ character password"
            )
        db.add(
            User(
                role="admin",
                email=email,
                password_hash=hash_secret(password),
                name=os.environ.get(
                    "DG_BOOTSTRAP_ADMIN_NAME", "DriverGuard Coordinator"
                ),
                created_at=datetime.now(UTC),
            )
        )
        depot_name = os.environ.get("DG_BOOTSTRAP_DEPOT_NAME", "Astana").strip()
        if (
            depot_name
            and db.scalar(select(Depot.id).where(Depot.name == depot_name)) is None
        ):
            db.add(Depot(name=depot_name))
        db.commit()
        print(
            "[deploy] Initial administrator created; no demo events inserted",
            flush=True,
        )


def main() -> None:
    app_dir = Path(__file__).resolve().parents[1]
    os.chdir(app_dir)
    sys.path.insert(0, str(app_dir))
    validate_environment(dict(os.environ))
    os.environ["DATABASE_URL"] = normalize_database_url(os.environ["DATABASE_URL"])
    os.environ["SEED"] = "never"
    os.environ["DEMO_MODE"] = "false"
    print("[deploy] Applying database migrations", flush=True)
    subprocess.run(["alembic", "upgrade", "head"], check=True)
    bootstrap_empty_database()
    port = int(os.environ.get("PORT", "8000"))
    if not 1 <= port <= 65535:
        raise ValueError("Invalid PORT")
    os.execvp(
        sys.executable,
        [
            sys.executable,
            "-m",
            "uvicorn",
            "app.main:app",
            "--host",
            "0.0.0.0",
            "--port",
            str(port),
        ],
    )


if __name__ == "__main__":
    main()
