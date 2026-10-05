"""Наблюдаемость и устойчивость (PRODUCTION_STANDARDS 1, 4, 5): структурированные логи с
request-id, метрики запросов, security-заголовки, rate limit, лимит размера тела — без
внешних сервисов.

Всё в памяти одного процесса backend: для пилота на одном сервере этого достаточно; при
горизонтальном масштабировании лимиты и метрики переезжают в Redis/Prometheus.
"""

from __future__ import annotations

import json
import logging
import re
import time
import uuid
from collections import defaultdict, deque
from contextvars import ContextVar
from threading import Lock

import jwt

from app.config import get_settings

request_id_var: ContextVar[str] = ContextVar("request_id", default="-")

# Пределы тела запроса: JSON панели/PWA — килобайты; multipart чек-листа — до 7+10 фото по 4 МБ
MAX_JSON_BODY = 2 * 1024 * 1024
MAX_BODY = 80 * 1024 * 1024
# request-id из заголовка принимаем только «чистый» (без ESC-последовательностей в логах)
_RID_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,64}$")


# ── логи ──────────────────────────────────────────────────────────────────────
class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self.formatTime(record, "%Y-%m-%dT%H:%M:%S%z"),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "request_id": request_id_var.get(),
        }
        for key in ("method", "path", "status", "duration_ms", "client"):
            if hasattr(record, key):
                payload[key] = getattr(record, key)
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        return json.dumps(payload, ensure_ascii=False)


class TextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        rid = request_id_var.get()
        prefix = f"[{rid}] " if rid != "-" else ""
        ts = self.formatTime(record, "%H:%M:%S")
        return f"{ts} {record.levelname:<7} {record.name}: {prefix}{record.getMessage()}"


def setup_logging() -> None:
    s = get_settings()
    root = logging.getLogger()
    root.setLevel(s.log_level.upper())
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter() if s.log_format.lower() == "json" else TextFormatter())
    root.handlers = [handler]
    # access-лог пишет наше middleware (с request-id и длительностью) — штатный uvicorn дублирует
    logging.getLogger("uvicorn.access").disabled = True
    for name in ("uvicorn", "uvicorn.error"):
        logging.getLogger(name).handlers = []
        logging.getLogger(name).propagate = True


access_log = logging.getLogger("driverguard.access")


def safe_text(value: str, limit: int = 200) -> str:
    """Строка для текстового лога: без управляющих символов (инъекция ESC-последовательностей)."""
    return value.encode("ascii", "backslashreplace").decode()[:limit]


# ── метрики ───────────────────────────────────────────────────────────────────
class Metrics:
    """Счётчики и латентность по маршрутам (кольцо из 500 замеров на маршрут).
    Несопоставившиеся пути (404 по случайным URL) идут в один бакет — иначе память растёт
    от чужого сканера."""

    def __init__(self) -> None:
        self._lock = Lock()
        self.started = time.time()
        self.count: dict[str, int] = defaultdict(int)
        self.errors: dict[str, int] = defaultdict(int)
        self.latency: dict[str, deque[float]] = defaultdict(lambda: deque(maxlen=500))
        self.rate_limited = 0
        self.rejected_body = 0

    def observe(self, route: str, status: int, duration_ms: float) -> None:
        with self._lock:
            self.count[route] += 1
            if status >= 500:
                self.errors[route] += 1
            self.latency[route].append(duration_ms)

    @staticmethod
    def _pct(values: list[float], p: float) -> float:
        if not values:
            return 0.0
        ordered = sorted(values)
        idx = min(len(ordered) - 1, int(round((len(ordered) - 1) * p)))
        return round(ordered[idx], 1)

    def snapshot(self) -> dict:
        with self._lock:
            routes = {
                route: {
                    "count": self.count[route],
                    "errors_5xx": self.errors[route],
                    "p50_ms": self._pct(list(self.latency[route]), 0.5),
                    "p95_ms": self._pct(list(self.latency[route]), 0.95),
                    "max_ms": round(max(self.latency[route], default=0.0), 1),
                }
                for route in sorted(self.count)
            }
            return {
                "uptime_s": int(time.time() - self.started),
                "requests_total": sum(self.count.values()),
                "errors_5xx_total": sum(self.errors.values()),
                "rate_limited_total": self.rate_limited,
                "rejected_body_total": self.rejected_body,
                "routes": routes,
            }


metrics = Metrics()


