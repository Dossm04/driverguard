"""Аутентификация: bcrypt-хэши, JWT, зависимости ролей, PIN-лимитер (SEC-1, SEC-2)."""

import time
from collections import defaultdict
from datetime import UTC, datetime, timedelta

import bcrypt
import jwt
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db import get_db
from app.models import Device, User

ALGORITHM = "HS256"
ACCESS_TTL = timedelta(hours=12)
REFRESH_TTL = timedelta(days=30)

# Блокировка подбора PIN/пароля/секрета устройства (in-memory на процесс, docs/decisions.md):
# 5 свободных попыток за 15 минут, дальше — прогрессивная пауза 1, 2, 4 … 60 с между
# попытками. Подбор становится бесполезным (≤1 попытка/мин), а жертва «5 чужих ошибок»
# не заперта на 15 минут — важно для зала, где все телефоны за одним IP.
PIN_MAX_ATTEMPTS = 5
PIN_WINDOW_S = 15 * 60
PIN_MAX_DELAY_S = 60
_pin_attempts: dict[str, list[float]] = defaultdict(list)
_pin_calls = 0

# Хэш-«пустышка»: bcrypt выполняется и для несуществующей учётки, чтобы по времени ответа
# нельзя было перечислять email/телефоны
DUMMY_HASH = "$2b$12$uRGjk6Q3TRtieOnBpFAPY.N9IZyRNbAdCi./eIQwxhg4qc8nZlN6W"

_bearer = HTTPBearer(auto_error=False)


def hash_secret(raw: str) -> str:
    """Хэширует пароль, PIN или секрет устройства.

    Вторая линия защиты: на строке длиннее 72 байт bcrypt выбрасывает
    исключение с английским текстом, и наружу это уходило как 500.
    Первая линия — валидаторы схем (_password_fits_bcrypt), здесь же
    страхуемся от любого будущего вызова в обход API.
    """
    payload = raw.encode()
    if len(payload) > 72:
        raise ValueError(
            f"секрет длиннее 72 байт ({len(payload)}): bcrypt столько не принимает. "
            "В кириллице это примерно 36 символов."
        )
    return bcrypt.hashpw(payload, bcrypt.gensalt()).decode()


def verify_secret(raw: str, hashed: str | None) -> bool:
    if not hashed or len(raw.encode()) > 72:  # bcrypt: >72 байт — ValueError в новых версиях
        return False
    try:
        return bcrypt.checkpw(raw.encode(), hashed.encode())
    except ValueError:
        return False


def create_token(sub: str, typ: str, ttl: timedelta, **claims: object) -> str:
    payload = {
        "sub": sub,
        "typ": typ,
        "exp": datetime.now(UTC) + ttl,
        **claims,
    }
    return jwt.encode(payload, get_settings().jwt_secret, algorithm=ALGORITHM)


def decode_token(token: str) -> dict:
    try:
        return jwt.decode(token, get_settings().jwt_secret, algorithms=[ALGORITHM])
    except jwt.PyJWTError as exc:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Недействительный токен") from exc


def user_tokens(user: User) -> dict:
    """Пара access+refresh для пользователя."""
    claims = {"role": user.role, "name": user.name}
    return {
        "access_token": create_token(str(user.id), "access", ACCESS_TTL, **claims),
        "refresh_token": create_token(str(user.id), "refresh", REFRESH_TTL),
        "token_type": "bearer",
    }


def _prune_attempts(now: float) -> None:
    """Раз в ~1000 вызовов выбрасываем ключи без свежих неудач — словарь не растёт от мусора."""
    global _pin_calls
    _pin_calls += 1
    if _pin_calls % 1000:
        return
    for key in [k for k, ts in _pin_attempts.items() if not ts or now - ts[-1] >= PIN_WINDOW_S]:
        _pin_attempts.pop(key, None)


def pin_attempts_left(phone: str) -> int:
    """>0 — попытка разрешена. После PIN_MAX_ATTEMPTS неудач в окне следующая попытка
    возможна только через 2^(n−5) с (до 60 с) после последней неудачи."""
    now = time.monotonic()
    _prune_attempts(now)
    attempts = [t for t in _pin_attempts[phone] if now - t < PIN_WINDOW_S]
    _pin_attempts[phone] = attempts
    left = PIN_MAX_ATTEMPTS - len(attempts)
    if left > 0:
        return left
    delay = min(PIN_MAX_DELAY_S, 2 ** (len(attempts) - PIN_MAX_ATTEMPTS))
    return 1 if now - attempts[-1] >= delay else 0


def pin_retry_after(phone: str) -> int:
    """Сколько секунд ждать до следующей попытки (для сообщения и Retry-After)."""
    now = time.monotonic()
    attempts = [t for t in _pin_attempts.get(phone, []) if now - t < PIN_WINDOW_S]
    if len(attempts) < PIN_MAX_ATTEMPTS:
        return 0
    delay = min(PIN_MAX_DELAY_S, 2 ** (len(attempts) - PIN_MAX_ATTEMPTS))
    return max(1, int(delay - (now - attempts[-1])) + 1)


def pin_register_failure(phone: str) -> None:
    _pin_attempts[phone].append(time.monotonic())


def pin_reset(phone: str) -> None:
    _pin_attempts.pop(phone, None)


def _credentials(
    creds: HTTPAuthorizationCredentials | None = Depends(_bearer),
) -> str:
    if creds is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Требуется авторизация")
    return creds.credentials


def get_current_user(token: str = Depends(_credentials), db: Session = Depends(get_db)) -> User:
    payload = decode_token(token)
    if payload.get("typ") != "access":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Нужен access-токен")
    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Пользователь не найден")
    touch_last_seen(db, user)
    return user


# «Кто онлайн»: last_seen пишем не чаще раза в минуту, чтобы не грузить БД на каждый запрос
LAST_SEEN_THROTTLE = timedelta(minutes=1)
ONLINE_WINDOW = timedelta(minutes=5)


def touch_last_seen(db: Session, user: User) -> None:
    now = datetime.now(UTC)
    if user.last_seen is None or now - user.last_seen >= LAST_SEEN_THROTTLE:
        user.last_seen = now
        db.commit()


def is_online(last_seen: datetime | None) -> bool:
    return bool(last_seen and datetime.now(UTC) - last_seen <= ONLINE_WINDOW)


def require_roles(*roles: str):
    """Фабрика зависимостей: доступ только перечисленным ролям."""

    def dependency(user: User = Depends(get_current_user)) -> User:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав")
        return user

    return dependency


def get_device_or_user(
    token: str = Depends(_credentials), db: Session = Depends(get_db)
) -> Device | User:
    """События может слать устройство (device-токен) или сотрудник (admin/coordinator)."""
    payload = decode_token(token)
    if payload.get("typ") == "device":
        device = db.get(Device, int(payload["sub"]))
        if device is None:
            raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Устройство не найдено")
        if device.status == "disabled":  # отзыв доступа без ротации секрета
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Устройство отключено")
        return device
    if payload.get("typ") == "access":
        user = db.get(User, int(payload["sub"]))
        if user is None or user.role not in ("admin", "coordinator"):
            raise HTTPException(status.HTTP_403_FORBIDDEN, "Недостаточно прав")
        return user
    raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Недействительный токен")


def phone_for(user: object, phone: str | None) -> str | None:
    """Телефон водителя — персональные данные (SEC-5, ТЗ 3.2): роль viewer его не видит."""
    return None if getattr(user, "role", None) == "viewer" else phone
