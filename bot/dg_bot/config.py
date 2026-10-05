"""Конфигурация бота из переменных окружения (см. docs/telegram.md)."""

import os
from dataclasses import dataclass


@dataclass(frozen=True)
class Config:
    token: str
    api_url: str
    api_email: str
    api_password: str
    chat_id_env: str
    poll_s: float
    settings_refresh_s: float
    tz: str
    web_url: str
    telegram_api_base: str | None


def load() -> Config:
    env = os.environ.get
    return Config(
        token=env("TELEGRAM_BOT_TOKEN", "").strip(),
        api_url=env("API_URL", "http://localhost:8000/api/v1").rstrip("/"),
        api_email=env("BOT_EMAIL", "bot@driverguard.kz"),
        api_password=env("BOT_PASSWORD", "bot12345"),
        chat_id_env=env("TELEGRAM_CHAT_ID", "").strip(),
        poll_s=float(env("BOT_POLL_S", "3")),
        settings_refresh_s=float(env("BOT_SETTINGS_REFRESH_S", "15")),
        tz=env("TZ", "Asia/Almaty"),
        web_url=env("WEB_URL", "http://localhost:3000").rstrip("/"),
        telegram_api_base=(env("TELEGRAM_API_BASE") or "").strip() or None,
    )
