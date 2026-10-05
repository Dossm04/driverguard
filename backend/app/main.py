"""Точка входа FastAPI-приложения DriverGuard."""

import contextlib
import logging
import time

import anyio
from fastapi import APIRouter, Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text

from app import storage, ws
from app.config import get_settings
from app.db import engine
from app.observability import (
    ObservabilityMiddleware,
    metrics,
    request_id_var,
    setup_logging,
)
from app.routers import (
    auth,
    checklists,
    dashboard,
    directories,
    events,
    leaderboard,
    profile,
    reports,
    retrain,
    settings,
    trips,
    users,
)
from app.security import require_roles

setup_logging()
log = logging.getLogger("driverguard")
_settings = get_settings()


@contextlib.asynccontextmanager
async def lifespan(app: FastAPI):
    # Sync-эндпоинты (SQLAlchemy) идут через пул потоков anyio; по умолчанию в нём 40 потоков —
    # 40 телефонов с heartbeat + панели упирались бы в очередь. Задаётся WORKER_THREADS.
    anyio.to_thread.current_default_thread_limiter().total_tokens = _settings.worker_threads
    log.info(
        "DriverGuard backend запущен: потоки=%s, пул БД=%s+%s, лимиты %s/%s в мин, логи=%s",
        _settings.worker_threads,
        _settings.db_pool_size,
        _settings.db_max_overflow,
        _settings.rate_limit_auth_per_min,
        _settings.rate_limit_per_min,
        _settings.log_format,
    )
    async with ws.lifespan(app):
        yield


app = FastAPI(title="DriverGuard API", version="0.1.0", lifespan=lifespan)

# Порядок слоёв (последний add_middleware — внешний): CORS снаружи, чтобы и 429 лимитера,
# и 500 получали CORS-заголовки, а preflight OPTIONS не считался в лимит.
app.add_middleware(ObservabilityMiddleware)
# CORS: панель на 3000 и любые адреса локальной сети (телефон с PWA по IP ноутбука);
# список и regex — из настроек (CORS_ORIGINS, CORS_ORIGIN_REGEX)
app.add_middleware(
    CORSMiddleware,
    allow_origins=_settings.cors_origin_list,
    allow_origin_regex=_settings.cors_origin_regex_effective,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition", "X-Request-Id", "Retry-After"],
)


@app.exception_handler(Exception)
async def unhandled_error(request: Request, exc: Exception) -> JSONResponse:
    """Необработанная ошибка → JSON 500 с request-id (правило 8: не прячем, но и не отдаём
    трассировку наружу; подробности — в лог по этому же id)."""
    rid = request.scope.get("request_id") or request_id_var.get()
    return JSONResponse(
        status_code=500,
        content={"detail": "Внутренняя ошибка сервера", "request_id": rid},
        headers={"X-Request-Id": rid, "Cache-Control": "no-store"},
    )


# Все HTTP-ручки живут под /api/v1
api_router = APIRouter(prefix="/api/v1")


@api_router.get("/health")
def health() -> dict[str, str]:
    """Liveness: процесс жив и отвечает (без обращения к БД)."""
    return {"status": "ok", "service": "driverguard-backend", "version": "0.1.0"}


def _check_db() -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


_ready_cache: dict = {"at": 0.0, "status": 0, "body": {}}
# Публичная ручка без токена: кэш, чтобы её нельзя было сделать усилителем нагрузки на БД/MinIO
READY_CACHE_S = 3.0


@api_router.get("/health/ready")
async def ready() -> JSONResponse:
    """Readiness: БД и хранилище отвечают. 503 — трафик пускать рано (compose healthcheck,
    балансировщик). Причины не раскрываем наружу, они в логе. Результат кэшируется 3 с."""
    if time.monotonic() - _ready_cache["at"] < READY_CACHE_S:
        return JSONResponse(status_code=_ready_cache["status"], content=_ready_cache["body"])
    checks: dict[str, str] = {}
    for name, fn in (("db", _check_db), ("storage", storage.ping)):
        try:
            with anyio.fail_after(5):
                await anyio.to_thread.run_sync(fn)
            checks[name] = "ok"
        except Exception as exc:  # noqa: BLE001 — любая причина = не готов
            log.warning("readiness: %s недоступно: %s", name, exc)
            checks[name] = "error"
    ok = all(v == "ok" for v in checks.values())
    body = {"status": "ready" if ok else "not_ready", **checks}
    _ready_cache.update(at=time.monotonic(), status=200 if ok else 503, body=body)
    return JSONResponse(status_code=200 if ok else 503, content=body)


@api_router.get("/health/metrics", dependencies=[Depends(require_roles("admin"))])
async def health_metrics() -> dict:  # async: лимитер потоков виден только из event loop
    """Счётчики запросов, латентность p50/p95 по маршрутам, пул БД, WebSocket — для админа
    (панель «Настройки → Пользователи» и нагрузочный тест)."""
    snap = metrics.snapshot()
    snap["db_pool"] = engine.pool.status()
    snap["ws_connections"] = len(ws.manager.connections)
    snap["live_positions"] = len(ws._live)
    limiter = anyio.to_thread.current_default_thread_limiter()
    snap["thread_limiter"] = {"total": limiter.total_tokens, "borrowed": limiter.borrowed_tokens}
    return snap


api_router.include_router(auth.router)
api_router.include_router(directories.router)
api_router.include_router(trips.router)
api_router.include_router(events.router)
api_router.include_router(dashboard.router)
api_router.include_router(leaderboard.router)
api_router.include_router(profile.router)
api_router.include_router(profile.trainings_router)
api_router.include_router(checklists.router)
api_router.include_router(settings.router)
api_router.include_router(users.router)
api_router.include_router(reports.router)
api_router.include_router(retrain.router)

app.include_router(api_router)
# WebSocket живёт на /ws/live без префикса API (ТЗ 7.2)
app.include_router(ws.router)
