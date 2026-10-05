"""Подключение ИИ-проверки фото одной командой: ключ → infra/.env → перезапуск backend → тест.

  python infra/ai_setup.py                         # спросит ключ (ввод скрыт), модель gemma4
  python infra/ai_setup.py --key sk-… --model gemma4
  python infra/ai_setup.py --no-restart --test     # backend запущен вручную: только .env и тест
  python infra/ai_setup.py --status                # только показать, что видит backend

Что делает: пишет AI_PROVIDER=auto, OPENAI_COMPAT_BASE_URL/API_KEY/MODEL в infra/.env
(файл в .gitignore — ключ в репозиторий не попадёт), перезапускает контейнер backend
(`docker compose … up -d backend`), затем входит админом и вызывает POST /checklists/ai-test:
backend отправит модели тестовую картинку и вернёт вердикт с временем ответа.
Нужна модель, понимающая фото: на alem.ai это Gemma 4 (`gemma4`); Qwen 3.8 — текстовая.
"""

from __future__ import annotations

import argparse
import getpass
import json
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from tunnel import COMPOSE, ENV_PATH, ROOT, env_values, rewrite_env  # noqa: E402

EXAMPLE_PATH = ROOT / "infra" / ".env.example"
DEFAULT_BASE_URL = "https://llm.alem.ai/v1"
DEFAULT_MODEL = "gemma4"


def http_json(url: str, body: dict | None = None, token: str | None = None, timeout: float = 90) -> dict:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method="POST" if body is not None else "GET")
    req.add_header("Content-Type", "application/json")
    if token:
        req.add_header("Authorization", f"Bearer {token}")
    with urllib.request.urlopen(req, timeout=timeout) as resp:  # noqa: S310 — свой backend
        return json.loads(resp.read().decode() or "{}")


