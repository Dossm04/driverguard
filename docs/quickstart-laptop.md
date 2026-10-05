# Запуск DriverGuard на своём ноутбуке (Windows / macOS / Linux)

Цель: за 15 минут получить панель, PWA на телефоне, Telegram-алерты и устройство с веб-камерой.
Всё, что ниже, проверено в сборочной среде на Linux; на Windows команды выполняйте в
**PowerShell** (или в WSL2 — тогда всё как на Linux).

## 0. Что нужно установить

| Что | Зачем | Где взять |
|---|---|---|
| Git | скачать проект | git-scm.com |
| Docker Desktop (Windows/macOS) или Docker Engine (Linux) | база, MinIO, backend, панель, бот, симулятор | docker.com |
| Python 3.11+ | устройство с веб-камерой (MediaPipe) и вспомогательные скрипты | python.org (на Windows поставьте галочку «Add to PATH») |
| Node.js 20+ (необязательно) | только если хотите править панель и запускать `npm run dev` | nodejs.org |

Windows: `make` по умолчанию нет — ниже для каждого шага дана прямая команда `docker compose …`
или `python …`, которая делает то же, что цель Makefile.

## 1. Скачать проект и ветку

```bash
git clone https://github.com/edserver2026-cpu/driverguard1.git
cd driverguard1
git checkout claude/driverguard-full-build-92zul4
```

## 2. Настройки: `.env` с токеном бота

```bash
cp infra/.env.example infra/.env        # Windows PowerShell: Copy-Item infra\.env.example infra\.env
```

Откройте `infra/.env` и впишите токен от BotFather:

```
TELEGRAM_BOT_TOKEN=123456789:AAF…ваш-токен-от-BotFather
```

Ключ ИИ для проверки фото чек-листа — туда же. Без ключа работает демо-режим: вердикт «допущен»
без анализа, панель показывает это в Настройки → Чек-лист. Для реальной проверки нужна модель
с картинками; на платформе alem.ai это **Gemma 4**:

```
OPENAI_COMPAT_BASE_URL=https://llm.alem.ai/v1
OPENAI_COMPAT_API_KEY=ключ-из-кабинета-alem.ai
OPENAI_COMPAT_MODEL=gemma4
```

После изменения `.env` перезапустите backend (`docker compose … up -d backend`) и нажмите
«Проверить ИИ» в Настройки → Чек-лист: панель отправит тестовую картинку и покажет ответ модели
или текст ошибки (неверный ключ, недоступный хост). Запасной вариант — `GEMINI_API_KEY`.

## 3. Поднять весь стек

```bash
make demo
# без make:
docker compose -f infra/docker-compose.yml --profile full up -d --build
```

Первая сборка образов занимает 3–5 минут. Backend сам применяет миграции и загружает
демо-данные (пустая база → seed). Готово, когда `http://localhost:8000/docs` открывается.

| Что | Адрес | Вход |
|---|---|---|
| Панель координатора | http://localhost:3000 | admin@driverguard.kz / admin123 |
| PWA водителя | http://localhost:3000/driver | +77012441832 / PIN 1234 |
| Swagger | http://localhost:8000/docs | — |
| MinIO | http://localhost:9001 | minioadmin / minioadmin |

Логи: `make demo-logs` (или `docker compose -f infra/docker-compose.yml --profile full logs -f`).
Симулятор устройства `device-sim` уже шлёт события с машины DG-0001 (Иванов А.С.) — они
появляются в «Событиях» и на Live-карте каждые 10–30 секунд.

## 4. Telegram: две команды

Бот в контейнере уже запущен с вашим токеном. Осталось указать, куда слать:

1. Откройте бота в Telegram (`t.me/<username-вашего-бота>`), нажмите **/start**. Бот ответит и
   покажет ваш Chat ID. Для группы: добавьте бота в группу, напишите в ней `/start`.
2. Впишите Chat ID в панели: **Настройки → Уведомления → Chat ID координатора → Сохранить**.

Или то же самое скриптом (он найдёт chat_id сам, запишет в панель и пришлёт тест):

```bash
cd bot && python -m venv .venv && .venv/bin/pip install -e ".[dev]"      # один раз
.venv/bin/python scripts/check_telegram.py --token <ТОКЕН> --set-chat auto --send-test
# Windows: .venv\Scripts\python scripts\check_telegram.py --token <ТОКЕН> --set-chat auto --send-test
```

Скрипт печатает, кто писал боту (chat_id, тип чата), сохраняет последний в панель и шлёт
«✅ DriverGuard: связь есть». Если бот в контейнере уже забрал ваши сообщения и скрипт
пишет «никто не писал» — остановите бота на минуту (`docker compose … stop bot`), снова
нажмите /start и повторите, затем `… start bot`.

Проверка алерта: Swagger → `POST /api/v1/events` (Authorize как admin) с телом из
`docs/telegram.md` §5 — сообщение с кнопками приходит за ≤10 с. Кнопка «Ложное» меняет
статус события в панели и возвращает водителю баллы.

## 5. Устройство с веб-камерой (на этом же ноутбуке)

```bash
cd device
python -m venv .venv && .venv/bin/pip install -e ".[dev]"      # Linux/macOS (Debian: sudo apt install libgl1 libegl1 libgles2 libglib2.0-0 ffmpeg)
.venv/bin/python -m dg --source 0 --display --gps sim
# Windows: py -3.11 -m venv .venv ; .venv\Scripts\pip install -e ".[dev]" ; .venv\Scripts\python -m dg --source 0 --display --gps sim
```

