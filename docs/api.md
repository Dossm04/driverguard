# API DriverGuard

Источник истины — OpenAPI: при поднятом backend открой `http://localhost:8000/docs`
(Swagger) или `http://localhost:8000/openapi.json`. Базовый путь — `/api/v1`.
Фронтенд использует только эндпоинты из этого списка (правило CLAUDE.md «Не выдумывать
эндпоинты»).

## Аутентификация (BE-1)

| Метод | Путь | Кто | Описание |
|---|---|---|---|
| POST | /auth/login | — | Email + пароль → access/refresh JWT (админ/координатор) |
| POST | /auth/driver-login | — | Телефон + PIN (лимит 5 попыток / 15 мин) → JWT водителя |
| POST | /auth/device | — | serial + secret → долгоживущий device-токен |
| POST | /auth/refresh | — | refresh-токен → новая пара токенов |

Дальше все запросы — с заголовком `Authorization: Bearer <token>`.

## Справочники (BE-2) — роли admin/coordinator
| PATCH | /drivers/{id} (vehicle_id) | admin, coordinator | Закрепить/снять машину: vehicle_id — свободная машина или null |
| POST/DELETE | /drivers/{id}/photo | admin, coordinator | Фото водителя (JPEG/PNG/WebP ≤5 МБ) в бакет photos; в ответах — presigned photo_url |

| Метод | Путь | Описание |
|---|---|---|
| GET | /depots | Список депо |
| GET/POST/PATCH | /drivers, /drivers/{id} | Водители (+создание учётки с PIN) |
| GET/POST/PATCH | /vehicles, /vehicles/{id} | Машины (закрепление водителя) |
| GET/POST/PATCH | /devices, /devices/{id} | Устройства (`online` = last_seen ≤ 5 мин) |

## Рейсы (BE-3)

| Метод | Путь | Описание |
|---|---|---|
| POST | /trips/start | {driver_id, vehicle_id, device_id?} → активный рейс (409, если уже есть) |
| POST | /trips/{id}/stop | Завершить рейс |
| POST | /trips/{id}/breaks | Перерыв с причиной (устал/туалет/еда/заправка/другое) |
| POST | /trips/{id}/breaks/end | Закрыть открытый перерыв |
| GET | /trips | Фильтры driver_id, trip_status; сортировка по началу |

## События (BE-4, BE-5)

| Метод | Путь | Описание |
|---|---|---|
| POST | /events | Батч ≤100 событий (Приложение Б ТЗ), **идемпотентный upsert по uuid** — повторная отправка не создаёт дубликатов. Отправитель: device-токен или admin/coordinator; без trip_id событие привязывается к активному рейсу водителя |
| GET | /events | Фильтры: type, driver_id, status, severity, ts_from, ts_to; пагинация page/page_size; в ответе имя водителя, номер машины |
| GET | /events/{uuid} | Одно событие |
| POST | /events/{uuid}/clip-upload-url | Presigned PUT в MinIO (`clips/{device}/{yyyy-mm}/{uuid}.mp4`, TTL 10 мин) |
| GET | /events/{uuid}/clip-url | Presigned-ссылка на просмотр клипа (модалка событий, бот) — 404, если клипа нет |

Формат события устройства — Приложение Б ТЗ (`reference/DriverGuard_ТЗ_v1.0.md`).

## Review событий (BE-8)

| Метод | Путь | Описание |
|---|---|---|
| POST | /events/{uuid}/review | {status: confirmed \| false_positive, comment?: ≤200 — попадает в audit_log (бот пишет «Telegram: имя»)}, роли admin/coordinator. «Ложное» возвращает баллы водителю, пишет кадр в retrain_queue; всё — в audit_log (SEC-4) |
| GET | /retrain-queue?exported=false&limit=200&internal=false | Очередь дообучения (ML-5): элементы с типом/временем события, водителем, машиной, версией модели и presigned-ссылкой на клип; роли admin/coordinator. `ml/scripts/retrain_queue.py` забирает её и режет кадры |
| POST | /retrain-queue/mark-exported | {ids: [...]} → exported_at = сейчас (повторно — no-op), запись `retrain_export` в audit_log |

## Дашборд (BE-9)

