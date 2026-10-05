"""Пользователи панели (WEB-9 «Пользователи и роли»): admin / coordinator / viewer.

Учётки водителей создаются в разделе «Водители» (телефон + PIN) и здесь не редактируются.
Все изменения — в аудит (SEC-4); пароль в аудит не попадает.
"""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AuditLog, User
from app.schemas import UserIn, UserOut, UserPatch
from app.security import hash_secret, is_online, require_roles

router = APIRouter(prefix="/users", tags=["пользователи"])

_admin = Depends(require_roles("admin"))


def _user_out(u: User) -> UserOut:
    out = UserOut.model_validate(u)
    out.online = is_online(u.last_seen)
    return out


@router.get("", response_model=list[UserOut], dependencies=[_admin])
def list_users(db: Session = Depends(get_db)):
    """Все учётки (сотрудники и водители) с признаком «онлайн» — был запрос ≤5 мин назад."""
    users = db.scalars(select(User).order_by(User.role, User.name)).all()
    return [_user_out(u) for u in users]


@router.post("", response_model=UserOut, status_code=201)
def create_user(body: UserIn, db: Session = Depends(get_db), user: User = _admin):
    now = datetime.now(UTC)
    account = User(
        role=body.role,
        email=body.email.lower(),
        password_hash=hash_secret(body.password),
        name=body.name,
        created_at=now,
    )
    db.add(account)
    try:
        db.flush()
    except IntegrityError as exc:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Пользователь с таким email уже есть"
        ) from exc
    db.add(
        AuditLog(
            user_id=user.id,
            action="user_create",
            entity=f"user:{account.id}",
            before=None,
            after={"name": account.name, "email": account.email, "role": account.role},
            ts=now,
        )
    )
    db.commit()
    db.refresh(account)
    return account


@router.patch("/{user_id}", response_model=UserOut)
def patch_user(user_id: int, body: UserPatch, db: Session = Depends(get_db), user: User = _admin):
    account = db.get(User, user_id)
    if account is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Пользователь не найден")
    if account.role == "driver":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Учётки водителей редактируются в разделе «Водители»"
        )
    if body.role is not None and account.id == user.id and body.role != account.role:
        raise HTTPException(status.HTTP_409_CONFLICT, "Нельзя изменить собственную роль")
    before = {"name": account.name, "role": account.role}
    if body.name is not None:
        account.name = body.name
    if body.role is not None:
        account.role = body.role
    if body.password:
        account.password_hash = hash_secret(body.password)
    now = datetime.now(UTC)
    db.add(
        AuditLog(
            user_id=user.id,
            action="user_update",
            entity=f"user:{account.id}",
            before=before,
            after={"name": account.name, "role": account.role, "password": bool(body.password)},
            ts=now,
        )
    )
    db.commit()
    db.refresh(account)
    return account
