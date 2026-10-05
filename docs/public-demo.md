# Публичный доступ для менторов

Цель: у каждого ментора — своя ссылка и свои учётки (координатор панели + водитель PWA),
камера телефона работает в браузере, координатор видит, кто сейчас в системе.

## Вариант 1 (рекомендуется для показа): ноутбук + Cloudflare Tunnel — 5 минут, бесплатно

Что нужно: запущенный `make demo` (Docker) и `cloudflared`
(Windows `winget install Cloudflare.cloudflared`, macOS `brew install cloudflared`).

```bash
make demo             # стек в Docker, если ещё не запущен
make mentors N=5      # 5 комплектов учёток; пароли печатаются ОДИН раз — сохраните их
make tunnel           # два HTTPS-адреса (панель и API), пересборка web ≈ 2–3 мин
```

`make tunnel` печатает ссылки вида `https://<случайное-имя>.trycloudflare.com`:

| Кому | Ссылка | Вход |
|---|---|---|
| Ментор как координатор | `<панель>/login` | `mentorN@demo.driverguard.kz` + пароль из `make mentors` |
| Ментор как водитель | `<панель>/driver` | телефон `+7 777 000 000N` + PIN |
| Камера в браузере телефона | `<панель>/driver/camera` | тот же вход водителя |

Особенности:
- Адреса меняются при каждом запуске `make tunnel` (быстрые туннели без аккаунта).
  Постоянный адрес — именованный туннель на своём домене в Cloudflare (бесплатно, нужен домен).
- Ссылки живут, пока запущен `make tunnel` и ноутбук в сети. При Ctrl+C `infra/.env`
  возвращается к localhost-адресам; чтобы панель снова открывалась локально — `make demo`.
- HTTPS обязателен для камеры и установки PWA — туннель это даёт.
- `make tunnel` также публикует MinIO (фото чек-листов по presigned-ссылкам), включает
  `TRUST_PROXY=true` (лимиты и логи по реальному IP из `CF-Connecting-IP`) и
  `NEXT_PUBLIC_MP_WASM_URL` (WASM MediaPipe с CDN, чтобы десятки телефонов не качали его через
  туннель), перезапускает backend, web и бота. Туннель не откроется, пока действуют пароли по
  умолчанию (`admin123`, PIN `1234`, `device-secret-1`) — смените их или `--allow-default-passwords`.
  Большой зал (30–40 телефонов) — [demo-jury.md](demo-jury.md).
- Кто сейчас в системе: Настройки → Пользователи → колонка «Онлайн» (запрос ≤5 мин назад),
  счётчик «онлайн N из M» в заголовке. Устройства (настоящие блоки и виртуальные `WEB-M00N`
  менторов) — Настройки → Устройства.
- Если backend/web запущены без Docker: `python infra/tunnel.py --mode dev`, затем
  перезапустить `make backend-dev` и `make web-dev-tunnel`.

## Вариант 2 (постоянная ссылка): бесплатные облака

Vercel умеет хостить только `web/` (Next.js). Backend, PostgreSQL и MinIO ему нужны отдельно,
поэтому «всё на Vercel» не получится. Рабочие бесплатные связки:

| Часть | Где | Примечание |
|---|---|---|
| web (Next.js) | Vercel или Render Static/Web | build-переменные `NEXT_PUBLIC_API_URL`, `NEXT_PUBLIC_WS_URL` |
| backend (FastAPI) | Render / Railway / Fly.io (Docker из `backend/Dockerfile`) | env как в `infra/.env.example`; `CORS_ORIGINS` = адрес web |
| PostgreSQL | Neon / Supabase (free) или PostgreSQL из инфраструктуры alem.ai | `DATABASE_URL`, затем `alembic upgrade head` и `python -m app.seed` |
| Фото/клипы (S3) | MinIO из инфраструктуры alem.ai, Cloudflare R2 (free 10 ГБ) | `MINIO_ENDPOINT`, `MINIO_PUBLIC_ENDPOINT`, ключи |
| Telegram-бот | вместе с backend (второй сервис из `bot/Dockerfile`) | `TELEGRAM_BOT_TOKEN` только в переменных окружения хостинга |

Порядок: база → бакеты → backend (миграции + seed + `scripts/mentors.py`) → web с адресом
backend → `CORS_ORIGINS` в backend = адрес web. Бесплатные тарифы «засыпают» без трафика
(первый запрос 20–60 с) — для показа лучше открыть ссылку заранее.

## Безопасность публичного стенда

- `JWT_SECRET` — случайная строка ≥32 байт; пароли `admin123`/`bot12345` из seed сменить в
  Настройки → Пользователи (или `BOT_PASSWORD` в .env до seed).
- Ключи ИИ (`OPENAI_COMPAT_API_KEY`) и токен бота — только в `.env`/переменных хостинга,
  никогда в репозитории. Учётки менторов после показа: `make mentors` → `--remove`.
- Учётки менторов — роль «координатор»: они не могут менять пользователей и роли.
