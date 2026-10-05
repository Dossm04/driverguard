"""Очередь дообучения (ML-5, BE-8): ложные срабатывания из review → выгрузка в ml/,
отметка об экспорте."""

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session, joinedload

from app import storage
from app.db import get_db
from app.models import AuditLog, Driver, Event, RetrainQueueItem
from app.schemas import RetrainExportIn, RetrainExportOut, RetrainItemOut, RetrainListOut
from app.security import require_roles

router = APIRouter(prefix="/retrain-queue", tags=["дообучение"])
_staff = Depends(require_roles("admin", "coordinator"))


@router.get("", response_model=RetrainListOut)
def list_retrain_queue(
    exported: bool | None = Query(
        default=False, description="false — ещё не выгруженные, true — выгруженные"
    ),
    limit: int = Query(default=200, ge=1, le=500),
    internal: bool = False,
    db: Session = Depends(get_db),
    user=_staff,
):
    """Элементы очереди с данными события и presigned-ссылкой на клип
    (internal=true — адрес внутри docker-сети)."""
    q = select(RetrainQueueItem)
    if exported is True:
        q = q.where(RetrainQueueItem.exported_at.is_not(None))
    elif exported is False:
        q = q.where(RetrainQueueItem.exported_at.is_(None))
    total = db.scalar(select(func.count()).select_from(q.subquery())) or 0
    rows = db.scalars(
        q.order_by(RetrainQueueItem.created_at.asc(), RetrainQueueItem.id.asc()).limit(limit)
    ).all()
    events = {
        e.uuid: e
        for e in db.scalars(
            select(Event)
            .where(Event.uuid.in_([r.event_uuid for r in rows]))
            .options(joinedload(Event.driver).joinedload(Driver.vehicle), joinedload(Event.device))
        ).unique()
    }
    items = []
    for r in rows:
        e = events.get(r.event_uuid)
        if e is None:
            continue
        items.append(
            RetrainItemOut(
                id=r.id,
                event_uuid=r.event_uuid,
                label_hint=r.label_hint,
                frame_key=r.frame_key,
                created_at=r.created_at,
                exported_at=r.exported_at,
                event_type=e.type,
                event_ts=e.ts,
                severity=e.severity,
                confidence=e.confidence,
                speed_kmh=e.speed_kmh,
                status=e.status,
                model_version=e.device.model_version
                if e.device
                else None,  # версия детектора устройства (ML-4)
                driver_name=e.driver.name if e.driver else None,
                vehicle_plate=e.driver.vehicle.plate if e.driver and e.driver.vehicle else None,
                clip_url=storage.presigned_clip_download(e.clip_key, internal=internal)
                if e.clip_key
                else None,
            )
        )
    return RetrainListOut(items=items, total=total)


@router.post("/mark-exported", response_model=RetrainExportOut)
def mark_exported(body: RetrainExportIn, db: Session = Depends(get_db), user=_staff):
    """Помечает элементы выгруженными (ml/scripts/retrain_queue.py --mark);
    повторная отметка — no-op."""
    now = datetime.now(UTC)
    rows = db.scalars(
        select(RetrainQueueItem).where(
            RetrainQueueItem.id.in_(body.ids), RetrainQueueItem.exported_at.is_(None)
        )
    ).all()
    for r in rows:
        r.exported_at = now
    if rows:
        db.add(
            AuditLog(
                user_id=user.id,
                action="retrain_export",
                entity=f"retrain_queue:{len(rows)}",
                after={"ids": [r.id for r in rows]},
                ts=now,
            )
        )
    db.commit()
    return RetrainExportOut(exported=len(rows), ids=[r.id for r in rows])
