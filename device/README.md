# DriverGuard device — софт DMS в кабине (ШАГ 14)

Ловит микросон, усталость (PERCLOS, зевота), клевок головой, отвлечение, антисаботаж и
превышение скорости по камере и GPS, а через детектор нарушений (YOLOv8-ONNX) — телефон, курение
и ремень; пишет клипы событий, копит всё в SQLite и отправляет на backend, когда есть сеть.
Работает на ноутбуке уже сейчас, на Raspberry Pi 5 — тот же код.

```
камера → capture → dms (MediaPipe Face Landmarker, blendshapes) → rules (машина состояний)
        ↘ detector (поток: YOLOv8-ONNX, телефон/сигарета/ремень) ↗   ↘ alerts (двойной сигнал / сирена)
        ↘ recorder (кольцевой буфер 20 с → клип 10+5 с)
                              store (SQLite: события, heartbeat, конфиг) → sync (батчи, presigned-клипы, backoff)
```

## Запуск на ноутбуке

```bash
cd device
python3 -m venv .venv && .venv/bin/pip install -e ".[dev]"      # + ".[sound]" для звука
.venv/bin/python -m dg --source 0 --display                   # веб-камера, окно со статусом
.venv/bin/python -m dg --source clip.mp4 --no-sync            # прогон записи, только SQLite
.venv/bin/python -m dg --simulate --speedup 10                # без камеры: события + трасса
```

На Debian/Ubuntu MediaPipe требует системные GL-библиотеки: `sudo apt install libgl1 libegl1 libgles2 libglib2.0-0`.
При первом запуске с камерой скачивается модель `face_landmarker.task` (~3.6 МБ) в
`~/.cache/driverguard/`. Без интернета положите файл туда сами или задайте `DG_MODEL_PATH`.

Параметры: `--api URL`, `--serial`, `--secret` (или `DG_API_URL` / `DG_SERIAL` / `DG_SECRET`),
`--gps none|gpsd|sim`, `--no-sound`, `--duration N`, `--seed N`, `--config path.yaml`,
`--detector auto|on|off`, `--yolo path.onnx`.
Seed backend знает устройства `DG-0001…DG-0006` с секретами `device-secret-N`.

## Что считается событием (config.yaml, те же пороги, что в reference/driverguard_demo.html)

| Событие | Правило | Уровень алерта |
|---|---|---|
| `microsleep` | eyeBlink ≥ 0.5 (подтверждение EAR) непрерывно ≥ 1.5 с | 2 — сирена до открытия глаз |
| `fatigue` | PERCLOS ≥ 20 % за 60 с (не чаще 1/30 с) или ≥ 3 зевоты за 10 мин | 1 |
| `head_nod` | наклон головы выше калиброванной базы ≥ 2 с | 1 |
| `distraction` | поворот головы от дороги ≥ 8 с при > 20 км/ч (≥ 15 с — critical) | 1 |
| `camera_sabotage` | лицо не видно ≥ 5 мин при движении (≥ 3 с — локальное предупреждение) | 2 |
| `speeding` | скорость выше лимита профиля (90 трасса / 60 город) дольше 10 с, value = превышение | 1 |
| `phone` | телефон у лица (детектор) с conf ≥ 0.6 дольше 2 с при > 5 км/ч; сирена — при > 60 км/ч | 2 |
| `smoking` | сигарета/вейп у лица (детектор) дольше 3 с | 1 |
| `seatbelt` | ремень не пристёгнут (детектор, **beta**: `context.beta=true`) дольше 30 с при > 20 км/ч, один раз до пристёгивания | 1 |

Антидребезг: состояние засчитывается после `CONFIRM_FRAMES` кадров подряд; cooldown на тип
30 с (микросон — 5 с на новый эпизод); события с confidence < 0.6 не отправляются.
Калибровка — первые 60 кадров с лицом (персональная база наклона, поворота и EAR).
Пороги обновляются с backend через `GET /devices/{id}/config` (панель → Настройки → Пороги)
и кэшируются в SQLite.

## Детектор нарушений (DEV-8…DEV-10, ML-4)

`dg/detector.py` гоняет YOLOv8-ONNX через onnxruntime на CPU в отдельном потоке (последний кадр,
не чаще `detector.interval_ms`), главный цикл MediaPipe не ждёт. До своей модели используется COCO
`models/yolov8n-coco.onnx` (класс «cell phone»; ~40 мс на кадр на ноутбуке, ~300 мс на Pi 5 CPU);
своя модель с классами phone/cigarette/seatbelt_on/seatbelt_off приходит из `ml/`:
`python ml/scripts/registry.py promote vN` кладёт ONNX в `models/` и меняет `detector.model` и
`device.model_version` в `config.yaml`. Версия модели (из метаданных ONNX) уходит в backend в heartbeat
и событиях — панель показывает её в карточке устройства (ML-4).

