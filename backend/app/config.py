"""Конфигурация приложения через pydantic-settings.

Значения по умолчанию рассчитаны на локальную разработку и совпадают
с infra/.env.example. Переменные читаются из окружения и файла .env.
"""

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict

# localhost и частные сети (192.168/10/172.16–31) на любом порту — телефон с PWA по IP ноутбука
DEFAULT_CORS_REGEX = (
    r"^https?://(localhost|127\.0\.0\.1|192\.168\.\d{1,3}\.\d{1,3}|10\.\d{1,3}\.\d{1,3}\.\d{1,3}"
    r"|172\.(1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3})(:\d+)?$"
)


class Settings(BaseSettings):
    """Настройки backend-сервиса DriverGuard."""

    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # База данных
    database_url: str = "postgresql+psycopg://driverguard:driverguard@localhost:5432/driverguard"

    # MinIO (S3-совместимое хранилище клипов и фото)
    minio_endpoint: str = "http://localhost:9000"
    minio_root_user: str = "minioadmin"
    minio_root_password: str = "minioadmin"
    # Публичный адрес MinIO для presigned-ссылок, которые открывает БРАУЗЕР
    # (в docker-сети backend видит minio:9000, а браузер — localhost:9000).
    # Пусто — используется minio_endpoint.
    minio_public_endpoint: str = ""
    # Регион для подписи presigned-ссылок (MinIO по умолчанию us-east-1): задан явно, чтобы
    # клиент не ходил за ним по сети на публичный адрес, недоступный из контейнера
    minio_region: str = "us-east-1"
    minio_bucket_clips: str = "clips"
    minio_bucket_photos: str = "photos"

    # Аутентификация (в проде обязательно заменить; минимум 32 байта для HS256)
    jwt_secret: str = "dev-only-change-me-in-production-driverguard-jwt"

    # ИИ-проверка чек-листов (BE-10). ai_provider: auto | openai_compat | gemini | mock;
    # auto — openai_compat при ключе (alem.ai, данные в Казахстане), иначе gemini при
    # ключе, иначе mock-вердикт для демо.
    ai_provider: str = "auto"
    # OpenAI-совместимый API (alem.ai: https://llm.alem.ai/v1, ключ выдаётся на модель)
    openai_compat_base_url: str = ""
    openai_compat_api_key: str = ""
    openai_compat_model: str = "gemma4"  # alem.ai: модель с картинками (Gemma 4)
    gemini_api_key: str = ""
    gemini_model: str = "gemini-3.6-flash"
    gemini_base_url: str = "https://generativelanguage.googleapis.com"
    # Пусто — уровень рассуждений по умолчанию провайдера (лучшая калибровка confidence);
    # "low" — быстрее ~в 3 раза, если KPI-10 (≤30 с) важнее точности
    gemini_thinking_level: str = ""
    ai_timeout_s: float = 60.0
    # Интеграции (пустые значения — интеграция отключена)
    anthropic_api_key: str = ""  # адаптер Claude — по ТЗ 7.3, подключается при появлении ключа
    telegram_bot_token: str = ""
    telegram_chat_id: str = ""

    # CORS: панель и PWA на другом origin (телефон в той же Wi-Fi открывает панель по IP ноутбука).
    # cors_origins — список через запятую; cors_origin_regex — по умолчанию любые localhost и
    # частные сети (192.168.x.x, 10.x.x.x, 172.16–31.x.x) на любом порту
    cors_origins: str = "http://localhost:3000"
    cors_origin_regex: str = (
        ""  # пусто = DEFAULT_CORS_REGEX; свой регэксп — для нестандартных сетей
    )

    @property
    def cors_origin_regex_effective(self) -> str:
        """Пустое значение из окружения (compose) = регулярное выражение по умолчанию."""
        return self.cors_origin_regex or DEFAULT_CORS_REGEX

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]

    # Часовой пояс парка: границы «сегодня/вчера», графики по дням, серии без нарушений.
    # Казахстан с 2024 года живёт в одном поясе UTC+5 (Asia/Almaty). Переменная APP_TZ.
    app_tz: str = "Asia/Almaty"

    # Демо-режим: симулятор движения машин для live-карты (SYS «Симуляция»)
    demo_mode: bool = True

    # ── Production-стандарты (docs/ARCHITECTURE.md) ──
    # Логи: уровень и формат (text — для терминала, json — для сборщика логов)
    log_level: str = "INFO"
    log_format: str = "text"
    # Клиентский IP из X-Forwarded-For / CF-Connecting-IP — только за доверенным прокси
    # (Cloudflare Tunnel, nginx); иначе заголовок можно подделать и обойти лимиты
    trust_proxy: bool = False
    # Rate limit: попытки входа на IP в минуту (зал на одном Wi-Fi = один IP, поэтому щедро;
    # подбор пароля режет блокировка учётки на 15 минут в auth.py) и общий поток на токен/IP
    rate_limit_auth_per_min: int = 120
    rate_limit_per_min: int = 1200
    # Пул соединений к PostgreSQL и потоки sync-эндпоинтов: 40 телефонов + 5 панелей
    # одновременно (heartbeat раз в 15 с, WS, опросы дашборда) — с запасом
    db_pool_size: int = 20
    db_max_overflow: int = 30
    worker_threads: int = 100


@lru_cache
def get_settings() -> Settings:
    """Единственный экземпляр настроек на процесс (слабый JWT-секрет — предупреждение в лог)."""
    import logging
    import os

    settings = Settings()
    if len(settings.jwt_secret.encode()) < 32 or "change-me" in settings.jwt_secret:
        message = (
            "JWT_SECRET слабый или по умолчанию: с ним любой может выписать себе admin-токен. "
            'Задайте случайную строку ≥32 байт в infra/.env (python -c "import secrets;'
            'print(secrets.token_hex(32))") и перезапустите backend. Для локальных '
            "экспериментов: DG_ALLOW_WEAK_SECRET=1"
        )
        if os.environ.get("DG_ALLOW_WEAK_SECRET") != "1":
            raise RuntimeError(message)
        logging.getLogger("driverguard").warning(message)
    return settings