# ── rate limit ────────────────────────────────────────────────────────────────
class SlidingWindowLimiter:
    """Скользящее окно в памяти: не более limit событий на ключ за window_s секунд.
    Число ключей ограничено (max_keys): чужой поток мусорных ключей не съест память."""

    def __init__(self, limit: int, window_s: float = 60.0, max_keys: int = 20_000) -> None:
        self.limit = limit
        self.window_s = window_s
        self.max_keys = max_keys
        self._hits: dict[str, deque[float]] = {}
        self._lock = Lock()
        self._last_gc = time.monotonic()

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()

    def _gc(self, now: float, force: bool = False) -> None:
        if not force and now - self._last_gc < 60:
            return
        self._last_gc = now
        for key in [k for k, v in self._hits.items() if not v or now - v[-1] > self.window_s]:
            self._hits.pop(key, None)
        while len(self._hits) > self.max_keys:  # всё ещё много — выкидываем самые старые ключи
            self._hits.pop(next(iter(self._hits)), None)

    def _window(self, key: str, now: float) -> deque[float]:
        hits = self._hits.get(key)
        if hits is None:
            if len(self._hits) >= self.max_keys:
                self._gc(now, force=True)
            hits = self._hits[key] = deque()
        while hits and now - hits[0] > self.window_s:
            hits.popleft()
        return hits

    def allow(self, key: str) -> tuple[bool, int]:
        """Учесть попытку сразу → (пропустить?, через сколько секунд повторить)."""
        now = time.monotonic()
        with self._lock:
            hits = self._window(key, now)
            if len(hits) >= self.limit:
                return False, max(1, int(self.window_s - (now - hits[0])) + 1)
            hits.append(now)
            self._gc(now)
            return True, 0

    def check(self, key: str) -> tuple[bool, int]:
        """Только проверить порог, не учитывая попытку (для входа: учитываем лишь неудачи)."""
        now = time.monotonic()
        with self._lock:
            hits = self._window(key, now)
            if len(hits) >= self.limit:
                return False, max(1, int(self.window_s - (now - hits[0])) + 1)
            return True, 0

    def hit(self, key: str) -> None:
        now = time.monotonic()
        with self._lock:
            self._window(key, now).append(now)
            self._gc(now)


AUTH_PATHS = (
    "/api/v1/auth/login",
    "/api/v1/auth/driver-login",
    "/api/v1/auth/device",
    "/api/v1/auth/refresh",
)

# Лимитеры — на процесс (тесты и /health/metrics видят те же объекты, что middleware).
# Вход: на IP, считаются только НЕУДАЧНЫЕ попытки (зал жюри за одним IP входит без помех;
# подбор пароля дополнительно режет блокировка учётки в security.py).
# Остальное: на проверенный токен пользователя, без токена — на IP.
auth_limiter = SlidingWindowLimiter(get_settings().rate_limit_auth_per_min)
general_limiter = SlidingWindowLimiter(get_settings().rate_limit_per_min)


def client_ip(scope: dict) -> str:
    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
    if get_settings().trust_proxy:
        forwarded = headers.get("cf-connecting-ip") or headers.get("x-forwarded-for", "")
        if forwarded:
            return safe_text(forwarded.split(",")[0].strip(), 64)
    client = scope.get("client")
    return client[0] if client else "unknown"


def limiter_key(scope: dict) -> str:
    """Авторизованные запросы считаем на пользователя из ПОДПИСАННОГО токена (телефоны за одним
    NAT не мешают друг другу; подделать ключ случайным Bearer нельзя), остальные — на IP."""
    headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
    auth = headers.get("authorization", "")
    if auth.startswith("Bearer "):
        try:
            payload = jwt.decode(
                auth[7:],
                get_settings().jwt_secret,
                algorithms=["HS256"],
                options={"verify_exp": False},  # просроченный токен всё равно один пользователь
            )
            return f"tok:{payload.get('typ', '?')}:{payload.get('sub', '?')}"
        except jwt.PyJWTError:
            pass
    return "ip:" + client_ip(scope)


def route_template(scope: dict) -> str:
    """«GET /api/v1/drivers/{driver_id}/profile» вместо конкретного id: метрики по шаблону
    маршрута, а не по каждому объекту. Шаблон восстанавливается из path_params (у вложенных
    роутеров FastAPI scope["route"].path не содержит префикса). Несопоставившиеся пути —
    один бакет."""
    method = scope.get("method", "?")
    if "endpoint" not in scope:
        return f"{method} <unmatched>"
    path = scope.get("path", "?")
    params = scope.get("path_params") or {}
    if params:
        by_value = {str(v): name for name, v in params.items()}
        segments = [f"{{{by_value[seg]}}}" if seg in by_value else seg for seg in path.split("/")]
        path = "/".join(segments)
    return f"{method} {path}"


