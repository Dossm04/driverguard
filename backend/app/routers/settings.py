"""Настройки (BE-15): разделы scoring / thresholds / notifications / retention.

Каждый раздел валидируется своей pydantic-схемой (app.schemas.SETTING_MODELS),
изменение поднимает version и пишется в аудит (SEC-4). Редактирует только admin,
координатор и наблюдатель читают. Предпросмотр пересчёта Score — без сохранения.
"""

from datetime import UTC, datetime, timedelta

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app import scoring, stats
from app.db import get_db
from app.models import AuditLog, Driver, Setting, User
from app.schemas import (
    SETTING_MODELS,
    ScoringPreviewRow,
    ScoringSettings,
    SettingIn,
    SettingOut,
)
from app.security import require_roles

router = APIRouter(prefix="/settings", tags=["настройки"])

_admin = Depends(require_roles("admin"))
_staff_read = Depends(require_roles("admin", "coordinator", "viewer"))


def _validation_message(exc: ValidationError) -> str:
    parts = []
    for err in exc.errors()[:4]:
        loc = ".".join(str(x) for x in err.get("loc", ()))
        parts.append(f"{loc}: {err.get('msg')}" if loc else str(err.get("msg")))
    return "; ".join(parts)


def _validate(key: str, value: dict) -> BaseModel:
    model = SETTING_MODELS.get(key)
    if model is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Раздел настроек не найден")
    try:
        return model.model_validate(value)
    except ValidationError as exc:
        raise HTTPException(422, f"Настройки «{key}»: {_validation_message(exc)}") from exc


def _setting_out(row: Setting, users: dict[int, User]) -> SettingOut:
    author = users.get(row.updated_by) if row.updated_by else None
    return SettingOut(
        key=row.key,
        value=row.value,
        version=row.version,
        updated_at=row.updated_at,
        updated_by_name=author.name if author else None,
    )


def _users_by_id(db: Session, rows: list[Setting]) -> dict[int, User]:
    ids = {r.updated_by for r in rows if r.updated_by}
    if not ids:
        return {}
    return {u.id: u for u in db.scalars(select(User).where(User.id.in_(ids)))}


@router.get("", response_model=list[SettingOut], dependencies=[_staff_read])
def list_settings(db: Session = Depends(get_db)):
    rows = db.scalars(select(Setting).order_by(Setting.key)).all()
    users = _users_by_id(db, rows)
    return [_setting_out(r, users) for r in rows]


@router.post("/scoring/preview", response_model=list[ScoringPreviewRow], dependencies=[_staff_read])
def preview_scoring(body: dict, db: Session = Depends(get_db)):
    """Как изменится недельный Score каждого водителя при новых весах — без сохранения."""
    cfg = _validate("scoring", body)  # читаемая 422, как и у PUT
    assert isinstance(cfg, ScoringSettings)
    now = datetime.now(UTC)
    since = now - timedelta(days=7)
    streaks = stats.streaks_by_driver(db, now)
    current = stats.scores_by_driver(db, since, now, 7, streaks)
    weights = {**scoring.DEFAULT_WEIGHTS, **cfg.weights}
    proposed = stats.scores_by_driver(
        db, since, now, 7, streaks, weights, cfg.modifiers.model_dump()
    )
    drivers = db.scalars(select(Driver).order_by(Driver.name)).all()
    rows = []
    for d in drivers:
        if d.id not in current or d.id not in proposed:
            continue
        rows.append(
            ScoringPreviewRow(
                driver_id=d.id,
                name=d.name,
                score_now=current[d.id].score,
                score_new=proposed[d.id].score,
                delta=proposed[d.id].score - current[d.id].score,
            )
        )
    return rows


@router.get("/{key}", response_model=SettingOut, dependencies=[_staff_read])
def get_setting(key: str, db: Session = Depends(get_db)):
    row = db.get(Setting, key)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Раздел настроек не найден")
    return _setting_out(row, _users_by_id(db, [row]))


@router.put("/{key}", response_model=SettingOut)
def update_setting(key: str, body: SettingIn, db: Session = Depends(get_db), user: User = _admin):
    parsed = _validate(key, body.value)
    now = datetime.now(UTC)
    row = db.get(Setting, key)
    before = dict(row.value) if row else None
    after = parsed.model_dump()
    if key == "scoring":  # неуказанный тип = вес по умолчанию, а не 0 в форме
        after["weights"] = {**scoring.DEFAULT_WEIGHTS, **after["weights"]}
    if row is None:
        row = Setting(key=key, value=after, version=1, updated_by=user.id, updated_at=now)
        db.add(row)
    else:
        row.value = after
        row.version += 1  # версионирование изменений (BE-15)
        row.updated_by = user.id
        row.updated_at = now
    db.add(
        AuditLog(
            user_id=user.id,
            action="settings_update",
            entity=f"settings:{key}",
            before=before,
            after=after,
            ts=now,
        )
    )
    db.commit()
    db.refresh(row)
    return _setting_out(row, {user.id: user})
