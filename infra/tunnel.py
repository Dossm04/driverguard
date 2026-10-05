"""Публичный HTTPS-адрес для демо с ноутбука: два быстрых туннеля Cloudflare (панель и API).

Зачем: менторы открывают панель и PWA по ссылке из любой сети, а камера телефона в браузере
работает только по HTTPS. Быстрые туннели (trycloudflare.com) бесплатны, без аккаунта и ключей,
но адрес меняется при каждом запуске — поэтому скрипт сам прописывает свежие адреса в
infra/.env (NEXT_PUBLIC_API_URL, NEXT_PUBLIC_WS_URL, CORS_ORIGINS, WEB_URL) и пересобирает
web/backend в docker compose. При Ctrl+C туннели закрываются, .env возвращается к прежним
значениям.

  python infra/tunnel.py                 # docker-режим: стек `make demo` уже запущен
  python infra/tunnel.py --mode dev      # backend/web запущены вручную: печатает, что перезапустить
  python infra/tunnel.py --dry-run       # без cloudflared и docker: показать, что будет записано

Нужен cloudflared: Windows `winget install Cloudflare.cloudflared`, macOS `brew install cloudflared`,
Linux — пакет с https://github.com/cloudflare/cloudflared/releases.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import signal
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
ENV_PATH = ROOT / "infra" / ".env"
COMPOSE = ["docker", "compose", "-f", str(ROOT / "infra" / "docker-compose.yml")]
URL_RE = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")
ENV_KEYS = (
    "NEXT_PUBLIC_API_URL",
    "NEXT_PUBLIC_WS_URL",
    "CORS_ORIGINS",
    "WEB_URL",
    "TRUST_PROXY",
    "NEXT_PUBLIC_MP_WASM_URL",
    "MINIO_PUBLIC_ENDPOINT",
)


def mediapipe_version() -> str:
    """Версия @mediapipe/tasks-vision из web/package-lock.json — WASM с CDN должен совпадать
    с JS-загрузчиком в бандле, иначе «не удалось загрузить модель» у всех через туннель."""
    lock = ROOT / "web" / "package-lock.json"
    try:
        data = json.loads(lock.read_text(encoding="utf-8"))
        return data["packages"]["node_modules/@mediapipe/tasks-vision"]["version"]
    except Exception:  # noqa: BLE001 — нет lock-файла: версия из package.json
        pkg = json.loads((ROOT / "web" / "package.json").read_text(encoding="utf-8"))
        return pkg["dependencies"]["@mediapipe/tasks-vision"].lstrip("^~")


# WASM MediaPipe с CDN: 30–40 телефонов через бесплатный туннель не тянут по 10 МБ с ноутбука
MP_WASM_CDN = f"https://cdn.jsdelivr.net/npm/@mediapipe/tasks-vision@{mediapipe_version()}/wasm"


def rewrite_env(text: str, updates: dict[str, str]) -> str:
    """Заменяет значения ключей в .env (или дописывает в конец), остальное не трогает."""
    lines = text.splitlines()
    seen: set[str] = set()
    for i, line in enumerate(lines):
        key = line.split("=", 1)[0].strip()
        if key in updates and not line.lstrip().startswith("#"):
            lines[i] = f"{key}={updates[key]}"
            seen.add(key)
    for key, value in updates.items():
        if key not in seen:
            lines.append(f"{key}={value}")
    return "\n".join(lines) + "\n"


def env_values(text: str, keys: tuple[str, ...]) -> dict[str, str | None]:
    found: dict[str, str | None] = dict.fromkeys(keys)
    for line in text.splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            key, value = line.split("=", 1)
            if key.strip() in found:
                found[key.strip()] = value.strip()
    return found


def tunnel_updates(
    api_url: str, web_url: str, current_cors: str | None, minio_url: str | None = None
) -> dict[str, str]:
    cors = [o.strip() for o in (current_cors or "http://localhost:3000").split(",") if o.strip()]
    cors = [o for o in cors if "trycloudflare.com" not in o]  # адреса прошлых запусков
    if web_url not in cors:
        cors.append(web_url)
    return {
        "NEXT_PUBLIC_API_URL": f"{api_url}/api/v1",
        "NEXT_PUBLIC_WS_URL": f"{api_url.replace('https://', 'wss://')}/ws/live",
        "CORS_ORIGINS": ",".join(cors),
        "WEB_URL": web_url,
        # За Cloudflare backend видит IP туннеля: реальный клиент — в CF-Connecting-IP
        "TRUST_PROXY": "true",
        "NEXT_PUBLIC_MP_WASM_URL": MP_WASM_CDN,
        # Фото чек-листов панель открывает по presigned-ссылкам прямо в MinIO — через туннель
        # ссылки должны вести на публичный адрес MinIO, а не на localhost:9000
        **({"MINIO_PUBLIC_ENDPOINT": minio_url} if minio_url else {}),
    }


class Tunnel:
    """Один быстрый туннель cloudflared; адрес читается из его лога."""

    def __init__(self, target: str) -> None:
        self.target = target
        self.url: str | None = None
        self.proc: subprocess.Popen[str] | None = None

    def start(self, timeout_s: float = 60) -> str:
        self.proc = subprocess.Popen(
            ["cloudflared", "tunnel", "--no-autoupdate", "--url", self.target],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        assert self.proc.stderr is not None
        deadline = time.monotonic() + timeout_s
        for line in self.proc.stderr:
            m = URL_RE.search(line)
            if m:
                self.url = m.group(0)
                threading.Thread(target=self._drain, daemon=True).start()
                return self.url
            if time.monotonic() > deadline:
                break
        self.stop()
        raise RuntimeError(f"cloudflared не выдал адрес для {self.target} за {timeout_s:.0f} с")

    def _drain(self) -> None:  # лог cloudflared читаем, чтобы не забился pipe
        assert self.proc is not None and self.proc.stderr is not None
        for _ in self.proc.stderr:
            pass

    def stop(self) -> None:
        if self.proc and self.proc.poll() is None:
            self.proc.terminate()
            try:
                self.proc.wait(5)
            except subprocess.TimeoutExpired:
                self.proc.kill()


def default_credentials_in_use(api_base: str = "http://localhost:8000/api/v1") -> list[str]:
    """Какие учётки из seed всё ещё с паролями по умолчанию (через публичный туннель это
    полный доступ любому, кто видел README)."""
    found: list[str] = []
    checks = [
        ("/auth/login", {"email": "admin@driverguard.kz", "password": "admin123"}, "admin@driverguard.kz / admin123"),
        ("/auth/driver-login", {"phone": "+77012441832", "pin": "1234"}, "водитель +77012441832 / PIN 1234"),
        ("/auth/device", {"serial": "DG-0001", "secret": "device-secret-1"}, "устройство DG-0001 / device-secret-1"),
    ]
    for path, body, label in checks:
        req = urllib.request.Request(
            api_base + path,
            data=json.dumps(body).encode(),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:  # noqa: S310 — свой адрес
                if resp.status == 200:
                    found.append(label)
                elif resp.status != 401:
                    raise RuntimeError(f"Проверка учётных данных не завершена: HTTP {resp.status}")
        except urllib.error.HTTPError as exc:
            if exc.code != 401:
                raise RuntimeError(f"Проверка учётных данных не завершена: HTTP {exc.code}") from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            raise RuntimeError("Backend недоступен: нельзя подтвердить смену паролей") from exc
    return found


def wait_http(url: str, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=5) as resp:  # noqa: S310 — свой адрес
                if resp.status < 500:
                    return True
        except Exception:  # noqa: BLE001 — ждём, пока поднимется
            pass
        time.sleep(3)
    return False


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Публичный HTTPS-адрес для демо (cloudflared)")
    parser.add_argument("--mode", choices=["docker", "dev"], default="docker")
    parser.add_argument("--dry-run", action="store_true", help="без cloudflared/docker")
    parser.add_argument("--keep-env", action="store_true", help="не возвращать .env при выходе")
    parser.add_argument(
        "--allow-default-passwords",
        action="store_true",
        help="открыть туннель, даже если admin123 / PIN 1234 / device-secret-1 ещё действуют",
    )
    parser.add_argument("--no-minio", action="store_true", help="не публиковать MinIO (фото не откроются)")
    args = parser.parse_args(argv)

    if not ENV_PATH.exists():
        print("Нет infra/.env — сначала `make demo` (создаст из .env.example)", file=sys.stderr)
        return 2
    if not args.dry_run and shutil.which("cloudflared") is None:
        print(
            "Не найден cloudflared. Установите: Windows `winget install Cloudflare.cloudflared`, "
            "macOS `brew install cloudflared`, Linux — https://github.com/cloudflare/cloudflared/releases",
            file=sys.stderr,
        )
        return 2

    original = ENV_PATH.read_text(encoding="utf-8")
    if not args.dry_run and not args.allow_default_passwords:
        try:
            weak = default_credentials_in_use()
        except RuntimeError as exc:
            print(f"СТОП: {exc}. Проверьте backend и повторите запуск.", file=sys.stderr)
            return 3
        blocking = [w for w in weak if not w.startswith("устройство")]
        if blocking:
            print(
                "СТОП: через публичную ссылку войти сможет кто угодно — учётки с паролями по умолчанию:\n  - "
                + "\n  - ".join(weak)
                + "\nСмените их: Настройки → Пользователи (admin), Водители → карточка → PIN, "
                "либо ADMIN_PASSWORD/DRIVER_PIN в infra/.env и пересев (SEED=always). "
                "Осознанно рискнуть: --allow-default-passwords",
                file=sys.stderr,
            )
            return 3
        if weak:  # только секрет устройства: предупреждаем, не блокируем показ
            print(
                "ВНИМАНИЕ: " + "; ".join(weak) + " — с ним можно слать события «от устройства». "
                "Отключите DG-0001 в Настройки → Устройства или пересейте с новым DG_SECRET "
                "(python infra/secrets_check.py --fix --with-device, затем SEED=always make demo).",
                file=sys.stderr,
            )
    tunnels: list[Tunnel] = []
    try:
        minio_url: str | None = None
        if args.dry_run:
            api_url, web_url = "https://api-demo.trycloudflare.com", "https://web-demo.trycloudflare.com"
            minio_url = None if args.no_minio else "https://minio-demo.trycloudflare.com"
        else:
            print("Открываю туннель к backend (localhost:8000)…")
            api = Tunnel("http://localhost:8000")
            tunnels.append(api)
            api_url = api.start()
            print("Открываю туннель к панели (localhost:3000)…")
            web = Tunnel("http://localhost:3000")
            tunnels.append(web)
            web_url = web.start()
            if not args.no_minio:
                print("Открываю туннель к MinIO (localhost:9000) — фото чек-листов через presigned-ссылки…")
                minio = Tunnel("http://localhost:9000")
                tunnels.append(minio)
                minio_url = minio.start()

        updates = tunnel_updates(
            api_url, web_url, env_values(original, ("CORS_ORIGINS",))["CORS_ORIGINS"], minio_url
        )
        new_text = rewrite_env(original, updates)
        if args.dry_run:
            print("infra/.env получил бы значения:")
            for k, v in updates.items():
                print(f"  {k}={v}")
            return 0
        ENV_PATH.write_text(new_text, encoding="utf-8")
        print("infra/.env обновлён:", ", ".join(updates))

        if args.mode == "docker":
            print("Пересобираю web (адреса backend вшиваются в бандл) и перезапускаю backend…")
            # bot читает WEB_URL (ссылки «открыть в панели» в алертах) — перезапускаем и его
            subprocess.run(
                [*COMPOSE, "--profile", "full", "up", "-d", "--build", "backend", "web", "bot"],
                check=True,
            )
            ok = wait_http(f"{web_url}/login", 300)
            if not ok:
                print("Панель через туннель не отвечает 5 минут — смотрите `make demo-logs`", file=sys.stderr)
        else:
            print(
                "Режим dev: перезапустите backend и web, чтобы они прочитали новые значения:\n"
                "  make backend-dev\n"
                "  cd web && npm run dev   (переменные NEXT_PUBLIC_* берёт из infra/.env через make web-dev-tunnel)"
            )

        print(
            "\nСсылки для менторов (действуют, пока запущен этот скрипт):\n"
            f"  Панель координатора:  {web_url}/login\n"
            f"  PWA водителя:         {web_url}/driver\n"
            f"  Камера в браузере:    {web_url}/driver/camera\n"
            f"  API (Swagger):        {api_url}/docs\n"
            "Учётки менторов: `make mentors N=5` (печатает пароли один раз).\n"
            "Кто сейчас в системе: Настройки → Пользователи (колонка «Онлайн»).\n"
            "Ctrl+C — закрыть туннели и вернуть локальные адреса в .env."
        )
        stop = threading.Event()
        signal.signal(signal.SIGINT, lambda *_: stop.set())
        signal.signal(signal.SIGTERM, lambda *_: stop.set())
        while not stop.is_set():
            if any(t.proc and t.proc.poll() is not None for t in tunnels):
                print("Туннель закрылся — перезапустите скрипт", file=sys.stderr)
                break
            stop.wait(2)
        return 0
    finally:
        for t in tunnels:
            t.stop()
        if not args.dry_run and not args.keep_env and ENV_PATH.read_text(encoding="utf-8") != original:
            ENV_PATH.write_text(original, encoding="utf-8")
            print(
                "\ninfra/.env возвращён к локальным адресам. Чтобы панель снова открывалась по "
                "localhost: `make demo` (пересоберёт web)."
            )


if __name__ == "__main__":
    sys.exit(main())
