#!/usr/bin/env python
"""Предполётная проверка стенда перед показом жюри.

Одна команда вместо десяти проверок по памяти. Запускать дважды: накануне
и за пятнадцать минут до выхода.

    python infra/showtime.py                      проверить всё
    python infra/showtime.py --url https://xxx.trycloudflare.com
    python infra/showtime.py --qr                 показать QR прямо в терминале
    python infra/showtime.py --watch              следить, кто подключился

Скрипт ничего не меняет: только проверяет и говорит, что делать.
Задача — чтобы в зале не выяснилось, что забыли сменить пароль
или не создали учётки.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

OK, WARN, FAIL, INFO = "  [готово] ", "  [!]      ", "  [СТОП]   ", "  [инфо]   "
blockers: list[str] = []
warnings_: list[str] = []


def say(mark: str, text: str, fix: str | None = None) -> None:
    print(f"{mark}{text}")
    if fix:
        for line in fix.splitlines():
            print(f"             → {line}")
    if mark == FAIL:
        blockers.append(text)
    elif mark == WARN:
        warnings_.append(text)


def api(base: str, path: str, token: str | None = None, data: dict | None = None,
        timeout: float = 10) -> tuple[int, object]:
    """Возвращает (код ответа, тело). Сетевые ошибки — код 0."""
    req = urllib.request.Request(base.rstrip("/") + path)
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    if data is not None:
        req.add_header("Content-Type", "application/json")
        req.data = json.dumps(data).encode()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read()
            return r.status, (json.loads(body) if body else None)
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"null")
        except Exception:
            return e.code, None
    except Exception:
        return 0, None


# ─────────────────────────── Проверки ───────────────────────────

def check_backend(api_url: str) -> bool:
    code, body = api(api_url, "/api/v1/health")
    if code != 200:
        say(FAIL, f"Сервер не отвечает: {api_url}",
            "make demo\nЕсли уже запущен — make demo-logs, смотрите какой контейнер упал")
        return False
    say(OK, f"Сервер отвечает: {api_url}")

    code, body = api(api_url, "/api/v1/health/ready")
    if code == 200:
        say(OK, "Готовность: база и хранилище на месте")
    else:
        detail = body if isinstance(body, dict) else {}
        broken = [k for k, v in detail.items() if v not in ("ok", "not_ready")]
        say(FAIL, f"Готовность не подтверждена: {detail or 'нет ответа'}",
            "Чаще всего не поднялось хранилище MinIO — без него не откроются фото чек-листов.\n"
            "make demo-logs minio")
    return True


def check_default_passwords(api_url: str) -> str | None:
    """Пытаемся войти паролем по умолчанию. Если получилось — это дыра."""
    code, body = api(api_url, "/api/v1/auth/login",
                     data={"email": "admin@driverguard.kz", "password": "admin123"})
    if code == 200:
        say(FAIL, "Пароль администратора по умолчанию всё ещё работает",
            "Панель → Настройки → Пользователи → сменить пароль.\n"
            "Пока не сменён, публичную ссылку открывать нельзя: admin123 знает любой,\n"
            "кто видел репозиторий.")
        return body.get("access_token") if isinstance(body, dict) else None
    say(OK, "Пароль администратора сменён")
    return None


def admin_token(api_url: str, email: str, password: str) -> str | None:
    code, body = api(api_url, "/api/v1/auth/login", data={"email": email, "password": password})
    if code == 200 and isinstance(body, dict):
        return body.get("access_token")
    say(WARN, "Не удалось войти под администратором для глубоких проверок",
        "Передайте текущие данные: --email admin@… --password ***")
    return None


def check_mentors(api_url: str, token: str, need: int) -> None:
    code, body = api(api_url, "/api/v1/drivers", token)
    if code != 200 or not isinstance(body, list):
        say(WARN, "Список водителей не прочитан — пропускаю проверку учёток жюри")
        return

    mentors = [d for d in body if "ентор" in str(d.get("name", ""))]
    if not mentors:
        say(FAIL, "Учёток для жюри нет",
            f"make mentors N={need} ROLE=viewer OUT=mentors.csv")
        return
    if len(mentors) < need:
        say(WARN, f"Учёток жюри: {len(mentors)}, планировали {need}",
            f"make mentors N={need} ROLE=viewer OUT=mentors.csv")
    else:
        say(OK, f"Учёток жюри: {len(mentors)}")

    csv = ROOT / "mentors.csv"
    if csv.exists():
        say(OK, f"Файл с доступами готов: {csv}")
    else:
        say(WARN, "Файла mentors.csv нет рядом — раздавать нечего",
            f"make mentors N={need} ROLE=viewer OUT=mentors.csv")


def check_devices(api_url: str, token: str) -> None:
    code, body = api(api_url, "/api/v1/devices", token)
    if code != 200 or not isinstance(body, list):
        return
    web = [d for d in body if str(d.get("serial", "")).startswith("WEB-M")]
    online = sum(1 for d in web if d.get("online"))
    if not web:
        say(WARN, "Виртуальных устройств для телефонов жюри пока нет",
            "Они создаются вместе с учётками: make mentors N=40")
    else:
        say(INFO, f"Телефонов-устройств заведено: {len(web)}, сейчас на связи: {online}")


def check_backup() -> None:
    backups = ROOT / "backups"
    if not backups.exists() or not any(backups.iterdir()):
        say(FAIL, "Резервной копии базы нет",
            "make backup\nОдна минута сейчас спасёт показ, если данные испортятся.")
        return
    latest = max((p for p in backups.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime,
                 default=None)
    if latest is None:
        say(WARN, "Папка backups пуста", "make backup")
        return
    age_h = (time.time() - latest.stat().st_mtime) / 3600
    if age_h > 48:
        say(WARN, f"Последняя копия старше двух суток ({latest.name})", "make backup")
    else:
        say(OK, f"Резервная копия свежая: {latest.name}")


def check_secrets() -> None:
    env = ROOT / "infra" / ".env"
    if not env.exists():
        say(WARN, "infra/.env не найден — проверьте, откуда стенд берёт секреты")
        return
    text = env.read_text(encoding="utf-8", errors="replace")
    weak = []
    for line in text.splitlines():
        if "=" not in line or line.strip().startswith("#"):
            continue
        key, _, value = line.partition("=")
        key, value = key.strip(), value.strip().strip("'\"")
        if key.endswith(("SECRET", "PASSWORD", "TOKEN")) and value:
            if len(value) < 24 or value.lower() in {"change-me", "secret", "password", "admin123"}:
                weak.append(key)
    if weak:
        say(FAIL, f"Слабые секреты в infra/.env: {', '.join(weak)}",
            "python infra/secrets_check.py --fix  (затем перезапустить стенд)")
    else:
        say(OK, "Секреты в infra/.env выглядят надёжно")


def check_public_url(url: str) -> None:
    """Публичная ссылка — единственный путь, по которому камера включится."""
    if not url:
        say(WARN, "Публичная ссылка не передана — проверьте её отдельно",
            "make tunnel, затем python infra/showtime.py --url https://…")
        return
    if not url.startswith("https://"):
        say(FAIL, "Ссылка не по HTTPS — браузер телефона не даст доступ к камере",
            "Нужен именно адрес туннеля, а не локальный IP")
        return
    code, _ = api(url, "/", timeout=15)
    if code == 0:
        say(FAIL, f"Публичная ссылка не открывается: {url}",
            "Перезапустите make tunnel. Адреса меняются при каждом запуске —\n"
            "не забудьте перевыпустить QR-код.")
    else:
        say(OK, f"Публичная ссылка отвечает: {url}")


# ─────────────────────────── QR ───────────────────────────

def show_qr(link: str) -> None:
    try:
        import qrcode
    except ImportError:
        say(WARN, "Библиотека qrcode не установлена — QR не нарисую",
            "pip install qrcode\nИли сделайте QR любым онлайн-генератором по ссылке ниже.")
        print(f"\n  Ссылка для жюри: {link}\n")
        return

    qr = qrcode.QRCode(border=2, box_size=1)
    qr.add_data(link)
    qr.make(fit=True)
    m = qr.get_matrix()

    print(f"\n  QR на ссылку {link}\n")
    # Две строки матрицы в один символ: так QR помещается на экран целиком
    for y in range(0, len(m), 2):
        row = ""
        for x in range(len(m[0])):
            top = m[y][x]
            bottom = m[y + 1][x] if y + 1 < len(m) else False
            row += "█" if top and bottom else "▀" if top else "▄" if bottom else " "
        print("  " + row)
    print()

    out = ROOT / "jury-qr.svg"
    try:
        import qrcode.image.svg

        img = qrcode.make(link, image_factory=qrcode.image.svg.SvgPathImage)
        img.save(str(out))
        say(OK, f"QR сохранён для проектора: {out}")
    except Exception:
        pass


# ─────────────────────────── Наблюдение ───────────────────────────

def watch(api_url: str, token: str, interval: float = 5.0) -> None:
    """Живой счётчик: кто из жюри уже подключился. Ctrl+C — выход."""
    print("\n  Слежу за подключениями. Ctrl+C — остановить.\n")
    seen: set[str] = set()
    try:
        while True:
            code, devices = api(api_url, "/api/v1/devices", token)
            code2, live = api(api_url, "/api/v1/dashboard/live", token)
            if code == 200 and isinstance(devices, list):
                web = [d for d in devices if str(d.get("serial", "")).startswith("WEB-M")]
                online = [d for d in web if d.get("online")]
                fresh = {d["serial"] for d in online} - seen
                seen |= {d["serial"] for d in online}
                positions = len(live) if code2 == 200 and isinstance(live, list) else "?"
                line = (f"  телефонов на связи: {len(online)} из {len(web)}   "
                        f"точек на карте: {positions}")
                if fresh:
                    line += f"   подключились: {', '.join(sorted(fresh))}"
                print(line)
            time.sleep(interval)
    except KeyboardInterrupt:
        print("\n  Остановлено.\n")


# ─────────────────────────── Главное ───────────────────────────

def main() -> int:
    ap = argparse.ArgumentParser(description="Предполётная проверка стенда перед показом")
    ap.add_argument("--api", default=os.environ.get("DG_API", "http://localhost:8000"),
                    help="адрес сервера")
    ap.add_argument("--url", default="", help="публичная ссылка туннеля (панель)")
    ap.add_argument("--email", default="admin@driverguard.kz")
    ap.add_argument("--password", default="", help="текущий пароль администратора")
    ap.add_argument("--judges", type=int, default=40, help="сколько судей ожидается")
    ap.add_argument("--qr", action="store_true", help="нарисовать QR на ссылку для жюри")
    ap.add_argument("--watch", action="store_true", help="следить, кто подключился")
    args = ap.parse_args()

    print("\n  Предполётная проверка стенда DriverGuard")
    print("  " + "═" * 58)

    if not check_backend(args.api):
        print("\n  Дальше проверять нечего: сервер не поднят.\n")
        return 1

    default_token = check_default_passwords(args.api)
    token = default_token
    if args.password:
        token = admin_token(args.api, args.email, args.password) or token

    check_secrets()
    check_backup()

    if token:
        check_mentors(args.api, token, args.judges)
        check_devices(args.api, token)
    else:
        say(WARN, "Без пароля администратора часть проверок пропущена",
            "Повторите с ключом --password ***")

    check_public_url(args.url)

    print("  " + "═" * 58)
    if blockers:
        print(f"\n  ВЫХОДИТЬ РАНО: {len(blockers)} блокирующих пункта.\n")
        for b in blockers:
            print(f"    • {b}")
        print()
    elif warnings_:
        print(f"\n  Можно выходить, но {len(warnings_)} пункта стоит закрыть:\n")
        for w in warnings_:
            print(f"    • {w}")
        print()
    else:
        print("\n  Стенд готов к показу.\n")

    if args.qr or args.url:
        link = (args.url.rstrip("/") + "/driver") if args.url else "https://…/driver"
        show_qr(link)

    if args.watch and token:
        watch(args.api, token)

    return 1 if blockers else 0


if __name__ == "__main__":
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if reconfigure is not None:
            try:
                reconfigure(encoding="utf-8", errors="replace")
            except (ValueError, OSError):
                pass
    sys.exit(main())
