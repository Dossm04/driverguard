"""Аутентификация: координатор/админ, водитель (PIN), устройство (BE-1)."""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app import security
from app.db import get_db
from app.models import Device, Driver, User
from app.schemas import DeviceLoginIn, DriverLoginIn, LoginIn, RefreshIn, TokenOut, UserOut

router = APIRouter(prefix="/auth", tags=["auth"])


def _check_attempts(key: str) -> None:
    """Блокировка подбора: после 5 неудач — прогрессивная пауза (security.py)."""
    if security.pin_attempts_left(key) <= 0:
        wait = security.pin_retry_after(key)
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            f"Слишком много попыток. Попробуйте через {wait} с",
            headers={"Retry-After": str(wait)},
        )


@router.post("/login", response_model=TokenOut)
def login(body: LoginIn, db: Session = Depends(get_db)) -> TokenOut:
    email = body.email.strip().lower()  # учётки хранятся в нижнем регистре (users.py)
    key = f"email:{email}"
    _check_attempts(key)  # тот же лимитер, что для PIN (SEC-2)
    user = db.scalar(select(User).where(func.lower(User.email) == email))
    # bcrypt считается и для несуществующей учётки — время ответа не выдаёт, есть ли email
    ok = security.verify_secret(body.password, user.password_hash if user else security.DUMMY_HASH)
    if user is None or not ok:
        security.pin_register_failure(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный email или пароль")
    security.pin_reset(key)
    return TokenOut(**security.user_tokens(user), user=UserOut.model_validate(user))


@router.post("/driver-login", response_model=TokenOut)
def driver_login(body: DriverLoginIn, db: Session = Depends(get_db)) -> TokenOut:
    _check_attempts(body.phone)
    user = db.scalar(select(User).where(User.phone == body.phone, User.role == "driver"))
    ok = security.verify_secret(body.pin, user.pin_hash if user else security.DUMMY_HASH)
    if user is None or not ok:
        security.pin_register_failure(body.phone)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный телефон или PIN")
    security.pin_reset(body.phone)
    driver = db.scalar(select(Driver).where(Driver.user_id == user.id))
    return TokenOut(
        **security.user_tokens(user),
        user=UserOut.model_validate(user),
        driver_id=driver.id if driver else None,
    )


@router.post("/device", response_model=TokenOut)
def device_login(body: DeviceLoginIn, db: Session = Depends(get_db)) -> TokenOut:
    key = f"device:{body.serial}"
    _check_attempts(key)  # секрет устройства подбирать так же нельзя, как PIN
    device = db.scalar(select(Device).where(Device.serial == body.serial))
    ok = security.verify_secret(body.secret, device.secret_hash if device else security.DUMMY_HASH)
    if device is None or not ok:
        security.pin_register_failure(key)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Неверный serial или секрет")
    security.pin_reset(key)
    device.last_seen = datetime.now(UTC)
    db.commit()
    token = security.create_token(str(device.id), "device", timedelta(days=365))
    return TokenOut(access_token=token)


@router.post("/refresh", response_model=TokenOut)
def refresh(body: RefreshIn, db: Session = Depends(get_db)) -> TokenOut:
    payload = security.decode_token(body.refresh_token)
    if payload.get("typ") != "refresh":
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Нужен refresh-токен")
    user = db.get(User, int(payload["sub"]))
    if user is None:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "Пользователь не найден")
    driver = (
        db.scalar(select(Driver).where(Driver.user_id == user.id))
        if user.role == "driver"
        else None
    )
    return TokenOut(
        **security.user_tokens(user),
        user=UserOut.model_validate(user),
        driver_id=driver.id if driver else None,
    )