```bash
.venv/bin/pip install -e ".[yolo]"                       # onnxruntime
.venv/bin/python -m dg --source 0 --display --gps sim     # detector.enabled: auto — включится сам
.venv/bin/python -m dg --source 0 --detector off          # только DMS
```

Телефон и сигарета засчитываются только в зоне «у лица» (бокс лица MediaPipe × `near_face`), поэтому
телефон на панели или водитель, вышедший из кабины, событий не дают (Приложение Г, сценарии 9, 10, 20).
Ремень — класс в статусе beta: событие помечается `context.beta=true`; пока precision < 85 %, вес
`seatbelt` в Настройках → Пороги и веса можно поставить 0. Без onnxruntime или файла модели устройство
работает как раньше (в логе «работаем без детектора»), `--detector on` в этом случае — ошибка.

## Данные и синхронизация

- `dg.sqlite`: `events` (uuid, type, severity, ts, lat, lon, gps_valid, speed, confidence,
  value, context, clip_path, status_sent, clip_sent), `heartbeats`, `config`.
- Клипы: `clips/<uuid>.mp4`, 640×480, libx264 ultrafast через ffmpeg (если есть в PATH),
  иначе mp4v средствами OpenCV.
- Sync каждые 30 с: `POST /events` батчами ≤ 100 (идемпотентно по uuid) → presigned PUT
  клипов → heartbeat (в т.ч. `trip_km_delta` — пробег по GPS с прошлого heartbeat, backend
  прибавляет его к активному рейсу машины) → конфиг. Без сети — экспоненциальный повтор 30 с → 10 мин, всё
  копится локально и уходит после появления связи (KPI-5).

Проверка сценария «авиарежим → накопление → сеть → доставка»:

```bash
.venv/bin/python -m dg --simulate --speedup 20 --api http://localhost:9999/api/v1 --duration 60   # backend недоступен
.venv/bin/python -c "from dg.store import Store; print(Store('dg.sqlite').counts())"              # pending > 0
.venv/bin/python -m dg --simulate --speedup 20 --duration 40                                       # backend поднят → pending 0
```

## Тесты

```bash
.venv/bin/pytest -q      # машина состояний (микросон 1.0 с — нет, 1.6 с — да; моргание — не микросон),
                         # SQLite-очередь и sync с фейковым backend, кольцевой буфер, симулятор, конфиг
.venv/bin/ruff check .
```

## Raspberry Pi 5 (+ Hailo — ШАГ 16)

```bash
sudo apt install -y python3-venv ffmpeg gpsd gpsd-clients libgl1 libegl1 libgles2 libglib2.0-0
sudo useradd -r -s /usr/sbin/nologin driverguard
sudo mkdir -p /opt/driverguard /etc/driverguard && sudo cp -r device /opt/driverguard/
cd /opt/driverguard/device && python3 -m venv .venv && .venv/bin/pip install -e .
sudo cp config.yaml /etc/driverguard/config.yaml && sudo cp systemd/device.env.example /etc/driverguard/device.env
sudo cp systemd/driverguard-device.service /etc/systemd/system/
sudo systemctl enable --now driverguard-device
journalctl -u driverguard-device -f
```

Отредактируйте `/etc/driverguard/device.env` (serial, secret, URL backend). Сервис работает от
пользователя `driverguard` в `/var/lib/driverguard` (там же `dg.sqlite`, `clips/`, кэш модели);
группы `video`/`audio` дают доступ к камере и звуку. Клавиша `c` в окне `--display` — повторная
калибровка (DEV-14); она же выполняется автоматически, когда лицо вернулось после долгого отсутствия. Команда
«Перезагрузить» из панели приходит через `/config`, процесс завершается с кодом 3, systemd
перезапускает его. Для стенда без камеры есть `driverguard-simulate.service`.

Камера: UVC ИК-камера 640×480@30 с подсветкой 850 нм (DEV-1); на Pi 5 кодирование клипов
программное (libx264 ultrafast). Детектор нарушений на Pi 5 без Hailo работает на CPU
(`detector.interval_ms: 500`); перенос модели на Hailo (.hef из `ml/scripts/export.py`) — ШАГ 16.

## Жесты рук (телефон, курение) без обученной модели

Пока в `models/` нет YOLO-детектора, телефон у уха и сигарета у рта определяются по точкам руки
(MediaPipe Hand Landmarker, `dg/gestures.py`, та же математика в PWA). Модель `hand_landmarker.task`
скачивается в `~/.cache/driverguard` (или `DG_HAND_MODEL_PATH`). `DG_GESTURES=off` — отключить.
Ремень жестами не определить — только детектор из `ml/`.