def wait_backend(api: str, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            http_json(f"{api}/health", timeout=5)
            return True
        except Exception:  # noqa: BLE001 — ждём старта
            time.sleep(2)
    return False


def run_test(api: str, email: str, password: str) -> int:
    if not wait_backend(api, 120):  # после `up -d backend` контейнер поднимается 15–20 с
        print(f"Backend не отвечает на {api} (ждал 2 минуты) — запущен ли стек?", file=sys.stderr)
        return 3
    try:
        tokens = http_json(f"{api}/auth/login", {"email": email, "password": password}, timeout=20)
    except urllib.error.HTTPError as exc:
        print(f"Вход админом не удался ({exc.code}): проверьте --admin-email/--admin-password", file=sys.stderr)
        return 3
    except Exception as exc:  # noqa: BLE001
        print(f"Backend не отвечает на {api}: {exc}", file=sys.stderr)
        return 3
    token = tokens["access_token"]
    status = http_json(f"{api}/checklists/ai-status", token=token, timeout=20)
    print(
        f"Провайдер: {status.get('provider')} · модель: {status.get('model') or '—'} · "
        f"хост: {status.get('host') or '—'} · ключ задан: {'да' if status.get('configured') else 'нет'}"
    )
    if not status.get("configured"):
        print("Ключ не виден backend'у — контейнер не перезапущен или .env не прочитан.", file=sys.stderr)
        return 4
    print("Отправляю тестовую картинку модели (до 90 с)…")
    result = http_json(f"{api}/checklists/ai-test", {}, token=token, timeout=120)
    if result.get("ok"):
        print(
            f"OK: модель {result.get('model')} ответила за {result.get('latency_ms', 0) / 1000:.1f} с, "
            f"вердикт «{result.get('verdict')}». ИИ-проверка фото подключена."
        )
        return 0
    print(f"Провайдер ответил ошибкой: {result.get('error')}", file=sys.stderr)
    print(
        "Частые причины: неверный ключ, ключ выдан на другую модель (у alem.ai ключ привязан к модели), "
        "модель без поддержки картинок (нужна gemma4), нет интернета у контейнера.",
        file=sys.stderr,
    )
    return 5


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Подключить ИИ-проверку фото (alem.ai Gemma 4)")
    parser.add_argument("--key", help="API-ключ модели; без флага — запрос со скрытым вводом")
    parser.add_argument(
        "--model", default=DEFAULT_MODEL, help=f"модель с картинками (по умолчанию {DEFAULT_MODEL})"
    )
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL)
    parser.add_argument("--api", default="http://localhost:8000/api/v1", help="адрес backend для теста")
    parser.add_argument("--admin-email", default="admin@driverguard.kz")
    parser.add_argument("--admin-password", default="admin123")
    parser.add_argument(
        "--no-restart", action="store_true", help="не трогать docker (backend запущен вручную)"
    )
    parser.add_argument("--no-test", action="store_true", help="только записать .env")
    parser.add_argument(
        "--no-build", action="store_true", help="не пересобирать образ backend (после git pull нужна пересборка)"
    )
    parser.add_argument("--test", action="store_true", help="только тест, .env не менять")
    parser.add_argument("--status", action="store_true", help="только показать статус провайдера")
    args = parser.parse_args(argv)

    if args.status or args.test:
        return run_test(args.api, args.admin_email, args.admin_password) if args.test else _status_only(args)

    key = args.key or getpass.getpass("API-ключ модели (ввод скрыт): ").strip()
    if not key.startswith("sk-") or len(key) < 12:
        print("Ключ выглядит неверно: ожидается строка вида sk-…", file=sys.stderr)
        return 2
    if not key.isascii() or any(ch in key for ch in "•*● "):
        print(
            "В ключе есть скрытые символы (например, «•»): терминал замаскировал вставку, и в .env попал бы "
            "испорченный ключ. Запустите скрипт БЕЗ --key и введите ключ в скрытом поле, "
            "или откройте infra/.env в Блокноте и вставьте строку OPENAI_COMPAT_API_KEY=sk-… вручную.",
            file=sys.stderr,
        )
        return 2

    if not ENV_PATH.exists():
        ENV_PATH.write_text(EXAMPLE_PATH.read_text(encoding="utf-8"), encoding="utf-8")
        print("infra/.env создан из .env.example")
    current = ENV_PATH.read_text(encoding="utf-8")
    updates = {
        "AI_PROVIDER": "auto",
        "OPENAI_COMPAT_BASE_URL": args.base_url,
        "OPENAI_COMPAT_API_KEY": key,
        "OPENAI_COMPAT_MODEL": args.model,
    }
    ENV_PATH.write_text(rewrite_env(current, updates), encoding="utf-8")
    shown = env_values(
        ENV_PATH.read_text(encoding="utf-8"), ("OPENAI_COMPAT_MODEL", "OPENAI_COMPAT_BASE_URL")
    )
    print(
        f"infra/.env: модель {shown['OPENAI_COMPAT_MODEL']} · {shown['OPENAI_COMPAT_BASE_URL']} "
        "· ключ записан (в git не попадёт)"
    )

    if not args.no_restart:
        print("Пересобираю и перезапускаю backend в docker compose (1–2 минуты)…")
        build = [] if args.no_build else ["--build"]
        proc = subprocess.run([*COMPOSE, "--profile", "full", "up", "-d", *build, "backend"], check=False)
        if proc.returncode != 0:
            print(
                "docker compose завершился с ошибкой. Запущен ли Docker Desktop (значок кита, «Engine running»)? "
                "Проверьте `docker version`, затем повторите команду.",
                file=sys.stderr,
            )
            return 6
        if not wait_backend(args.api, 120):
            print("Backend не поднялся за 2 минуты — смотрите `docker compose … logs backend`", file=sys.stderr)
            return 6
    if args.no_test:
        return 0
    return run_test(args.api, args.admin_email, args.admin_password)


def _status_only(args: argparse.Namespace) -> int:
    if not wait_backend(args.api, 120):
        print(f"Backend не отвечает на {args.api} (ждал 2 минуты)", file=sys.stderr)
        return 3
    try:
        creds = {"email": args.admin_email, "password": args.admin_password}
        tokens = http_json(f"{args.api}/auth/login", creds, timeout=20)
        status = http_json(f"{args.api}/checklists/ai-status", token=tokens["access_token"], timeout=20)
    except Exception as exc:  # noqa: BLE001
        print(f"Не удалось получить статус: {exc}", file=sys.stderr)
        return 3
    print(json.dumps(status, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
