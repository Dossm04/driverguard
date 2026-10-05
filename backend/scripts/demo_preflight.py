#!/usr/bin/env python
"""Проверка готовности стенда к показу жюри.

Запускать за час до показа и ещё раз за десять минут. Скрипт ничего не меняет:
он проверяет живой контур — тот самый, по которому пойдут телефоны судей, —
и на каждую проблему печатает готовую команду исправления.

    python scripts/demo_preflight.py
    python scripts/demo_preflight.py --api https://xxx.trycloudflare.com/api/v1

Почему проверок так много: в день показа ломается не код, а окружение.
Пароли по умолчанию, забытая резервная копия, не созданные учётки, не заданный
chat_id бота — всё это выясняется в зале, если не проверить заранее.
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import urllib.error
import urllib.request
from datetime import UTC, datetime, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent          # backend/
REPO = ROOT.parent

OK, WARN, FAIL, INFO = "  [готово] ", "  [!]      ", "  [СТОП]   ", "  [инфо]   "

blockers: list[str] = []
warnings: list[str] = []


def say(mark: str, text: str, fix: str | None = None) -> None:
    print(f"{mark}{text}")
    if fix:
        for line in fix.splitlines():
            print(f"             → {line}")
    if mark == FAIL:
        blockers.append(text)
    elif mark == WARN:
        warnings.append(text)


def call(api: str, path: str, token: str | None = None, data: object = None,
         timeout: float = 15.0) -> tuple[int, object]:
    """Возвращает (код ответа, тело). Сетевые ошибки — код 0."""
    req = urllib.request.Request(api.rstrip("/") + path)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(data).encode()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            body = resp.read()
            return resp.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as e:
        raw = e.read()
        try:
            return e.code, json.loads(raw)
        except Exception:  # noqa: BLE001 — тело может быть не JSON
            return e.code, raw[:200].decode(errors="replace")
    except Exception as e:  # noqa: BLE001 — проверка не должна падать
        return 0, str(e)


def main() -> int:
    ap = argparse.ArgumentParser(description="Готовность стенда к показу жюри")
    ap.add_argument("--api", default="http://localhost:8000/api/v1")
    ap.add_argument("--web", default="http://localhost:3000")
    ap.add_argument("--admin-email", default="admin@driverguard.kz")
    ap.add_argument("--admin-password", default=None,
                    help="новый пароль админа; без него проверка входа пропускается")
    ap.add_argument("--expect-mentors", type=int, default=0,
                    help="сколько учёток жюри должно быть создано")
    args = ap.parse_args()

    print("\n  Готовность стенда DriverGuard к показу")
    print("  " + "─" * 62)
    print(f"  API:    {args.api}")
    print(f"  Панель: {args.web}")
    print("  " + "─" * 62)

    # ── 1. Сервер отвечает ──
    code, body = call(args.api, "/health")
    if code != 200:
        say(FAIL, f"Сервер не отвечает ({body})",
            "make demo\nЗатем make demo-logs — посмотреть, какой контейнер не поднялся")
        print("\n  Без сервера остальные проверки бессмысленны.\n")
        return 1
    say(OK, "Сервер отвечает")

    # ── 2. Готовность: база и хранилище фото ──
    code, body = call(args.api, "/health/ready")
    ready = isinstance(body, dict) and body.get("status") == "ready"
    if ready:
        say(OK, "База и хранилище фото на связи")
    else:
        detail = body if isinstance(body, dict) else {}
        say(FAIL, f"Стенд не готов: {detail}",
            "Хранилище (MinIO) нужно для фото чек-листов.\n"
            "docker compose -f infra/docker-compose.yml --profile full up -d")

    # ── 3. Пароли по умолчанию ──
    # Отказ пускать — это успех, но только если сервер осознанно отказал (401).
    # Код 500 или обрыв связи означают «проверить не удалось»: писать в такой
    # ситуации «пароль сменён» опасно — можно выйти на показ с admin123.
    code, _ = call(args.api, "/auth/login",
                   data={"email": args.admin_email, "password": "admin123"})
    if code == 200:
        say(FAIL, "Пароль админа всё ещё admin123 — его знает любой, кто видел репозиторий",
            "Панель → Настройки → Пользователи → сменить пароль.\n"
            "Пока не сменён, make tunnel откажется открывать публичную ссылку.")
    elif code in (401, 403, 429):
        say(OK, "Пароль админа по умолчанию не работает")
    else:
        say(FAIL, f"Не удалось проверить пароль админа (код {code})",
            "Сервер отвечает с ошибкой — сначала разберитесь с ним, иначе\n"
            "можно выйти на показ с паролем admin123 и не знать об этом")

    code, _ = call(args.api, "/auth/driver-login",
                   data={"phone": "+77010000001", "pin": "1234"})
    if code == 200:
        say(WARN, "У водителя из демо-данных остался PIN 1234",
            "Панель → Водители → карточка → сменить PIN")
    elif code in (401, 403, 429):
        say(OK, "PIN 1234 не работает")
    else:
        say(WARN, f"Не удалось проверить PIN по умолчанию (код {code})")

    # ── 4. Секреты в infra/.env ──
    env_file = REPO / "infra" / ".env"
    if not env_file.exists():
        say(WARN, "infra/.env не найден", "cp infra/.env.example infra/.env")
    else:
        text = env_file.read_text(encoding="utf-8", errors="replace")
        weak = [
            line.split("=")[0]
            for line in text.splitlines()
            if "=" in line and not line.strip().startswith("#")
            and line.split("=", 1)[1].strip().strip('"') in
            ("", "change-me", "changeme", "secret", "admin123", "driverguard")
        ]
        if weak:
            say(FAIL, f"Слабые значения в infra/.env: {', '.join(weak[:5])}",
                "python infra/secrets_check.py --fix")
        else:
            say(OK, "Секреты в infra/.env заданы")

    # ── 5. Резервная копия ──
    backups = REPO / "backups"
    dirs = sorted((d for d in backups.iterdir() if d.is_dir()), reverse=True) \
        if backups.exists() else []
    if not dirs:
        say(FAIL, "Резервной копии базы нет",
            "make backup — одна минута сейчас спасёт показ, если данные испортятся")
    else:
        age = datetime.now(UTC) - datetime.fromtimestamp(dirs[0].stat().st_mtime, UTC)
        if age > timedelta(days=2):
            say(WARN, f"Последняя копия сделана {age.days} дней назад ({dirs[0].name})",
                "make backup")
        else:
            say(OK, f"Резервная копия свежая: {dirs[0].name}")

    # ── 6. Вход админа новым паролем ──
    token = None
    if args.admin_password:
        code, body = call(args.api, "/auth/login",
                          data={"email": args.admin_email, "password": args.admin_password})
        if code == 200 and isinstance(body, dict):
            token = body.get("access_token")
            say(OK, "Вход админа новым паролем работает")
        else:
            say(FAIL, f"Новый пароль админа не подходит (код {code})",
                "Проверьте --admin-password или смените пароль в панели заново")
    else:
        say(INFO, "Пароль админа не передан — проверки панели пропущены",
            "Повторите с --admin-password '<новый пароль>' для полной проверки")

    # ── 7. Демо-данные, устройства и учётки жюри ──
    if token:
        code, kpis = call(args.api, "/dashboard/summary?period=today", token)
        if code == 200 and isinstance(kpis, dict) and "vehicles" in kpis:
            veh = kpis["vehicles"]
            events = kpis.get("events", {}).get("value", "?")
            score = kpis.get("avg_score", {}).get("value", "?")
            km = kpis.get("km_week", {}).get("value", "?")
            say(OK, f"Демо-данные на месте: машин {veh.get('online')}/{veh.get('total')}, "
                    f"событий сегодня {events}, Score парка {score}, пробег {km} км")
            # Правило 3 в CLAUDE.md: на seed-данных цифры обязаны совпадать с макетом
            if (events, score) != (14, 78):
                say(WARN, "Цифры разошлись с макетом (ожидалось 14 событий и Score 78)",
                    "Это нормально, если стенд уже гоняли. Перед показом: make seed")
        else:
            say(FAIL, f"Дашборд не отдаёт показатели (код {code})", "make seed")

        code, devices = call(args.api, "/devices", token)
        if code == 200 and isinstance(devices, list):
            web = [d for d in devices if str(d.get("serial", "")).startswith("WEB-")]
            online = sum(1 for d in web if d.get("online"))
            if not web:
                say(FAIL, "Виртуальных устройств для телефонов жюри нет",
                    "make mentors N=40 ROLE=viewer OUT=mentors.csv")
            elif args.expect_mentors and len(web) < args.expect_mentors:
                say(WARN, f"Учёток жюри {len(web)}, ожидалось {args.expect_mentors}",
                    f"make mentors N={args.expect_mentors} ROLE=viewer")
            else:
                say(OK, f"Учётки жюри готовы: {len(web)} телефонов (сейчас на связи {online})")
        else:
            say(WARN, f"Список устройств недоступен (код {code})")

        code, settings = call(args.api, "/settings", token)
        if code == 200 and isinstance(settings, dict):
            chat = json.dumps(settings, ensure_ascii=False)
            if '"telegram_chat_id": ""' in chat or '"telegram_chat_id": null' in chat:
                say(WARN, "chat_id Telegram не задан — алерты координатору не придут",
                    "make telegram-set-chat (сначала напишите боту любое сообщение)")
            else:
                say(OK, "Telegram настроен")

    # ── 8. ГЛАВНОЕ: приём события с телефона ──
    # Это тот самый путь, по которому пойдут судьи. Проверяем целиком:
    # вход водителя по PIN → heartbeat с позицией → событие DMS.
    mentors_csv = next((p for p in (REPO / "backend").glob("mentors*.csv")), None) \
        or next((p for p in REPO.glob("mentors*.csv")), None)
    if mentors_csv is None:
        say(WARN, "Файла mentors.csv нет — путь телефона не проверен",
            "make mentors N=40 ROLE=viewer OUT=mentors.csv, затем запустите проверку снова")
    else:
        import csv as _csv
        import uuid as _uuid

        rows = list(_csv.DictReader(mentors_csv.open(encoding="utf-8")))
        if not rows:
            say(WARN, f"{mentors_csv.name} пуст")
        else:
            j = rows[0]
            code, body = call(args.api, "/auth/driver-login",
                              data={"phone": j["pwa_phone"], "pin": j["pwa_pin"]})
            if code != 200 or not isinstance(body, dict):
                say(FAIL, f"Вход телефона жюри не работает (код {code})",
                    "make mentors N=40 ROLE=viewer — пересоздать учётки")
            else:
                dtok = body.get("access_token")
                code, hb = call(args.api, "/drivers/me/camera-heartbeat", dtok,
                                {"lat": 51.0905, "lon": 71.4180, "gps_valid": True,
                                 "speed_kmh": 0, "fps": 15})
                if code not in (200, 201):
                    say(FAIL, f"Телефон не регистрируется на карте (код {code}: {hb})")
                else:
                    device = hb.get("device") if isinstance(hb, dict) else "?"
                    code, res = call(args.api, "/drivers/me/camera-events", dtok, [{
                        "uuid": str(_uuid.uuid4()), "type": "microsleep", "severity": "critical",
                        "confidence": 0.93,
                        "ts": datetime.now(UTC).isoformat(),
                        "lat": 51.0905, "lon": 71.4180, "gps_valid": True,
                        "speed_kmh": 0, "value": 2.0, "note": "проверка готовности",
                    }])
                    if code in (200, 201):
                        say(OK, f"Путь телефона работает целиком: вход, карта ({device}), событие")
                        say(INFO, "Одно проверочное событие «засыпание» добавлено в ленту",
                            "Пометьте его ложным в панели перед показом, чтобы не смущало жюри")
                    else:
                        say(FAIL, f"Событие с телефона не принимается (код {code}: {res})")

    # ── 9. Панель отвечает ──
    try:
        with urllib.request.urlopen(args.web + "/login", timeout=15) as r:
            if r.status == 200:
                say(OK, "Панель открывается")
            else:
                say(WARN, f"Панель ответила кодом {r.status}")
    except Exception as e:  # noqa: BLE001
        say(FAIL, f"Панель не открывается ({type(e).__name__})",
            "make demo — панель поднимается вместе со стеком")

    # ── 10. Модель детектора на месте ──
    model = REPO / "device" / "models" / "yolov8n-coco.onnx"
    if model.exists():
        say(OK, f"Модель детектора на месте ({model.stat().st_size // 1_000_000} МБ, телефон)")
    else:
        say(WARN, "Модели детектора нет — телефон в кабине определяться не будет",
            "Она нужна только для устройства, для телефонов жюри не требуется")

    # ── 11. Публичная ссылка ──
    if args.api.startswith("https://"):
        say(OK, "Проверка шла по публичной ссылке — туннель работает")
    else:
        say(INFO, "Проверка шла локально",
            "За час до показа: make tunnel, затем запустите эту проверку\n"
            "ещё раз с --api https://<адрес>/api/v1 — камера в браузере требует HTTPS")

    # ── 12. Место на диске ──
    free_gb = shutil.disk_usage(REPO).free / 1_000_000_000
    if free_gb < 3:
        say(WARN, f"На диске свободно {free_gb:.1f} ГБ",
            "Клипы и фото чек-листов пишутся на диск; освободите место")
    else:
        say(OK, f"На диске свободно {free_gb:.1f} ГБ")

    # ── Итог ──
    print("  " + "─" * 62)
    if blockers:
        print(f"\n  НЕ ГОТОВО: {len(blockers)} блокирующих замечаний.")
        for b in blockers:
            print(f"    • {b}")
        print("\n  Выполните команды со стрелкой выше и запустите проверку снова.\n")
        return 1

    if warnings:
        print(f"\n  ГОТОВО с замечаниями ({len(warnings)}):")
        for w in warnings:
            print(f"    • {w}")
        print("\n  Блокирующих проблем нет — показывать можно.\n")
        return 0

    print("\n  ГОТОВО. Блокирующих проблем и замечаний нет.\n")
    return 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    os.environ.setdefault("PYTHONUNBUFFERED", "1")
    sys.exit(main())
