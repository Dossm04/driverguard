#!/bin/sh
# Backend в контейнере: миграции → (при пустой базе или SEED=always) демо-данные → uvicorn.
set -e
cd /srv/app

echo "[backend] alembic upgrade head"
alembic upgrade head

if [ "${SEED:-auto}" != "never" ]; then
  # Код 10 = «нужен seed». Под set -e ненулевой выход убил бы скрипт — временно выключаем.
  set +e
  python - <<'PYSEED'
import os, sys
from sqlalchemy import text
from app.db import engine
with engine.connect() as conn:
    users = conn.execute(text("SELECT COUNT(*) FROM users")).scalar() or 0
mode = os.environ.get("SEED", "auto")
if mode == "always" or (mode == "auto" and users == 0):
    print(f"[backend] seed: users={users}, режим={mode} → python -m app.seed")
    sys.exit(10)
print(f"[backend] seed: пропуск (users={users}, режим={mode})")
PYSEED
  rc=$?
  set -e
  if [ "$rc" = "10" ]; then
    python -m app.seed
  elif [ "$rc" != "0" ]; then
    echo "[backend] проверка seed завершилась с кодом $rc" >&2
    exit "$rc"
  fi
fi

exec uvicorn app.main:app --host 0.0.0.0 --port 8000
