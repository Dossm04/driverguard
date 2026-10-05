# DriverGuard ML — датасет, обучение YOLOv8, реестр моделей, стенд (ML-1…ML-6)

Детектор нарушений для устройства: классы `phone`, `cigarette`, `seatbelt_on`, `seatbelt_off`
(→ события `phone`, `smoking`, `seatbelt`, DEV-8…DEV-10). До своей модели устройство работает
на COCO-классе «cell phone» (`scripts/export.py --coco`). Всё, что здесь, работает **без железа**:
CPU ноутбука или Colab; компиляция под Hailo (ML-3, шаг 2) — после приезда платы.

```
ml/
  dgml/            чистая логика (без torch): классы, разметка, сплит, датасет, реестр, метрики, ONNX-инференс, стенд
  scripts/         CLI: extract_frames, prepare_dataset, train, evaluate, export, registry, retrain_queue, bench_*
  notebooks/       DriverGuard_YOLOv8_Colab.ipynb — те же скрипты в Colab (GPU T4)
  models/          registry.json (в git) + violations_vN.onnx, calib_vN/ (вне git)
  data/            raw/<источник>/…, dataset/ (YOLO), incoming/ (очередь дообучения) — вне git
  runs/            прогоны ultralytics — вне git
  tests/           pytest без torch (сплит, ворота, реестр, декодер ONNX, стенд)
```

## Установка

```bash
cd ml && python -m venv .venv && . .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -e ".[dev]"            # numpy, opencv, pyyaml, requests, pytest, ruff
pip install -e ".[train]"          # + ultralytics (torch), onnx, onnxruntime — для train/evaluate/export
pytest -q && ruff check .
```

## Конвейер

| Шаг | ТЗ | Команда |
|---|---|---|
| Кадры из видео кабины | ML-1 | `python scripts/extract_frames.py cabin_ivanov.mp4 --session 2026-09-10-ivanov --out data/raw/cabin` (`--gray` для ИК) |
| Разметка | ML-1 | Roboflow/CVAT → экспорт **YOLO** (images/ + labels/ + data.yaml) в `data/raw/<источник>/` |
| Сборка датасета | ML-1 | `python scripts/prepare_dataset.py data/raw/cabin data/raw/roboflow-phone --out data/dataset --force` |
| Обучение | ML-2 | `python scripts/train.py --data data/dataset/data.yaml --epochs 100 --version v1` |
| Оценка | ML-2 | `python scripts/evaluate.py --weights runs/v1/weights/best.pt --split test --version v1 --video cabin_test.mp4` |
| Экспорт ONNX + калибровка | ML-3 | `python scripts/export.py --version v1 --calib-from data/dataset/images/val --check` |
| Реестр, привязка к устройству | ML-4 | `python scripts/registry.py list` · `python scripts/registry.py promote v1` |
| Очередь дообучения | ML-5 | `python scripts/retrain_queue.py --api http://localhost:8000/api/v1 --mark` → `data/incoming/<дата>/` |
| Стендовый протокол | ML-6 | `python scripts/bench_protocol.py --subjects 5` → CSV; `python scripts/bench_report.py protocol.csv --sqlite ../device/dg.sqlite` |

Smoke-проверка всего конвейера без данных и GPU (синтетика, 1–3 эпохи, CPU):

```bash
python scripts/train.py --smoke && python scripts/export.py --weights runs/smoke/weights/best.pt --version smoke --imgsz 160 --check
```

### Датасет (ML-1): что проверяет `prepare_dataset.py`

- **Сплит по сессиям.** Имя кадра `<источник>__<сессия>__000123.jpg` (сессия = человек + поездка);
  кадры одной сессии целиком уходят в train **или** val **или** test — утечки нет (`split.py`).
  Для чужих датасетов без такого имени сессия = папка.
- **Классы** источника (data.yaml/classes.txt) переводятся в наши по синонимам (`dgml/classes.py`);
  боксы лишних классов (person и т. п.) выбрасываются, кадры без боксов остаются негативами.
- **Grayscale-копии** 30 % train (`--gray-ratio`) — аугментация под ИК-камеру ночью.
- **Ворота:** ≥ 500 изображений на класс, ≥ 20 % собственной съёмки (источники `cabin*`, `own*`,
  `retrain*`), ≥ 5 % негативов, val/test не пусты, утечки нет. Отчёт — `data/dataset/report.json`,
  код выхода 2, если ворота не пройдены.

### Обучение и ворота выпуска (ML-2)

YOLOv8n, imgsz 640, аугментации HSV/поворот/масштаб/flip/mosaic. После обучения `best.pt` валидируется,
метрики и отпечаток датасета пишутся в `models/registry.json`. **Выпуск разрешён при mAP@50 ≥ 0.85**
на валидации; `evaluate.py` печатает confusion matrix и P/R по классам для ручного разбора и умеет
прогнать тест-видео из кабины (`--video`, CSV детекций по кадрам + mp4 с боксами).

### Экспорт и Hailo (ML-3)

`export.py` даёт ONNX (opset 11, статический вход 640×640 — формат, который принимает Hailo Dataflow
Compiler), калибровочный набор (`models/calib_vN/*.jpg` + `.npy`) и проверяет модель через onnxruntime.
После приезда AI HAT+: `hailomz compile yolov8n --ckpt models/violations_v1.onnx --calib-path models/calib_v1
--hw-arch hailo8l` → `registry.py set-hef v1 models/violations_v1.hef` (ШАГ 16 плана).

### Реестр версий (ML-4)

`models/registry.json`: версия, дата, коммит, отпечаток и размеры датасета, параметры обучения, метрики
(в т. ч. по классам), ворота, артефакты (pt/onnx/hef), заметки. `registry.py promote vN` копирует ONNX
в `device/models/` и прописывает в `device/config.yaml` `detector.model` и `device.model_version =
violations-vN` — устройство отправляет эту строку в backend (регистрация, события, heartbeat), панель
показывает её в карточке устройства.

### Цикл дообучения (ML-5)

Координатор помечает событие «ложное» → backend кладёт его в `retrain_queue` (BE-8).
`scripts/retrain_queue.py` забирает очередь (`GET /retrain-queue`), скачивает клипы, режет кадры ±1 с
вокруг момента события в `data/incoming/<дата>/<тип>/` с именами `retrain__<uuid>__NN.jpg` (сессия = событие),
и помечает элементы экспортированными. Дальше — разметка, `prepare_dataset.py … data/incoming/*` и новая версия.
Периодичность в пилоте — еженедельно.

### Стенд (ML-6, Приложение Г ТЗ)

`bench_protocol.py` генерирует протокол: 20 сценариев × день/ночь × 3 повтора × испытуемые, с ожидаемым
событием. Оператор заполняет время начала/конца каждого прогона; `bench_report.py` сопоставляет протокол
с событиями из SQLite устройства (или JSON/CSV из панели) и считает TP/FP/FN, precision/recall по типам
и условиям, задержку алерта, FPS — Markdown-отчёт для `docs/bench-protocol.md`. Подробнее — `docs/bench-protocol.md`.

## Colab

`notebooks/DriverGuard_YOLOv8_Colab.ipynb`: клонирует ветку (токен GitHub) или берёт загруженную папку
`ml/`, распаковывает zip с источниками из Google Drive и запускает те же скрипты. Артефакты
(`violations_vN.onnx`, `registry.json`) копируются обратно на Drive; `registry.json` коммитится в репозиторий.
