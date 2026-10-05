"""MinIO: presigned-ссылки для загрузки клипов (SEC-3: TTL ≤10 мин, приватные бакеты)."""

import logging
from datetime import timedelta
from functools import lru_cache
from io import BytesIO
from urllib.parse import urlparse

import urllib3
from fastapi import HTTPException, status
from minio import Minio

from app.config import get_settings

PRESIGNED_TTL_S = 600  # 10 минут

log = logging.getLogger(__name__)


@lru_cache(maxsize=2)
def _client(public: bool = False) -> Minio:
    """Клиент на процесс (потокобезопасен): регион бакета кэшируется внутри, иначе каждая
    presigned-ссылка стоила бы отдельного запроса GetBucketLocation к MinIO."""
    s = get_settings()
    endpoint = (s.minio_public_endpoint or s.minio_endpoint) if public else s.minio_endpoint
    parsed = urlparse(endpoint)
    # region задан явно: иначе minio-py делает GetBucketLocation на endpoint, а публичный
    # адрес (localhost:9000 / туннель) из контейнера backend недоступен → 503 при каждой
    # presigned-ссылке («Хранилище фото временно недоступно»)
    return Minio(
        parsed.netloc or endpoint,
        access_key=s.minio_root_user,
        secret_key=s.minio_root_password,
        secure=parsed.scheme == "https",
        region=s.minio_region,
    )


def ping() -> None:
    """Readiness-проверка: MinIO отвечает и бакет фото существует (таймаут 2 с, без ретраев,
    чтобы /health/ready не висел при недоступном хранилище)."""
    s = get_settings()
    parsed = urlparse(s.minio_endpoint)
    client = Minio(
        parsed.netloc or s.minio_endpoint,
        access_key=s.minio_root_user,
        secret_key=s.minio_root_password,
        secure=parsed.scheme == "https",
        region=s.minio_region,
        http_client=urllib3.PoolManager(
            timeout=urllib3.Timeout(connect=2, read=2), retries=urllib3.Retry(total=0)
        ),
    )
    if not client.bucket_exists(s.minio_bucket_photos):
        raise RuntimeError(f"бакет {s.minio_bucket_photos} не создан (minio-init)")


def clip_key(device_serial: str, event_uuid: str, yyyy_mm: str) -> str:
    """Ключ клипа по BE-5: clips/{device}/{yyyy-mm}/{uuid}.mp4."""
    return f"clips/{device_serial}/{yyyy_mm}/{event_uuid}.mp4"


def presigned_clip_upload(key: str) -> str:
    """Presigned PUT в бакет клипов. Ошибку хранилища не прячем (правило 8 CLAUDE.md)."""
    s = get_settings()
    try:
        return _client(public=True).presigned_put_object(
            s.minio_bucket_clips, key, expires=timedelta(seconds=PRESIGNED_TTL_S)
        )
    except Exception as exc:  # соединение/креды — честный 503
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Хранилище клипов временно недоступно, попробуйте через минуту",
        ) from exc


def _presigned_get(bucket: str, key: str, what: str, public: bool = True) -> str:
    try:
        return _client(public=public).presigned_get_object(
            bucket, key, expires=timedelta(seconds=PRESIGNED_TTL_S)
        )
    except Exception as exc:
        log.error("MinIO недоступен (%s, %s): %s", what, key, exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            f"Хранилище {what} временно недоступно, попробуйте через минуту",
        ) from exc


def presigned_clip_download(key: str, internal: bool = False) -> str:
    """Presigned GET для просмотра клипа в модалке события (SEC-3: TTL ≤10 мин)."""
    return _presigned_get(get_settings().minio_bucket_clips, key, "клипов", public=not internal)


def photo_key(driver_id: int, batch: str, slot: str, ext: str, yyyy_mm: str) -> str:
    """Ключ фото чек-листа: checklists/{driver}/{yyyy-mm}/{batch}/{slot}.{ext}."""
    return f"checklists/{driver_id}/{yyyy_mm}/{batch}/{slot}.{ext}"


def put_photo(key: str, data: bytes, content_type: str) -> None:
    """Сохранить фото чек-листа в приватный бакет (панель читает по presigned GET)."""
    s = get_settings()
    try:
        _client().put_object(
            s.minio_bucket_photos, key, BytesIO(data), length=len(data), content_type=content_type
        )
    except Exception as exc:
        # Правило 8: не прячем ошибку, но пользователю — короткое понятное сообщение, детали — в лог
        log.error("MinIO недоступен при загрузке %s: %s", key, exc)
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "Хранилище фото временно недоступно. Чек-лист сохранён и отправится автоматически",
        ) from exc


def presigned_photo_download(key: str) -> str:
    return _presigned_get(get_settings().minio_bucket_photos, key, "фото")