| Метод | Путь | Описание |
|---|---|---|
| GET | /dashboard/summary?period=today\|7d\|30d | 6 KPI с дельтами: машины 5/6, события 14 (+3), критические 24ч 3, средний Score 78 (−2, цель 80), пробег 12 480 (+4.2%), аптайм 98.2%. На seed — ровно цифры Figma; границы «сегодня/вчера» — по APP_TZ (Asia/Almaty) |
| GET | /dashboard/events-by-day?days=7 | По дням: critical/warning/info |
| GET | /dashboard/events-by-type?days=7 | Типы с count и share_pct (speeding = 27% на seed) |
| GET | /dashboard/critical-latest?limit=3 | Последние критические (EventOut) |
| GET | /dashboard/red-zone | Score<60 по 30-дневному окну + поездок за 30 дней |

Окна скоринга: KPI «Средний Score» — окно периода (today → 7 дней); «красная зона» —
30 дней (docs/decisions.md).

## Лидерборд (BE-7) и профиль

| Метод | Путь | Описание |
|---|---|---|
| GET | /leaderboard?period=7\|30 | rows: rank, score, zone, Δ к прошлому периоду, streak, км, событий, бейджи; depots: командный зачёт |
| GET | /drivers/{id}/profile | Шапка, Score+серия, график 8 недель, разбивка 30д, события, рейсы, обучения |
| GET | /drivers/me | driver | Профиль текущего водителя для PWA: как /drivers/{id}/profile + device {serial, online, last_seen}, active_trip {id, started_at, distance_km, break, last_break_end}, last_checklist {verdict, status, created_at}, retention (сроки хранения, SEC-5), vehicle.id |
| POST | /drivers/{id}/sos | driver (свой), admin, coordinator | SOS из PWA (APP-5): {reason: Поломка\|ДТП\|Здоровье\|Другое, lat?, lon?, gps_valid?, comment?} → критическое событие sos (context.reason), WS-рассылка, 201 |
| POST | /drivers/{id}/trainings/{item_id}/complete | driver (свой), admin, coordinator | Отметка прохождения урока (APP-6) → status completed |
| GET | /trainings | любой авторизованный | Каталог 30-секундных уроков {id, title, duration_s, url} |
| POST | /drivers/{id}/trainings | Назначить микрообучение (по умолчанию «Управление усталостью») |
| POST | /drivers/me/camera-events | driver | События DMS из браузера телефона (PWA «Камера»): до 20 шт., типы microsleep/fatigue/head_nod/distraction/camera_sabotage, идемпотентно по uuid; driver_id — из токена, context.source = pwa_camera; устройство машины (или виртуальное WEB-<id>) отмечается онлайн |
| POST | /drivers/me/camera-heartbeat | driver | {lat?, lon?, gps_valid?, speed_kmh?, fps?} раз в 15 с: устройство онлайн, позиция телефона на Live-карте (живёт 2 мин) |

## WebSocket /ws/live (BE-16)

`ws://host/ws/live?token=<access>` — сообщения:
`{"type":"positions", vehicles:[{vehicle_id, plate, driver_name, lat, lon, speed_kmh, status, score}]}`
каждые 2 с (демо-симулятор движения по М-36; выключается `DEMO_MODE=false`),
`{"type":"event", event:{…}}` при новых событиях, `{"type":"event_review", …}` после review.
Статусы маркеров: ok / warn / danger (зоны Score) / offline (нет heartbeat 5 мин).

## Демо-данные

