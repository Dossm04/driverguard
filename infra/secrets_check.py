"""Проверка infra/.env перед стендом: слабые секреты и пароли по умолчанию.

  python infra/secrets_check.py          # только показать
  python infra/secrets_check.py --fix    # заменить слабые JWT_SECRET / MINIO_ROOT_PASSWORD /
                                         # DG_SECRET случайными (ADMIN_PASSWORD/DRIVER_PIN — только подсказка)

Вызывается из `make demo` (с --fix). Пароли учёток (ADMIN_PASSWORD, DRIVER_PIN) в .env влияют
только на seed пустой базы, поэтому их скрипт не трогает — печатает, что сделать.
Смена MINIO_ROOT_PASSWORD на уже запущенном стеке безопасна: MinIO берёт root-креды из окружения
при каждом старте, backend получает те же переменные из compose.
"""

from __future__ import annotations

import argparse
import secrets
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / "infra" / ".env"

WEAK = {
    "JWT_SECRET": lambda v: len(v.encode()) < 32 or "change-me" in v,
    "MINIO_ROOT_PASSWORD": lambda v: v in ("", "minioadmin") or len(v) < 12,
    "DG_SECRET": lambda v: v.startswith("device-secret-") or len(v) < 12,
}
GENERATE = {
    "JWT_SECRET": lambda: secrets.token_hex(32),
    "MINIO_ROOT_PASSWORD": lambda: secrets.token_urlsafe(18),
    "DG_SECRET": lambda: secrets.token_urlsafe(18),
}
HINTS = {
    "ADMIN_PASSWORD": "пароль admin@driverguard.kz (пусто = admin123): задайте до первого seed "
    "или смените в панели: Настройки → Пользователи",
    "DRIVER_PIN": "PIN демо-водителей (пусто = 1234): задайте до seed или смените в карточке водителя",
}


def parse(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            values[key.strip()] = value.split("#", 1)[0].strip()
    return values


def rewrite(text: str, updates: dict[str, str]) -> str:
    lines = text.splitlines()
    seen: set[str] = set()
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in updates and not line.lstrip().startswith("#"):
            lines[i] = f"{key}={updates[key]}"
            seen.add(key)
    for key, value in updates.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Слабые секреты в infra/.env")
    parser.add_argument("--fix", action="store_true", help="заменить слабые секреты случайными")
    parser.add_argument(
        "--with-device",
        action="store_true",
        help="вместе с --fix сменить и DG_SECRET (только до первого seed: у уже засеянной базы "
        "DG-0001 хранит старый хэш, и симулятор device-sim перестанет входить)",
    )
    args = parser.parse_args(argv)
    if not ENV_PATH.exists():
        print("Нет infra/.env — сначала `make demo` (создаст из .env.example)", file=sys.stderr)
        return 2
    text = ENV_PATH.read_text(encoding="utf-8")
    values = parse(text)
    weak = {k: v for k, v in values.items() if k in WEAK and WEAK[k](v)}
    for key in WEAK:
        if key not in values:
            weak[key] = ""
    if args.fix and weak:
        fixable = {k for k in weak if k != "DG_SECRET" or args.with_device}
        updates = {k: GENERATE[k]() for k in fixable}
        if updates:
            ENV_PATH.write_text(rewrite(text, updates), encoding="utf-8")
            print("infra/.env: сгенерированы случайные " + ", ".join(updates))
        weak = {k: v for k, v in weak.items() if k not in fixable}
    for key in weak:
        if key == "DG_SECRET":
            print(
                "СЛАБО: DG_SECRET (секрет устройства DG-0001 из seed). До первого seed: "
                "`python infra/secrets_check.py --fix --with-device`; база уже засеяна — "
                "пересеять (SEED=always) или отключить DG-0001 в Настройки → Устройства"
            )
        else:
            print(f"СЛАБО: {key} — задайте случайное значение (make secrets-check FIX=1)")
    for key, hint in HINTS.items():
        if not values.get(key):
            print(f"ПОДСКАЗКА: {key} пусто — {hint}")
    return 1 if weak else 0


if __name__ == "__main__":
    sys.exit(main())
