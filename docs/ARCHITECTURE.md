# DriverGuard — архитектура и production-стандарты

Документ по чек-листу `PRODUCTION_STANDARDS` (11 разделов): что применено сейчас, что заложено
и отложено осознанно, что неприменимо на масштабе пилота (один сервер, до ~100 машин,
стенд для жюри 30–40 телефонов + несколько панелей). Главное правило чек-листа — соразмерность.

## Компоненты

```
телефон (PWA «Камера», MediaPipe в браузере) ─┐
устройство в кабине (device/dg, Pi 5 + Hailo) ─┼─ HTTPS/WSS ─► backend FastAPI ─► PostgreSQL
панель координатора (Next.js)                 ─┘                 │      │           MinIO (фото, клипы)
Telegram-бот (aiogram) ◄──── опрос API ──────────────────────────┘      └─► alem.ai (Gemma 4, фото чек-листов)
```

- **backend/** — FastAPI + SQLAlchemy 2 + Alembic; sync-эндпоинты в пуле потоков anyio
  (`WORKER_THREADS`), WebSocket `/ws/live` для панели, in-memory лимитеры и метрики.
- **web/** — Next.js 15 (App Router, клиентские компоненты, TanStack Query), PWA водителя с
  service worker, DMS в браузере (`@mediapipe/tasks-vision`).
- **device/** — Python-агент в кабине: MediaPipe, машина состояний, SQLite-очередь, sync с
  экспоненциальным retry (30 с → 10 мин), офлайн-режим.
- **bot/** — aiogram 3, алерты critical-событий, review кнопками.
- **infra/** — docker compose (db, minio, backend, web, bot, device-sim), `tunnel.py`
  (Cloudflare quick tunnel → HTTPS для камеры), `backup.py`, `ai_setup.py`.

## Матрица стандартов

Обозначения: **✅ применено** · **🟡 заложено/частично** (осознанно отложено, есть план) ·
**⛔ неприменимо** на этом масштабе.

### 1. Устойчивость (Resilience)

| Пункт | Статус | Где / как |
|---|---|---|
| Rate limiting входящий | ✅ | `app/observability.py`: вход (`/auth/login`, `driver-login`, `device`, `refresh`) — на IP, считаются только **неудачные** попытки (`RATE_LIMIT_AUTH_PER_MIN`, 120/мин: зал на одном Wi-Fi входит без помех, флуд паролями режется); остальное — на пользователя из **подписанного** JWT (`RATE_LIMIT_PER_MIN`, 1200/мин; случайный Bearer не создаёт ключ), без токена — на IP; число ключей ограничено (20 000, LRU). 429 с `Retry-After`. Учётка после 5 ошибок за 15 мин — прогрессивная пауза 1→2→4…60 с (`security.py`): подбор бесполезен, а «5 чужих ошибок» не запирают члена жюри на 15 минут. `/auth/device` под той же защитой по serial. За Cloudflare Tunnel `TRUST_PROXY=true` (реальный IP из `CF-Connecting-IP`), иначе заголовок игнорируется |
| Лимит размера тела | ✅ | JSON ≤2 МБ, multipart (чек-лист) ≤80 МБ — 413 до чтения тела; фото читается не больше 4 МБ + 1 байт; ≤10 дополнительных фото; поля входа с `max_length` |
| Rate limiting исходящий | 🟡 | ИИ-проверка — один вызов на чек-лист, параллельность ограничена пулом потоков; бот уважает `retry_after` Telegram (flood control). Отдельный лимитер к alem.ai не нужен при 40 чек-листах в час |
| Таймауты | ✅ | alem.ai/Gemini `AI_TIMEOUT_S` (60 с); MinIO readiness 2 с; PostgreSQL `pool_timeout=30`; бот `httpx` 10 с; readiness-проверки в `fail_after(5)`; PWA `fetch` с таймаутом геолокации 15 с; device sync `requests` с таймаутом |
| Retries + backoff + jitter | ✅ | device sync: экспонента 30 с → 10 мин; PWA: очередь событий в памяти, повтор при следующем flush, heartbeat каждые 15 с; бот: повтор с `retry_after`. Backend не ретраит ИИ — при сбое чек-лист сохраняется с вердиктом `unavailable`, координатор видит «ИИ недоступен» (честнее, чем ждать 3×60 с) |
| Circuit breaker | 🟡 | ИИ: при ошибке провайдера ответ деградирует мгновенно (`unavailable_verdict`), статус виден в Настройки → Чек-лист. Полноценный breaker (счётчик ошибок → пауза) — при росте числа внешних зависимостей |
| Идемпотентность | ✅ | события — `uuid` от клиента + `ON CONFLICT DO NOTHING` (устройство и PWA); heartbeat идемпотентен по природе; чек-лист — один на водителя в день (повторная отправка обновляет); review события — повтор безопасен |
| Кэширование | 🟡 | панель: TanStack Query (staleTime/refetchInterval 30–60 с) — нагрузка на API ограничена сверху; сводка дашборда считается SQL-агрегатами по индексам. Серверный кэш (Redis) не нужен: p95 сводки < 100 мс при 40 телефонах (см. нагрузочный тест) |
| Балансировка / API-шлюз / reverse proxy | 🟡 | Один процесс uvicorn на пилоте; Cloudflare Tunnel даёт TLS, DDoS-защиту и WAF снаружи. Горизонтальное масштабирование потребует Redis для лимитеров/метрик и pub/sub для WS (см. 9) |

### 2. Асинхронность и сообщения

| Пункт | Статус | Где / как |
|---|---|---|
| Очереди сообщений, Pub/Sub, DLQ, Saga, распределённые транзакции | ⛔ | Один сервис + одна БД; фоновые задачи — `asyncio` (симулятор) и цикл бота. Очередь появится вместе с вторым инстансом backend или тяжёлой ИИ-обработкой (тогда — RQ/Celery + Redis, ИИ-проверка в воркере) |
| Событийная архитектура | 🟡 | Домен уже событийный: устройства и телефоны шлют события с UUID, панель получает их по WebSocket; переход на брокер не меняет контракты |
| Cron | ✅/🟡 | Периодика в процессе: симулятор, `last_seen`; `make backup` — запускать по cron/Планировщику Windows (см. 10) |
| WebSockets / Long polling / SSE | ✅ | WebSocket `/ws/live` (позиции, события, review) для панели; панель дополнительно опрашивает REST раз в 30–60 с — при обрыве WS данные не теряются. SSE не нужен (нужна двунаправленность для ролей) |

### 3. Инфраструктура и деплой

| Пункт | Статус | Где / как |
|---|---|---|
| CI/CD | ✅ | `.github/workflows/ci.yml`: backend (Postgres + MinIO, ruff, alembic с нуля, pytest, pip-audit), web (lint, tsc, build, unit, npm audit), device/bot/ml, e2e поверх живого стека, сборка docker-образов. CD — ручной `make demo`/`docker compose up --build` (один сервер) |
| Docker | ✅ | Все сервисы; `restart: unless-stopped`; healthcheck backend = `/health/ready`, web = `/login`, db `pg_isready`, minio `mc ready` |
| Health / liveness / readiness | ✅ | `/api/v1/health` (liveness), `/api/v1/health/ready` (БД `SELECT 1` + MinIO `bucket_exists`, 503 если нет), `/api/v1/health/metrics` (admin) |
| Откаты | ✅ | образы собираются из git; откат = `git checkout <tag> && make demo`; схема БД — `alembic downgrade -1`; данные — `make backup-restore` |
| Kubernetes, Helm, Service discovery, IaC, blue-green/canary | ⛔ | один сервер; compose-файл и есть «инфраструктура как код» пилота |
| Feature flags | 🟡 | через настройки в БД/`.env`: `DEMO_MODE`, `AI_PROVIDER`, пороги DMS редактируются в Настройках без деплоя |
| Кэш сборки | ✅ | слои Docker (зависимости отдельно от исходников), кэш pip/npm в CI |

### 4. Наблюдаемость

| Пункт | Статус | Где / как |
|---|---|---|
| Структурированные логи с уровнями | ✅ | `setup_logging()`: `LOG_LEVEL`, `LOG_FORMAT=text|json`; каждый запрос — `request_id` (принимается из `X-Request-Id` только «чистый» `[A-Za-z0-9_.:-]`, отдаётся в ответе), метод, путь (без управляющих символов — защита от инъекции в терминал), статус, длительность, клиент. 500 → JSON `{"detail","request_id"}` с CORS- и security-заголовками, без трассировки; трассировка в логе по тому же id |
| Метрики | ✅ | `/health/metrics`: запросы/ошибки/p50/p95/max по **шаблонам** маршрутов, 429, uptime, статус пула БД, число WS-соединений, живых позиций, занятость пула потоков. Формат JSON; экспорт в Prometheus — обёртка при появлении Prometheus |
| Мониторинг и алерты | 🟡 | Docker healthcheck + `restart`; Telegram-бот шлёт алерты о critical-событиях (домен). Алерт «backend не готов» — следующий шаг (uptime-kuma/healthchecks.io на `/health/ready`) |
| Трассировка | 🟡 | `request_id` сквозной между панелью и backend; распределённая трассировка не нужна при одном сервисе |
| SLO / SLI / бюджеты ошибок | 🟡 | Ориентиры зафиксированы: доступность API ≥99% в часы показа, p95 API ≤1 с, событие с телефона → панель ≤3 с, чек-лист с ИИ ≤60 с (KPI-10 ТЗ). Измеряются `scripts/load_test.py` и `/health/metrics` |

### 5. Безопасность

| Пункт | Статус | Где / как |
|---|---|---|
| Секреты | ✅ | только `.env` (в `.gitignore`), compose передаёт переменными; пред-коммитные проверки на ключи; ключи ИИ и токен бота ротируются после показа. `infra/secrets_check.py` (`make demo`, `make secrets-check FIX=1`) генерирует `JWT_SECRET`/`MINIO_ROOT_PASSWORD` (и `DG_SECRET` с `--with-device` до первого seed); backend **не стартует** со слабым `JWT_SECRET` (`DG_ALLOW_WEAK_SECRET=1` — только для экспериментов); seed берёт `ADMIN_PASSWORD`/`DRIVER_PIN` из env, секреты DG-0002…0006 случайные; `make tunnel` отказывается открывать публичный доступ, пока действуют пароли по умолчанию; демо-подсказки на экранах входа скрыты в production-сборке |
| IAM / роли | ✅ | admin / coordinator / viewer / driver / device; `require_roles`; viewer без телефонов; водитель видит только себя (`/drivers/me`), устройство — только своё |
| OAuth | ⛔ | внутренняя система парка; вход по email/паролю, PIN, device-secret |
| JWT и ротация | ✅/🟡 | access 12 ч + refresh 30 дней (`/auth/refresh`, single-flight на клиенте), `JWT_SECRET` ≥32 байт обязателен. Ротация секрета = перевыпуск токенов (`.env` → рестарт). Отзыв отдельного токена (jti/token_version) — 🟡 перед пилотом. WebSocket проверяет роль по базе при рукопожатии (удалённый/пониженный пользователь не держит карту) и не даёт >6 соединений на пользователя |
| TLS | ✅/🟡 | снаружи — Cloudflare Tunnel (HTTPS/WSS, обязателен для камеры); внутри compose-сети — plain HTTP между контейнерами на одном хосте (допустимо; при выносе БД/MinIO на другой хост — `sslmode=require`, MinIO TLS) |
| Шифрование на диске | 🟡 | volumes Docker; фото/клипы — приватные бакеты, presigned-ссылки ≤10 мин; шифрование диска — средствами ОС сервера |
| WAF / DDoS | ✅ | Cloudflare перед туннелем; свой rate limit — второй слой |
| CORS | ✅ | явный список `CORS_ORIGINS` + regex локальной сети для телефонов; `*` не используется |
| CSRF | ⛔ | токен в заголовке `Authorization`, cookie-сессий нет — CSRF неприменим |
| SQL-инъекции | ✅ | только SQLAlchemy с параметрами; сырых f-строк в SQL нет (тест `test_audit_security.py`) |
| XSS | ✅ | React экранирует; `dangerouslySetInnerHTML` не используется; заголовки `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Permissions-Policy` (камера/геолокация только своему origin). CSP — 🟡 черновик ниже |
| SSRF | ✅ | backend ходит только на адреса из конфигурации (alem.ai/Gemini/MinIO), URL от пользователя не принимает; presigned-ссылки генерирует сам |
| Загрузка файлов | ✅ | фото: тип по сигнатуре, лимит размера (413), ключи объектов формируются сервером |

Черновик CSP (включать после проверки на стенде, `next.config.mjs → headers`):
`default-src 'self'; script-src 'self' 'unsafe-inline' https://cdn.jsdelivr.net; worker-src 'self' blob:; connect-src 'self' <API> <WSS> https://cdn.jsdelivr.net https://storage.googleapis.com; img-src 'self' data: blob: https://*.tile.openstreetmap.org <MinIO>; style-src 'self' 'unsafe-inline'; font-src 'self' data:`
(`unsafe-inline` для script — из-за inline-скриптов Next без nonce; при переходе на nonce убрать).

### 6. Сеть и протоколы

| Пункт | Статус |
|---|---|
| DNS / TTL | 🟡 быстрые туннели меняют адрес при каждом запуске; для постоянной ссылки — именованный туннель на своём домене |
| TCP/UDP, HTTP/2/3, gRPC | ⛔ HTTP/1.1 внутри, HTTP/2–3 даёт Cloudflare на краю; gRPC не нужен |
| Webhooks | 🟡 Telegram — long polling (не нужен публичный адрес бота); webhook — при постоянном домене |
| Clock skew | ✅ время события с клиента ограничивается серверным `now` (`min(item.ts, now)`), окна лимитеров — `monotonic` |

### 7. API и версии

| Пункт | Статус |
|---|---|
| Версионирование API | ✅ префикс `/api/v1`, OpenAPI `/docs`; фронт использует только эндпоинты из openapi |
| Semver | 🟡 `version="0.1.0"` в API и package.json; теги релизов — при первом пилоте |
| Lock-файлы | ✅ `package-lock.json`, версии в `pyproject`; `npm audit` = 0 уязвимостей (Next 15.5, postcss ≥8.5.28 через overrides), `pip-audit` в CI |

### 8. База данных

| Пункт | Статус | Где / как |
|---|---|---|
| Индексы | ✅ | `events(driver_id, ts)`, `events(ts)`, `events(status)`, `trips(driver_id, started_at)`, `heartbeats(device_id, ts)`, `checklists.verdict`, уникальные email/phone/plate/serial/uuid |
| Оптимизация запросов, N+1 | ✅ | списки — `joinedload` (события с водителем и машиной), сводка — агрегаты SQL; нагрузочный тест держит p95 маршрутов панели ниже 200 мс |
| Пул соединений | ✅ | `pool_size=20`, `max_overflow=30`, `pool_pre_ping`, `pool_recycle=1800` (`DB_POOL_SIZE`, `DB_MAX_OVERFLOW`) |
| Миграции / версии схемы | ✅ | Alembic, `alembic upgrade head` при старте контейнера; в CI применяются с нуля |
| Реплики, шардинг, партиционирование, leader election, распределённые блокировки | ⛔ | одна БД; партиционирование `events` по месяцам — при > 10 млн строк |
| CAP / eventual consistency | ✅ | PostgreSQL — консистентность; офлайн-очередь устройства и PWA — eventual (события догоняют при появлении сети, UUID исключает дубли) |
| Блокировки | ✅ | оптимистично: review события/чек-листа — последняя запись побеждает, аудит хранит кто/когда; гонок «двух координаторов» бизнес не запрещает |

### 9. Параллелизм и производительность

| Пункт | Статус | Где / как |
|---|---|---|
| Race conditions / потокобезопасность | ✅ | лимитеры и метрики под `Lock`; WS broadcast из потоков через `run_coroutine_threadsafe`; `_live` — dict под GIL с атомарными операциями |
| Deadlocks | ✅ | транзакции короткие (запрос = транзакция), порядок записи фиксирован; `pool_timeout` не даёт зависнуть навсегда |
| Утечки памяти | ✅ | латентности — `deque(maxlen=500)` на маршрут, несопоставившиеся пути (сканеры) — один бакет `<unmatched>`, лимитер ≤20 000 ключей с чисткой, блокировки входа чистятся, `_live` с TTL 2 мин и сборкой раз в минуту, WS-соединения снимаются при ошибке/таймауте отправки (3 с, рассылка параллельная — зависшая панель не тормозит остальных) |
| Backpressure | ✅ | пул потоков `WORKER_THREADS` (100) + пул БД — очередь ограничена; 429 при превышении лимитов; батч событий ≤20 (413) |
| Масштабирование | 🟡 | вертикально — `WORKER_THREADS`/`DB_POOL_*`/`uvicorn --workers` (лимитеры и метрики станут per-process — допустимо; WS-broadcast между воркерами потребует Redis pub/sub). Автомасштабирование ⛔ |
| Ёмкость (нагрузочный тест) | ✅ | `make load-test N=40 ADMINS=5 DURATION=60` — см. раздел «Стенд для жюри» в `docs/demo-jury.md` |

### 10. Устойчивость к катастрофам

| Пункт | Статус | Где / как |
|---|---|---|
| Бэкапы с проверкой восстановления | ✅ | `make backup` → `backups/<дата>/db.dump` (pg_dump -Fc) + `minio.tar.gz`; сразу проверяется `pg_restore --list` и `tar -t`; `make backup-restore DIR=…` останавливает backend, восстанавливает, ждёт `/health/ready`. Хранить копии вне ноутбука (облачный диск) |
| DR-план | ✅ | новый хост: `git clone` → `.env` → `make demo` → `make backup-restore` — 15 минут; ключи/токены — из менеджера паролей команды |
| Failover, мультирегион, chaos | ⛔ | один сервер; `restart: unless-stopped` + healthcheck покрывают падение процесса |

### 11. Эксплуатация

| Пункт | Статус |
|---|---|
| Инциденты / on-call / postmortem | 🟡 шаблон: `docs/demo-jury.md` → «План Б» (что делать, если упало во время показа); postmortem — запись в `docs/decisions.md` |
| Latency / throughput / p99 | ✅ измеряются `load_test.py` (клиент) и `/health/metrics` (сервер, p50/p95/max) |
| Сетевые разделения | ✅ телефон и устройство работают офлайн (очередь), панель показывает «нет связи» (`QueryError`) и переподключает WS |
| CDN / edge-кэш | ✅ WASM MediaPipe с jsdelivr на стенде (`NEXT_PUBLIC_MP_WASM_URL`, ставит `make tunnel`), модель — Google Storage; статика Next с `immutable`-кэшем |
| Инвалидация кэша | ✅ статика Next хэшируется в имени; service worker обновляется при новой сборке |
| Cold start / serverless | ⛔ |

## Переменные production-настроек

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `LOG_LEVEL`, `LOG_FORMAT` | `INFO`, `text` | `json` — для сборщика логов |
| `TRUST_PROXY` | `false` | `true` за Cloudflare/nginx: IP клиента из заголовков |
| `RATE_LIMIT_AUTH_PER_MIN` | `120` | попыток входа с одного IP в минуту |
| `RATE_LIMIT_PER_MIN` | `1200` | запросов на токен/IP в минуту |
| `DB_POOL_SIZE`, `DB_MAX_OVERFLOW` | `20`, `30` | пул PostgreSQL |
| `WORKER_THREADS` | `100` | пул потоков sync-эндпоинтов |
| `NEXT_PUBLIC_MP_WASM_URL` | пусто (свой сервер) | CDN для WASM MediaPipe на стенде |

## Что сделать перед настоящим пилотом (не для показа)

1. Именованный Cloudflare Tunnel на своём домене (постоянные ссылки, CSP по домену).
2. Prometheus-экспорт `/health/metrics` + алерт на `/health/ready` (uptime-kuma).
3. Redis: лимитеры/метрики/WS pub/sub при `uvicorn --workers > 1` или втором сервере.
4. Бэкапы по расписанию (cron / Планировщик Windows) с копией в облако; учение по восстановлению раз в квартал.
5. CSP с nonce; ротация `JWT_SECRET` по регламенту; TLS к БД/MinIO при выносе на другой хост.
