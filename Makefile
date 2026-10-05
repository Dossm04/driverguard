# DriverGuard — команды разработки и демо
# По умолчанию infra поднимает только db + minio; полный стек: профиль full (см. infra/docker-compose.yml)

COMPOSE = docker compose -f infra/docker-compose.yml

.PHONY: backup backup-list backup-restore load-test load-test-docker mentors-docker secrets-check ai-setup mentors tunnel web-dev-tunnel web-unit help infra-up infra-down backend-dev web-dev backend-test web-lint web-e2e device-test bot-test ml-test ml-smoke test seed demo demo-down demo-logs telegram-check telegram-set-chat bot-run device-camera device-sim retrain-export

help: ## Список команд
	@grep -E '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-14s\033[0m %s\n", $$1, $$2}'

infra-up: ## Поднять db + minio (+ создание бакетов)
	$(COMPOSE) up -d

infra-down: ## Остановить инфраструктуру
	$(COMPOSE) down

ENV_LOAD = set -a && [ -f infra/.env ] && . ./infra/.env; set +a

backend-dev: ## Dev-сервер backend (нужен backend/.venv; читает infra/.env и backend/.env)
	$(ENV_LOAD) && cd backend && .venv/bin/alembic upgrade head && .venv/bin/uvicorn app.main:app --reload

web-dev: ## Dev-сервер web
	cd web && npm run dev

backend-test: ## Тесты backend
	cd backend && .venv/bin/ruff check . && .venv/bin/pytest -q

web-lint: ## Линтер и сборка web
	cd web && npm run lint && npm run build

web-unit: ## Юнит-тесты web (правила DMS в браузере, без сервера)
	cd web && npm run test:unit

web-e2e: ## Playwright (нужны запущенные backend :8000 и web :3000)
	cd web && npx playwright test

device-test: ## Тесты софта устройства
	cd device && .venv/bin/ruff check . && .venv/bin/pytest -q

bot-test: ## Тесты Telegram-бота
	cd bot && .venv/bin/ruff check . && .venv/bin/pytest -q

ml-test: ## Тесты ML-контура (без torch: сплит, ворота, реестр, декодер ONNX, стенд)
	cd ml && .venv/bin/ruff check . && .venv/bin/pytest -q

ml-smoke: ## Сквозной smoke ML: синтетика → YOLOv8n 1 эпоха → ONNX (нужен ml/.venv с .[train])
	cd ml && .venv/bin/python scripts/train.py --smoke --epochs 1 && .venv/bin/python scripts/export.py --weights runs/smoke/weights/best.pt --version smoke --imgsz 160 --check

test: backend-test device-test bot-test ml-test web-lint web-unit ## Все проверки (кроме e2e)

seed: ## Демо-данные в dev-базу (db из infra-up)
	$(ENV_LOAD) && cd backend && .venv/bin/alembic upgrade head && .venv/bin/python -m app.seed

demo: ## Полный стек в Docker: db, minio, backend (миграции + seed), web, bot, симулятор устройства
	@test -f infra/.env || { cp infra/.env.example infra/.env && \
	  python3 infra/secrets_check.py --fix --with-device && echo "infra/.env создан из примера"; }
	@python3 infra/secrets_check.py --fix || true   # слабые JWT_SECRET / MINIO_ROOT_PASSWORD → случайные
	$(COMPOSE) --profile full up -d --build
	@echo "Ждём backend..." && until curl -sf http://localhost:8000/docs >/dev/null; do sleep 2; done
	@echo ""
	@echo "  Панель:        http://localhost:3000          admin@driverguard.kz / ADMIN_PASSWORD из infra/.env (пусто = admin123)"
	@echo "  PWA водителя:  http://localhost:3000/driver   +77012441832 / DRIVER_PIN из infra/.env (пусто = 1234)"
	@echo "  Swagger:       http://localhost:8000/docs"
	@echo "  MinIO:         http://localhost:9001          minioadmin / minioadmin"
	@echo "  Сценарий показа: docs/demo-script.md · логи: make demo-logs"

demo-down: ## Остановить демо (данные в volumes сохраняются; -v для полной очистки)
	$(COMPOSE) --profile full down

demo-logs: ## Логи демо-стека
	$(COMPOSE) --profile full logs -f --tail=50 backend device-sim bot

