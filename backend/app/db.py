"""Подключение к базе: engine, фабрика сессий, база деклараций."""

from collections.abc import Iterator

from sqlalchemy import create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import get_settings


class Base(DeclarativeBase):
    """Базовый класс всех ORM-моделей."""


_s = get_settings()
# pool_pre_ping — мёртвые соединения после рестарта PostgreSQL не отдаются в запрос;
# размер пула — под одновременную работу десятков телефонов и панелей (docs/ARCHITECTURE.md)
engine = create_engine(
    _s.database_url,
    pool_pre_ping=True,
    pool_size=_s.db_pool_size,
    max_overflow=_s.db_max_overflow,
    pool_timeout=30,
    pool_recycle=1800,
)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    """FastAPI-зависимость: сессия на запрос."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