class ObservabilityMiddleware:
    """Один ASGI-слой: request-id, access-лог, метрики, security-заголовки, rate limit,
    лимит тела, JSON-ответ 500. WebSocket и lifespan пропускаем как есть."""

    SECURITY_HEADERS = [
        (b"x-content-type-options", b"nosniff"),
        (b"x-frame-options", b"DENY"),
        (b"referrer-policy", b"no-referrer"),
        (b"cache-control", b"no-store"),
    ]

    def __init__(self, app) -> None:  # noqa: ANN001
        self.app = app
        self.auth_limiter = auth_limiter
        self.general_limiter = general_limiter

    async def _reject(self, send, status: int, detail: str, rid: str, extra=()) -> None:  # noqa: ANN001
        body = json.dumps({"detail": detail, "request_id": rid}, ensure_ascii=False).encode()
        await send(
            {
                "type": "http.response.start",
                "status": status,
                "headers": [
                    (b"content-type", b"application/json; charset=utf-8"),
                    (b"content-length", str(len(body)).encode()),
                    (b"x-request-id", rid.encode()),
                    *extra,
                    *self.SECURITY_HEADERS,
                ],
            }
        )
        await send({"type": "http.response.body", "body": body})

    async def __call__(self, scope, receive, send) -> None:  # noqa: ANN001
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        headers = {k.decode().lower(): v.decode() for k, v in scope.get("headers", [])}
        incoming = headers.get("x-request-id", "")
        rid = incoming if _RID_RE.match(incoming) else uuid.uuid4().hex[:12]
        token = request_id_var.set(rid)
        scope["request_id"] = rid  # для обработчика необработанных ошибок (main.py)
        path = scope.get("path", "")
        started = time.perf_counter()
        status_holder = {"status": 0}

        try:
            # Размер тела: JSON — 2 МБ, multipart (фото чек-листа) — 80 МБ; выше — 413 без чтения
            try:
                content_length = int(headers.get("content-length", "0") or 0)
            except ValueError:
                content_length = 0
            is_json = "json" in headers.get("content-type", "")
            if content_length > (MAX_JSON_BODY if is_json else MAX_BODY):
                metrics.rejected_body += 1
                await self._reject(send, 413, "Слишком большой запрос", rid)
                status_holder["status"] = 413
                return

            is_auth = path in AUTH_PATHS
            if is_auth:
                key = "ip:" + client_ip(scope)  # без токена: считаем IP, учитываем только неудачи
                allowed, retry_after = self.auth_limiter.check(key)
            else:
                key = limiter_key(scope)
                allowed, retry_after = self.general_limiter.allow(key)
            if not allowed:
                metrics.rate_limited += 1
                await self._reject(
                    send,
                    429,
                    f"Слишком много запросов. Попробуйте через {retry_after} с",
                    rid,
                    extra=[(b"retry-after", str(retry_after).encode())],
                )
                status_holder["status"] = 429
                return

            async def send_wrapper(message) -> None:  # noqa: ANN001
                if message["type"] == "http.response.start":
                    status_holder["status"] = message["status"]
                    existing = {k.lower() for k, _ in message.get("headers", [])}
                    extra = [(k, v) for k, v in self.SECURITY_HEADERS if k not in existing]
                    message["headers"] = [
                        *message.get("headers", []),
                        (b"x-request-id", rid.encode()),
                        *extra,
                    ]
                await send(message)

            try:
                await self.app(scope, receive, send_wrapper)
            except Exception:
                # Трассировка — в лог по request-id; клиенту — JSON 500 с тем же id и всеми
                # заголовками (CORS снаружи добавит свои), а не обрыв соединения
                access_log.exception("Необработанная ошибка %s %s", scope.get("method"), path)
                if status_holder["status"] == 0:
                    status_holder["status"] = 500
                    await self._reject(send, 500, "Внутренняя ошибка сервера", rid)
            if is_auth and status_holder["status"] >= 400:
                self.auth_limiter.hit(key)
        finally:
            duration_ms = (time.perf_counter() - started) * 1000
            status = status_holder["status"] or 500
            metrics.observe(route_template(scope), status, duration_ms)
            if not path.endswith("/health"):  # liveness-опросы не засоряют лог
                access_log.info(
                    "%s %s → %s за %.0f мс",
                    scope.get("method"),
                    safe_text(path),
                    status,
                    duration_ms,
                    extra={
                        "method": scope.get("method"),
                        "path": safe_text(path),
                        "status": status,
                        "duration_ms": round(duration_ms, 1),
                        "client": client_ip(scope),
                    },
                )
            request_id_var.reset(token)