telegram-check: ## Проверить токен бота и показать chat_id писавших (токен из infra/.env)
	cd bot && set -a && . ../infra/.env && set +a && .venv/bin/python scripts/check_telegram.py

telegram-set-chat: ## Записать chat_id последнего написавшего боту в панель и прислать тест
	cd bot && set -a && . ../infra/.env && set +a && .venv/bin/python scripts/check_telegram.py --set-chat auto --send-test

bot-run: ## Запустить бота локально (backend на 8000, токен из infra/.env)
	cd bot && set -a && . ../infra/.env && set +a && .venv/bin/python main.py

device-camera: ## Устройство с веб-камерой на этом ноутбуке (окно со статусом)
	cd device && .venv/bin/python -m dg --source 0 --display --gps sim

device-sim: ## Симулятор устройства локально (без камеры)
	cd device && .venv/bin/python -m dg --simulate --speedup 5

ai-setup: ## Подключить ИИ-проверку фото одной командой: ключ → infra/.env → перезапуск backend → тест (make ai-setup KEY=sk-…)
	python3 infra/ai_setup.py $(if $(KEY),--key $(KEY),)

mentors: ## Учётки менторов/жюри: панель + водитель PWA + машина (make mentors N=40 ROLE=viewer OUT=mentors.csv)
	$(ENV_LOAD) && cd backend && .venv/bin/python scripts/mentors.py --count $(or $(N),3) --role $(or $(ROLE),coordinator) $(if $(OUT),--out $(OUT),)

mentors-docker: ## То же внутри контейнера backend (ноутбук без backend/.venv): make mentors-docker N=40 ROLE=viewer
	$(COMPOSE) --profile full exec backend python scripts/mentors.py --count $(or $(N),3) --role $(or $(ROLE),coordinator) --out /tmp/mentors.csv
	$(COMPOSE) --profile full cp backend:/tmp/mentors.csv ./mentors.csv && echo "Доступы сохранены в ./mentors.csv (не коммитить)"

load-test-docker: ## Нагрузочный тест внутри контейнера backend: make load-test-docker N=40 ADMINS=5 DURATION=60
	$(COMPOSE) --profile full exec backend python scripts/load_test.py --drivers $(or $(N),40) --admins $(or $(ADMINS),5) --duration $(or $(DURATION),60)

tunnel: ## Публичные HTTPS-ссылки для менторов (cloudflared) поверх запущенного `make demo`; Ctrl+C — закрыть
	python3 infra/tunnel.py --mode docker

web-dev-tunnel: ## Dev-сервер web с адресами backend из infra/.env (для `python infra/tunnel.py --mode dev`)
	$(ENV_LOAD) && cd web && npm run dev

secrets-check: ## Проверить infra/.env: слабые секреты и пароли по умолчанию (make secrets-check FIX=1 — заменить случайными)
	python3 infra/secrets_check.py $(if $(FIX),--fix,)

backup: ## Резервная копия PostgreSQL + MinIO из docker compose в backups/<дата> (с проверкой дампа)
	python3 infra/backup.py create --keep 10

backup-list: ## Список резервных копий
	python3 infra/backup.py list

backup-restore: ## Восстановить из копии: make backup-restore DIR=backups/<дата> (затирает текущие данные)
	python3 infra/backup.py restore $(DIR)

preflight: ## Готовность к показу: живой контур телефонов жюри (make preflight PASS='новый-пароль' N=40)
	$(ENV_LOAD) && cd backend && .venv/bin/python scripts/demo_preflight.py --api $(or $(API),http://localhost:8000/api/v1) --web $(or $(WEB),http://localhost:3000) $(if $(PASS),--admin-password '$(PASS)',) $(if $(N),--expect-mentors $(N),)

load-test: ## Нагрузочный тест: N водителей с камерой + админы (make load-test N=40 ADMINS=5 DURATION=60)
	$(ENV_LOAD) && cd backend && .venv/bin/python scripts/load_test.py --drivers $(or $(N),40) --admins $(or $(ADMINS),5) --duration $(or $(DURATION),60)

retrain-export: ## Очередь дообучения (ML-5): ложные срабатывания из панели → ml/data/incoming/<дата>/
	cd ml && .venv/bin/python scripts/retrain_queue.py --api http://localhost:8000/api/v1 --mark
