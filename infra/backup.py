"""Резервные копии демо-стека (PRODUCTION_STANDARDS 10): PostgreSQL + MinIO из docker compose.

  python infra/backup.py create            # backups/<дата>/db.dump + minio.tar.gz (+ проверка дампа)
  python infra/backup.py list              # что есть в backups/
  python infra/backup.py verify <папка>    # дамп читается pg_restore --list, архив — tar -t
  python infra/backup.py restore <папка>   # ОСТАНОВИТ backend, зальёт БД и фото, поднимет снова

Работает на Windows/macOS/Linux: всё делается внутри контейнеров (pg_dump/pg_restore из образа
postgres, tar — из alpine поверх volume MinIO), на хосте нужен только Docker.
Восстановление затирает текущие данные — скрипт спрашивает подтверждение (--yes, чтобы не спрашивать).
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / "infra" / ".env"
BACKUPS = ROOT / "backups"
COMPOSE = ["docker", "compose", "-f", str(ROOT / "infra" / "docker-compose.yml")]
PROJECT = "driverguard"  # name: в docker-compose.yml → volume driverguard_miniodata


def env_values() -> dict[str, str]:
    values = {"POSTGRES_USER": "driverguard", "POSTGRES_DB": "driverguard"}
    if ENV_PATH.exists():
        for line in ENV_PATH.read_text(encoding="utf-8").splitlines():
            if "=" in line and not line.lstrip().startswith("#"):
                key, value = line.split("=", 1)
                if key.strip() in values and value.strip():
                    values[key.strip()] = value.split("#", 1)[0].strip()
    return values


def run(cmd: list[str], **kw) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, check=True, **kw)


def volume_name() -> str:
    return f"{PROJECT}_miniodata"


def cmd_create(args: argparse.Namespace) -> int:
    env = env_values()
    target = BACKUPS / datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    target.mkdir(parents=True, exist_ok=True)

    db_dump = target / "db.dump"
    print(f"PostgreSQL → {db_dump}")
    with db_dump.open("wb") as fh:
        run(
            [*COMPOSE, "exec", "-T", "db", "pg_dump", "-U", env["POSTGRES_USER"], "-Fc", env["POSTGRES_DB"]],
            stdout=fh,
        )

    minio_tar = target / "minio.tar.gz"
    print(f"MinIO (фото чек-листов, клипы) → {minio_tar}")
    with minio_tar.open("wb") as fh:
        run(
            ["docker", "run", "--rm", "-v", f"{volume_name()}:/data:ro", "alpine",
             "tar", "-czf", "-", "-C", "/data", "."],
            stdout=fh,
        )

    ok = verify(target)
    print(f"Готово: {target} — {'дамп и архив проверены' if ok else 'ПРОВЕРКА НЕ ПРОШЛА'}")
    if args.keep and args.keep > 0:
        prune(args.keep)
    return 0 if ok else 1


def verify(folder: Path) -> bool:
    db_dump, minio_tar = folder / "db.dump", folder / "minio.tar.gz"
    ok = True
    if db_dump.exists() and db_dump.stat().st_size > 0:
        with db_dump.open("rb") as fh:
            res = subprocess.run(
                [*COMPOSE, "exec", "-T", "db", "pg_restore", "--list"],
                stdin=fh, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
            )
        tables = sum(1 for line in res.stdout.decode(errors="replace").splitlines() if " TABLE DATA " in line)
        print(f"  db.dump: {db_dump.stat().st_size // 1024} КБ, таблиц с данными: {tables}", end="")
        if res.returncode != 0 or tables == 0:
            ok = False
            print(" — ОШИБКА:", res.stderr.decode(errors="replace").strip()[:300])
        else:
            print(" — ok")
    else:
        ok = False
        print("  db.dump отсутствует или пустой")
    if minio_tar.exists():
        res = subprocess.run(
            ["docker", "run", "--rm", "-i", "alpine", "tar", "-tzf", "-"],
            stdin=minio_tar.open("rb"), stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
        files = [ln for ln in res.stdout.decode(errors="replace").splitlines() if not ln.endswith("/")]
        print(f"  minio.tar.gz: {minio_tar.stat().st_size // 1024} КБ, файлов: {len(files)}", end="")
        if res.returncode != 0:
            ok = False
            print(" — ОШИБКА:", res.stderr.decode(errors="replace").strip()[:300])
        else:
            print(" — ok")
    else:
        ok = False
        print("  minio.tar.gz отсутствует")
    return ok


def cmd_verify(args: argparse.Namespace) -> int:
    return 0 if verify(Path(args.folder)) else 1


def cmd_list(_: argparse.Namespace) -> int:
    if not BACKUPS.exists():
        print("Копий ещё нет: python infra/backup.py create")
        return 0
    for folder in sorted(BACKUPS.iterdir()):
        if folder.is_dir():
            size = sum(f.stat().st_size for f in folder.iterdir() if f.is_file()) // 1024
            print(f"  {folder.name}  {size} КБ  {[f.name for f in sorted(folder.iterdir())]}")
    return 0


def prune(keep: int) -> None:
    folders = sorted(f for f in BACKUPS.iterdir() if f.is_dir())
    for old in folders[:-keep]:
        for f in old.iterdir():
            f.unlink()
        old.rmdir()
        print(f"  удалена старая копия {old.name}")


def cmd_restore(args: argparse.Namespace) -> int:
    folder = Path(args.folder)
    if not (folder / "db.dump").exists():
        print(f"Нет {folder / 'db.dump'}", file=sys.stderr)
        return 2
    if not args.yes:
        answer = input(f"Заменить ТЕКУЩИЕ данные копией {folder.name}? Введите yes: ")
        if answer.strip().lower() != "yes":
            print("Отменено")
            return 1
    env = env_values()
    # backend в compose есть только в профиле full (make demo); в dev-режиме он запущен на хосте
    has_backend = bool(
        subprocess.run(
            [*COMPOSE, "--profile", "full", "ps", "-q", "backend"], capture_output=True, text=True
        ).stdout.strip()
    )
    print("Останавливаю backend, бота и симулятор (чтобы не писали в базу во время восстановления)…")
    subprocess.run([*COMPOSE, "--profile", "full", "stop", "backend", "bot", "device-sim"], check=False)

    print("PostgreSQL ← db.dump")
    with (folder / "db.dump").open("rb") as fh:
        run(
            [*COMPOSE, "exec", "-T", "db", "pg_restore", "-U", env["POSTGRES_USER"], "-d", env["POSTGRES_DB"],
             "--clean", "--if-exists", "--no-owner", "--single-transaction"],
            stdin=fh,
        )
    minio_tar = folder / "minio.tar.gz"
    if minio_tar.exists():
        print("MinIO ← minio.tar.gz (MinIO на время восстановления останавливается)")
        subprocess.run([*COMPOSE, "stop", "minio"], check=False)
        with minio_tar.open("rb") as fh:
            run(
                ["docker", "run", "--rm", "-i", "-v", f"{volume_name()}:/data", "alpine",
                 "sh", "-c", "find /data -mindepth 1 -delete && tar -xzf - -C /data"],
                stdin=fh,
            )
        run([*COMPOSE, "up", "-d", "minio"])
    if not has_backend:
        print(
            "Готово: данные восстановлены. Backend в compose не запущен (dev-режим) — "
            "перезапустите свой backend, чтобы он переподключился к базе."
        )
        return 0
    print("Поднимаю backend…")
    subprocess.run([*COMPOSE, "--profile", "full", "up", "-d", "backend"], check=False)
    for _ in range(60):
        res = subprocess.run(
            [*COMPOSE, "exec", "-T", "backend", "python", "-c",
             "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8000/api/v1/health/ready',timeout=3)"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        if res.returncode == 0:
            print("Готово: backend отвечает, данные восстановлены")
            return 0
        time.sleep(2)
    print("backend не ответил за 2 минуты — смотрите `make demo-logs`", file=sys.stderr)
    return 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Резервные копии PostgreSQL + MinIO (docker compose)")
    sub = parser.add_subparsers(dest="cmd", required=True)
    c = sub.add_parser("create", help="снять копию и проверить её")
    c.add_argument("--keep", type=int, default=0, help="оставить только N последних копий")
    c.set_defaults(fn=cmd_create)
    sub.add_parser("list", help="список копий").set_defaults(fn=cmd_list)
    v = sub.add_parser("verify", help="проверить копию")
    v.add_argument("folder")
    v.set_defaults(fn=cmd_verify)
    r = sub.add_parser("restore", help="восстановить из копии (затирает текущие данные)")
    r.add_argument("folder")
    r.add_argument("--yes", action="store_true")
    r.set_defaults(fn=cmd_restore)
    args = parser.parse_args(argv)
    try:
        return args.fn(args)
    except subprocess.CalledProcessError as exc:
        print(f"Команда завершилась с ошибкой ({exc.returncode}): {' '.join(map(str, exc.cmd))}", file=sys.stderr)
        return exc.returncode
    except FileNotFoundError as exc:
        print(f"Не найден docker: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
