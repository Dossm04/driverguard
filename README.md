# DriverGuard

Прототип мониторинга состояния водителя: камера и предупреждения у водителя,
события и отчёты в панели координатора. Веб-интерфейс доступен на русском, казахском и английском; Android 0.6 — на русском.

## Начать здесь

- **Облачная панель:** [вход координатора](https://web-production-c2a69.up.railway.app/login),
  [вход водителя](https://web-production-c2a69.up.railway.app/driver/login). Ноутбук не нужен;
  доступность зависит от работающих сервисов и остатка пробного кредита Railway.
- **Локальный показ:** установите Docker Desktop и выполните шаги «Запуск в Windows» ниже.
- **Обучение телефона, сигареты и ремня:** [инструкция и блокноты Colab](training/README.md).
- **Android 0.6 / Samsung A53:** [вход, предрейсовый аудит, мониторинг и журнал](android/README.md).
  APK для 64-битного Android 8+ содержит локальные модели, повторяющуюся тревогу,
  PERCLOS, персональный EAR, моргания, признаки зевоты, наклона и поворота головы,
  GPS-условия движения, сохранение и отправку измерений с очередью событий.
  Полный сценарий новой версии на физическом телефоне проверяется отдельно.
- **Постоянный сервер:** [размещение на Railway](docs/deploy-railway.md) с PostgreSQL и S3.
- **Архитектура:** камера/PWA → FastAPI → PostgreSQL + S3 → панель координатора;
  дополнительный Python-агент выполняет детекцию и отправляет события.
- **Статус:** это прототип. Новая модель четырёх классов ещё не обучена до конца;
  подтверждённых результатов полевых испытаний нет. Демонстрационные данные не являются
  статистикой реального автопарка.

GitHub хранит исходники и запускает автоматические проверки; облачные API и панель
работают на Railway. Локальный запуск через Docker и HTTPS-туннель остаётся отдельным
вариантом показа. В Android обработка камеры и очередь событий находятся на устройстве.
Первый вход и загрузка формы аудита требуют сети; сохранённый аккаунт и форма доступны
локально. Проверку камеры и восстановления связи на физическом A53 необходимо завершить.

## Запуск в Windows

1. Запустите Docker Desktop и дождитесь состояния Engine running.
2. Дважды нажмите `START_DEMO.cmd` в корне проекта. Python и Node на хосте для этого не нужны.
3. Откроются панель и локальный файл доступа `.runtime/ACCESS_LOCAL.txt`.
4. Панель: http://localhost:3000/login. Приложение водителя: http://localhost:3000/driver/login.
5. Для камеры на этом ноутбуке: http://localhost:3000/driver/camera, разрешите камеру и звук.
6. Остановка: `STOP_DEMO.cmd`. Данные сохраняются. После изменения кода: `powershell -NoProfile -ExecutionPolicy Bypass -File infra/start-demo.ps1 -Rebuild`.

При первом запуске создаются случайные пароли в `infra/.env`. Не публикуйте этот файл и `.runtime/`.
Если на этом же ПК распаковать комплект в новую папку, скрипт найдёт исходный `infra/.env`
по сведениям контейнеров `driverguard-demo`, сверит его с их настройками и скопирует в новую папку.
Пароли, база и фотографии сохраняются. Если исходные настройки тоже потеряны или не совпадают,
запуск остановится без создания новых паролей. Не заменяйте `.env` шаблоном поверх существующей базы.
Используется отдельный Docker-проект `driverguard-demo`, PostgreSQL на порту 15432 и S3 на 9000.
Порты доступны только с ноутбука. Для камеры телефона нужен отдельно настроенный HTTPS.
Старую базу MinIO этот комплект не переносит и не удаляет: SeaweedFS использует новый том `s3data`.

## Камера iPhone

Камеру запускайте в Safari на самом iPhone, панель координатора оставьте на ноутбуке.
USB-C можно использовать для зарядки. `localhost` на телефоне указывает на телефон.

1. После `START_DEMO.cmd` запустите `START_PHONE.cmd`: он включает временный публичный
   HTTPS-доступ через Cloudflare. Авторизация по паролю/PIN сохраняется.
2. Откройте на iPhone ссылку из `.runtime/PHONE_LINK.txt`, войдите по телефону и PIN
   из `.runtime/ACCESS_LOCAL.txt`, перейдите в «Камера» и разрешите доступ.
3. Держите Safari на экране, iPhone разблокированным, ноутбук включённым, Docker работающим.
4. `STOP_PHONE.cmd` отключает HTTPS и возвращает локальные адреса. База и фото сохраняются.

Этот режим подготовлен для камеры и передачи событий. S3 наружу не публикуется;
старые ссылки `localhost:9000` на фото нельзя открыть с телефона.

Исправление загрузчика камеры: пустой `NEXT_PUBLIC_MP_WASM_URL` из Docker теперь
выбирает `/mediapipe/wasm`. Раньше загружался `/vision_wasm_internal.js` с ответом 404.

## Что реализовано

Панель координатора, события и их разбор, профили, скоринг, рейсы, чек-листы, PDF/CSV,
приложение водителя и локальная обработка камеры MediaPipe. Длительное закрытие глаз
оценивается временными правилами. Телефон и курение в браузере определяются по жестам.
Для предметной модели YOLO подготовлен отдельный путь обучения и ONNX для Python-устройства.
Новые обученные веса, точность на реальных водителях и ночные испытания в эту проверку не входят.

На локальном стенде AI_PROVIDER=mock: фото чек-листа сохраняются, но ИИ их не анализирует.
DEMO_MODE=true двигает демонстрационные машины на карте; это не данные реального автопарка.
Telegram не отправляет сообщения, пока пользователь не подключит своего бота.
В PWA кадры камеры обрабатываются локально. Python-агент отдельно умеет сохранять клипы.

## Изменения проверки 01.10.2026

Исправлены очередь фото при временных ошибках, непрерывные таймеры после потери лица,
доступ к рейсам без назначенной машины, внутренние ссылки клипов, PDF на Windows,
проверка паролей перед туннелем и запрет установки модели без пройденного quality gate.
Недоступные образы MinIO заменены SeaweedFS с фиксированным digest; историческая конфигурация
сохранена в `infra/docker-compose.legacy-minio.yml`, её не используйте для нового запуска.
MINIO_* и имя сервиса minio сохранены как совместимый интерфейс настроек S3.

Ниже сохранены подробные инструкции разработки; для первого показа используйте запуск выше.
Ноутбуки и инструкция обучения находятся в [training/](training/README.md).

## Постоянный QR для текущего стенда

После локального запуска используйте `START_STABLE_QR.cmd` и укажите свой токен ngrok
в локальном запросе скрипта. В этой копии настроен домен владельца стенда
`mothball-urgent-quaintly.ngrok-free.dev`; страница для жюри — `/jury.html`.
Адрес закреплён за аккаунтом ngrok, но доступность зависит от ноутбука и туннеля.
Для другого аккаунта замените домен в `infra/start-stable-qr.ps1` и
`infra/docker-compose.stable-qr.yml`. Остановка — `STOP_STABLE_QR.cmd`.
Не запускайте одновременно временный и постоянный режим доступа.

## Структура монорепо

| Каталог      | Что внутри |
|--------------|------------|
| `backend/`   | FastAPI, SQLAlchemy 2, Alembic, PostgreSQL, MinIO (S3), WebSocket, pytest |
| `web/`       | Next.js 15 (App Router), TypeScript, Tailwind, shadcn/ui, recharts, react-leaflet |
| `device/`    | Python 3.11: MediaPipe DMS, машина состояний, SQLite-очередь, `--simulate` / `--source 0` |
| `bot/`       | aiogram 3 — Telegram-алерты координатору |
| `ml/`        | ML-контур: датасет → YOLOv8n → ONNX, реестр версий, очередь дообучения, стендовый протокол ([ml/README.md](ml/README.md)) |
| `training/`  | Блокноты Google Colab, проверка данных и импорт модели-кандидата |
| `infra/`     | docker-compose.yml (db, minio, backend, web, bot, device-sim), `.env.example` |
| `docs/`      | api.md, decisions.md, скриншоты |
| `reference/` | ТЗ, план сборки, эталоны Figma |

## Разработка без Windows-лаунчера (Bash)

Ниже отдельный сценарий для разработчика с Python и Node на хосте. Для готового локального
показа используйте `START_DEMO.cmd` выше. Команды ниже не нужны для уже запущенного `driverguard-demo`.

```bash
# 1. Переменные окружения (+ случайные JWT_SECRET / MINIO_ROOT_PASSWORD / DG_SECRET —
#    backend не стартует со слабым JWT_SECRET)
cp infra/.env.example infra/.env && python3 infra/secrets_check.py --fix

# 2. Инфраструктура (по умолчанию только db + minio — dev-серверы запускаем на хосте)
docker compose -f infra/docker-compose.yml up -d

# 3a. Backend (создание venv — один раз), миграции + демо-данные, dev-сервер
cd backend
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"
set -a && . ../infra/.env && set +a          # переменные из infra/.env (или: make backend-dev)
.venv/bin/alembic upgrade head && .venv/bin/python -m app.seed
.venv/bin/uvicorn app.main:app --reload

# 3b. Web (в отдельном терминале)
cd web && npm install && npm run dev
```

Полный стек в контейнерах одной командой (профиль `full`: db, minio, backend с миграциями и
демо-данными, панель + PWA, Telegram-бот, симулятор устройства):

```bash
make demo          # ~3–5 минут с нуля; make demo-logs · make demo-down
```

Сценарий показа на 5 минут — [docs/demo-script.md](docs/demo-script.md).
Пошаговый запуск на своём ноутбуке (Windows/macOS/Linux, Telegram, камера, телефон) —
[docs/quickstart-laptop.md](docs/quickstart-laptop.md). Публичные ссылки для менторов
(Cloudflare Tunnel, учётки `make mentors`) — [docs/public-demo.md](docs/public-demo.md).
Стенд для жюри на 30–40 телефонов (нагрузка, план Б) — [docs/demo-jury.md](docs/demo-jury.md);
production-стандарты (что применено, что отложено) — [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md).
Дорожная карта следующих этапов (модель, железо, сервер, пилот) — [docs/roadmap.md](docs/roadmap.md).

## Порты готового Windows-демо

| Сервис          | Порт | Адрес |
|-----------------|------|-------|
| Backend (API)   | 8000 | http://localhost:8000 (Swagger: `/docs`) |
| Web (панель)    | 3000 | http://localhost:3000 |
| PWA водителя    | 3000 | http://localhost:3000/driver (телефон +77012441832, PIN из `.runtime/ACCESS_LOCAL.txt`) |
| PostgreSQL      | 15432 | localhost:15432 |
| SeaweedFS S3 API | 9000 | http://localhost:9000; объекты открываются по подписанным ссылкам приложения |

Консоль MinIO на 9001 в этой сборке не используется. В ручном dev-сценарии порт PostgreSQL
зависит от `DB_PORT` (шаблон: 5432; Windows-лаунчер: 15432).

## Тесты и линтеры

```bash
# Backend
cd backend && .venv/bin/pytest -q
cd backend && .venv/bin/ruff check .

# Web
cd web && npm run lint
cd web && npm run build

# Device (см. device/README.md)
cd device && .venv/bin/pytest -q
cd device && .venv/bin/python -m dg --simulate --speedup 10     # без камеры

# ML (см. ml/README.md)
cd ml && .venv/bin/pytest -q                                    # без torch
cd ml && .venv/bin/python scripts/train.py --smoke              # синтетика → YOLOv8n → ворота (нужен .[train])
cd device && .venv/bin/python -m dg --source 0 --display         # веб-камера

# Bot
cd bot && .venv/bin/pytest -q

# Всё сразу (кроме e2e)
make test
```

Часто используемые команды собраны в [Makefile](Makefile) (`make help`): `make demo`,
`make infra-up`, `make seed`, `make backend-dev`, `make web-dev`, `make test`, `make web-e2e`,
`make backup` / `make backup-restore DIR=…` (копии БД и фото), `make load-test N=40 ADMINS=5`
(нагрузка стенда), `make tunnel`, `make mentors N=…`, `make ai-setup KEY=…`.

Офлайн-камера телефона, сохранение событий и порядок проверки описаны в
[инструкции по офлайн-режиму](docs/offline-camera.md). Перед отключением сети нажмите
«Подготовить офлайн» на странице камеры и дождитесь подтверждения.