`cd backend && python -m app.seed` — приводит БД к эталону Figma (цифры проверяются
самопроверкой seed'а): admin@driverguard.kz / admin123, PIN всех водителей 1234,
секрет устройства DG-000N — `device-secret-N`.

_Разделы «Чек-листы» — в ШАГ 10, «Отчёты/Настройки» — в ШАГ 11._

## Чек-листы (BE-10, ШАГ 10)

| Метод | Путь | Роли | Описание |
|---|---|---|---|
| GET | `/checklists/items` | все авторизованные | Каталог анкеты v2 (42 пункта: id, секция, критичность, способ, ai_key) |
| GET | `/checklists/slots` | все авторизованные | Действующие ракурсы фото (стандартные + добавленные парком, с подсказками) |
| GET | `/checklists/template` | admin, coordinator, viewer | Полный шаблон: ракурсы и пункты с учётом настроек парка (`/settings/checklist`) |
| GET | `/checklists/ai-status` | admin, coordinator, viewer | Провайдер ИИ: provider (openai_compat/gemini/mock), configured, model, host — без ключей |
| POST | `/checklists/ai-test` | admin | Тестовый запрос к провайдеру с замером задержки: {ok, provider, model, latency_ms, verdict} или {ok:false, error} |
| POST | `/checklists` | driver (свой), admin/coordinator (`driver_id`) | multipart: 7 фото по слотам `front_lights, rear_lights, left_side, right_side, tires, windshield, under_engine` (JPEG/PNG/WebP ≤4 МБ), `answers` — JSON анкеты, `trip_id`. Фото → MinIO `photos`, ИИ-вердикт (Gemini или mock без ключа), итог = худшее из фото и анкеты. 422 — состав/анкета, 502 — ИИ не ответил валидно |
| GET | `/checklists` | admin/coordinator/viewer | Фильтры `status`, `verdict`, `driver_id`; пагинация; в каждой карточке — presigned-ссылки фото (10 мин), теги ИИ по слотам, таблица пунктов, замечания анкеты, расхождения |
| GET | `/checklists/{id}` | сотрудники, водитель — свой | Карточка осмотра |
| POST | `/checklists/{id}/approve` | admin/coordinator | `{action: approve \| approve_with_note \| send_to_repair, note?}`. `approve` только при «допущен» (иначе 409), `approve_with_note` требует `note`; повторно — 409; аудит |

Переменные: `AI_PROVIDER=auto|gemini|mock`, `GEMINI_API_KEY`, `GEMINI_MODEL`, `GEMINI_THINKING_LEVEL`.

## Отчёты (BE-14)

| Метод | Путь | Роли | Описание |
|---|---|---|---|
| GET | /reports/summary?period=today\|7d\|30d&depot_id= (today — календарный день по APP_TZ, Asia/Almaty) | admin, coordinator, viewer | Сводка: totals, by_type, by_driver, score_trend (8 недель; avg_score = null для недели без событий), risky_segments (топ-5 кластеров), trips (≤50) |
| GET | /reports/export.csv?period&depot_id | те же | CSV (UTF-8 BOM, «;») со всеми разделами сводки |
| GET | /reports/export.pdf?period&depot_id | те же | PDF (reportlab, DejaVu Sans, кириллица); 503 без шрифта |

## Настройки и администрирование (BE-15, WEB-9)

| Метод | Путь | Роли | Описание |
|---|---|---|---|
| GET | /settings, /settings/{key} | admin, coordinator, viewer | Разделы scoring / thresholds / notifications / retention с version и автором |
| PUT | /settings/{key} | admin | Валидация по схеме раздела, version+1, аудит `settings_update` |
| POST | /settings/scoring/preview | admin, coordinator, viewer | Недельный Score водителей при предложенных весах — без сохранения |
| GET/POST | /users | admin | Пользователи панели; создание (email, роль, пароль ≥8) |
| PATCH | /users/{id} | admin | Имя/роль/пароль; своя роль и учётки водителей — 409 |
| — | `/users` (поле) | admin | В ответе `last_seen` (последний авторизованный запрос, не чаще раза в минуту) и `online` (≤5 мин) — «кто сейчас в системе» |
| GET/PUT | /settings/checklist | чтение: staff; запись: admin | Шаблон чек-листа парка: hidden_slots, custom_slots, hidden_items, item_overrides, custom_items — только отличия от каталога v2 |
| POST | /devices/{id}/heartbeat | device-токен или сотрудник | Телеметрия раз в 10 мин (DEV-23): fw_version, model_version (версия детектора, ML-4), temp_c, fps, disk_free, gps_fix, net, trip_km_delta (км с прошлого heartbeat → прибавляются к активному рейсу машины); обновляет last_seen (online ≤ 5 мин) |
| GET | /devices/{id}/config | device-токен, сотрудники | Пороги устройства (thresholds + thresholds_version), scoring_version, reboot: bool — устройство при true перезапускается, статус сбрасывается в active |
| POST | /devices/{id}/reboot | admin, coordinator | Команда перезагрузки (status=reboot_requested), доставляется через GET /devices/{id}/config (`reboot: true`) |


| GET | /health | — | Проверка живости backend: {status: ok} |