При первом запуске скачается модель Face Landmarker (3.7 МБ). В окне — статус
«КАЛИБРОВКА» 2–3 с, затем «НОРМА». Закройте глаза на 2 секунды: сирена (если есть звук:
`pip install simpleaudio`), в терминале «СОБЫТИЕ microsleep», через ~30 с событие в панели
с клипом. Чтобы устройство не конфликтовало с симулятором из Docker, остановите его:
`docker compose -f infra/docker-compose.yml --profile full stop device-sim`.

Сценарий «авиарежим»: выключите Wi-Fi на 1–2 минуты (события копятся в `device/dg.sqlite`),
включите — они уйдут батчем, дубликатов не будет.

**Телефон, курение, ремень (детектор нарушений).** В репозитории лежит `device/models/yolov8n-coco.onnx`
(класс «cell phone» до своей модели). Поставьте onnxruntime, и детектор включится сам:

```bash
.venv/bin/pip install -e ".[yolo]"          # Windows: .venv\Scripts\pip install -e ".[yolo]"
.venv/bin/python -m dg --source 0 --display --gps sim
```

В логе появится «Детектор нарушений: coco-yolov8n …», на плашке внизу — `phone/cig/belt-off`, боксы
рисуются на кадре. Поднесите телефон к уху на 2–3 с (симулятор GPS даёт скорость > 5 км/ч) — событие
`phone` уйдёт в панель; телефон, лежащий на столе, событий не даёт. Курение и ремень заработают после
обучения своей модели (`ml/README.md`, Colab-ноутбук `ml/notebooks/`).

## 6. PWA на телефоне

Телефон и ноутбук — в одной Wi-Fi. Узнайте IP ноутбука (`ipconfig` / `ifconfig`), например
`192.168.1.20`, и пересоберите панель с этим адресом (адрес backend вшивается в бандл):

```bash
NEXT_PUBLIC_API_URL=http://192.168.1.20:8000/api/v1 NEXT_PUBLIC_WS_URL=ws://192.168.1.20:8000/ws/live \
MINIO_PUBLIC_ENDPOINT=http://192.168.1.20:9000 \
docker compose -f infra/docker-compose.yml --profile full up -d --build web backend
```

(на Windows задайте те же переменные в `infra/.env`). Backend уже разрешает CORS для любых
адресов локальной сети. На телефоне откройте `http://192.168.1.20:3000/driver`, войдите
по PIN. **Кнопка «Установить на экран» и офлайн-кэш требуют HTTPS** (или localhost): для
настоящей установки на телефон и камеры в браузере нужен https-адрес — на демо это одна
команда `make tunnel` (Cloudflare Tunnel, бесплатно; учётки менторов — `make mentors N=5`),
подробно — [docs/public-demo.md](public-demo.md). Ключ ИИ для проверки фото — одной командой:
`python infra\ai_setup.py --key sk-…` (пропишет ключ Gemma 4 в infra/.env, перезапустит backend и
прогонит тест; без `--key` спросит ключ скрытым вводом). Без HTTPS PWA работает как обычный сайт:
чек-лист, SOS с координатами, Score, обучение — всё доступно.

## 7. Всё ли связано: чек-лист самопроверки

| Проверка | Ожидание |
|---|---|
| Панель → Обзор | 5/6 машин, 14 событий, Score 78 |
| Live-карта | маркеры движутся, DG-0001 шлёт события (симулятор или ваша камера) |
| События → «Ложное» на микросне Иванова → Лидерборд | Score Иванова 55 → 73 |
| PWA → Чек-лист (7 фото) | вердикт за ≤30 с, чек-лист виден в панели → Чек-листы |
| PWA → Начать рейс, затем 1–2 минуты симулятора | в PWA растут км, в Отчётах у рейса появляются события |
| PWA → SOS | событие «SOS» в панели и алерт в Telegram с причиной и картой |
| Telegram → «Ложное» | статус в панели меняется, в аудите «Telegram: Имя» |
| Настройки → Скоринг → вес 30 → Сохранить | Лидерборд пересчитан сразу |
| Настройки → Пороги → MICROSLEEP_MS 2000 | устройство в логе: «Применены пороги: MICROSLEEP_MS» |

Тесты локально: `make test` (backend 83, device 21, bot 18, web lint+build) и
`cd web && npx playwright test` (25 сценариев; нужны запущенные backend и web).

## 8. Если что-то не так

| Симптом | Что сделать |
|---|---|
| `make: command not found` (Windows) | используйте команды `docker compose …` из этого файла |
| `ports are not available … 5432 … forbidden by its access permissions` (Windows) | порт занят локальным PostgreSQL или зарезервирован Hyper-V: в `infra/.env` задайте `DB_PORT=15432` и снова `up -d` (аналогично `MINIO_CONSOLE_PORT`) |
| Backend не поднимается, в логе `password authentication failed` | `docker compose … down -v` и снова `up` — том базы от старой версии |
| Панель открывается, но данных нет / ошибка сети | backend на 8000 недоступен: `docker compose … logs backend`; в браузере с телефона — проверьте IP в `NEXT_PUBLIC_API_URL` |
| Бот молчит | `docker compose … logs bot`: `401` — нет учётки бота (SEED=always и перезапуск backend), «chat_id не задан» — шаг 4 |
| Камера: `libEGL.so.1` / `libGLESv2` | `sudo apt install libegl1 libgles2` (Debian/Ubuntu) |
| Камера: `Не удалось открыть источник видео` | другой индекс: `--source 1`; на Windows закройте приложения, держащие камеру |
| Чек-лист «ИИ-проверка не удалась» | нет ключа/сети для alem.ai или Gemini — задайте `AI_PROVIDER=mock` для демо |
