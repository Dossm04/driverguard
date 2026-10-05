"""Проверка и настройка Telegram-бота одной командой (docs/telegram.md §2, quickstart).

  python scripts/check_telegram.py                 # getMe + кто писал боту (chat_id)
  python scripts/check_telegram.py --set-chat auto # chat_id последнего написавшего → в панель
  python scripts/check_telegram.py --set-chat -1001234567890 --send-test

Токен — из TELEGRAM_BOT_TOKEN или --token; панель — --api / API_URL, --admin-email/--admin-password.
"""

from __future__ import annotations

import argparse
import os
import sys

import httpx


def tg(base: str, token: str, method: str, **params) -> dict:
    resp = httpx.post(f"{base}/bot{token}/{method}", json=params, timeout=20)
    data = resp.json()
    if not data.get("ok"):
        raise SystemExit(f"Telegram {method}: {data.get('description') or resp.status_code}")
    return data["result"]


def chats_from_updates(updates: list[dict]) -> dict[int, dict]:
    chats: dict[int, dict] = {}
    for u in updates:
        msg = (
            u.get("message")
            or u.get("channel_post")
            or (u.get("callback_query") or {}).get("message")
        )
        if not msg or "chat" not in msg:
            continue
        chat = msg["chat"]
        chats.pop(chat["id"], None)  # в конец словаря: последний апдейт — последний написавший
        title = (
            chat.get("title")
            or " ".join(x for x in (chat.get("first_name"), chat.get("last_name")) if x)
            or chat.get("username")
            or "?"
        )
        chats[chat["id"]] = {
            "id": chat["id"],
            "type": chat.get("type"),
            "title": title,
            "text": (msg.get("text") or "")[:40],
        }
    return chats


def set_chat_in_panel(api: str, email: str, password: str, chat_id: int) -> dict:
    with httpx.Client(timeout=20) as c:
        login = c.post(f"{api}/auth/login", json={"email": email, "password": password})
        if login.status_code != 200:
            raise SystemExit(f"Панель: вход не удался ({login.status_code}): {login.text[:120]}")
        h = {"Authorization": f"Bearer {login.json()['access_token']}"}
        current = c.get(f"{api}/settings/notifications", headers=h)
        if current.status_code != 200:
            raise SystemExit(f"Панель: GET /settings/notifications → {current.status_code}")
        value = current.json()["value"]
        value["telegram_chat_id"] = str(chat_id)
        saved = c.put(f"{api}/settings/notifications", json={"value": value}, headers=h)
        if saved.status_code != 200:
            raise SystemExit(
                f"Панель: PUT /settings/notifications → {saved.status_code}: {saved.text[:120]}"
            )
        return saved.json()


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Проверка токена, chat_id и запись в панель")
    p.add_argument("--token", default=os.environ.get("TELEGRAM_BOT_TOKEN", ""))
    p.add_argument(
        "--api-base", default=os.environ.get("TELEGRAM_API_BASE") or "https://api.telegram.org"
    )
    p.add_argument("--api", default=os.environ.get("API_URL", "http://localhost:8000/api/v1"))
    p.add_argument("--admin-email", default=os.environ.get("ADMIN_EMAIL", "admin@driverguard.kz"))
    p.add_argument("--admin-password", default=os.environ.get("ADMIN_PASSWORD", "admin123"))
    p.add_argument("--set-chat", default=None, help="chat_id или auto (последний написавший боту)")
    p.add_argument(
        "--send-test", action="store_true", help="отправить тестовое сообщение в выбранный чат"
    )
    args = p.parse_args(argv)
    if not args.token:
        print("Нет токена: задайте TELEGRAM_BOT_TOKEN (infra/.env) или --token", file=sys.stderr)
        return 2

    me = tg(args.api_base, args.token, "getMe")
    print(f"✓ Токен верный: @{me.get('username')} ({me.get('first_name')})")
    updates = tg(args.api_base, args.token, "getUpdates", timeout=0)
    chats = chats_from_updates(updates)
    if not chats:
        print(
            "• Боту ещё никто не писал: откройте его в Telegram, нажмите /start "
            "и запустите скрипт снова."
        )
        print(
            "  Если бот уже запущен (python main.py), он сам забирает обновления — "
            "остановите его на минуту."
        )
    else:
        print("• Чаты, писавшие боту:")
        for c in chats.values():
            print(f"    chat_id {c['id']:<16} {c['type']:<10} {c['title']}  «{c['text']}»")

    if args.set_chat:
        if args.set_chat == "auto":
            if not chats:
                print("Нечего записывать: chat_id не найден", file=sys.stderr)
                return 1
            chat_id = list(chats.values())[-1]["id"]
        else:
            chat_id = int(args.set_chat)
        saved = set_chat_in_panel(args.api, args.admin_email, args.admin_password, chat_id)
        print(
            f"✓ В панели сохранён chat_id {chat_id} "
            f"(Настройки → Уведомления, версия {saved['version']})"
        )
        if args.send_test:
            tg(
                args.api_base,
                args.token,
                "sendMessage",
                chat_id=chat_id,
                text="✅ DriverGuard: связь есть. Критические события будут приходить сюда.",
            )
            print("✓ Тестовое сообщение отправлено")
    return 0


if __name__ == "__main__":
    sys.exit(main())
