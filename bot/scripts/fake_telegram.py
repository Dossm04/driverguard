"""Фейковый Telegram Bot API для проверки бота без выхода в интернет (docs/telegram.md).

Запуск: python scripts/fake_telegram.py [порт=8081]; бот — с TELEGRAM_API_BASE=http://localhost:8081.
Сервисные ручки: GET /_sent (все вызовы бота), POST /_push {"callback": "fp:<uuid>"} или
{"text": "/status"} — имитируют нажатие кнопки / команду координатора (chat_id 777).
"""

import asyncio
import json
import sys
import time

from aiohttp import web

CHAT = {"id": 777, "type": "private", "first_name": "Айгерим"}
USER = {"id": 777, "is_bot": False, "first_name": "Айгерим", "last_name": "К."}
state = {"sent": [], "updates": [], "next_update": 1, "next_message": 1, "event": asyncio.Event()}


def _message(text: str = "") -> dict:
    mid = state["next_message"]
    state["next_message"] += 1
    return {"message_id": mid, "date": int(time.time()), "chat": CHAT, "from": USER, "text": text}


async def api(request: web.Request) -> web.Response:
    method = request.match_info["method"]
    if request.content_type.startswith("multipart") or request.content_type.startswith(
        "application/x-www-form"
    ):
        form = await request.post()
        params = {k: (v if isinstance(v, str) else f"<file {v.filename}>") for k, v in form.items()}
    else:
        params = await request.json() if request.can_read_body else {}
    if method == "getUpdates":
        timeout = float(params.get("timeout", 0) or 0)
        offset = int(params.get("offset", 0) or 0)
        state["updates"] = [u for u in state["updates"] if u["update_id"] >= offset]
        if not state["updates"] and timeout:
            state["event"].clear()
            try:
                await asyncio.wait_for(state["event"].wait(), timeout)
            except TimeoutError:
                pass
        return web.json_response({"ok": True, "result": list(state["updates"])})
    state["sent"].append({"method": method, "params": params, "at": time.time()})
    if method == "getMe":
        result = {
            "id": 1,
            "is_bot": True,
            "first_name": "DriverGuard",
            "username": "DriverGguard_bot",
        }
    elif method in ("sendMessage", "sendVideo", "sendContact", "sendPhoto"):
        result = _message(params.get("text") or params.get("caption") or "")
    elif method in ("editMessageText", "editMessageCaption"):
        result = {
            **_message(params.get("text") or params.get("caption") or ""),
            "message_id": int(params["message_id"]),
        }
    else:  # deleteWebhook, setMyCommands, answerCallbackQuery, …
        result = True
    return web.json_response({"ok": True, "result": result})


async def push(request: web.Request) -> web.Response:
    body = await request.json()
    uid = state["next_update"]
    state["next_update"] += 1
    if "callback" in body:
        origin = next(
            (s for s in reversed(state["sent"]) if s["method"] in ("sendMessage", "sendVideo")),
            None,
        )
        text = (
            (origin or {}).get("params", {}).get("text")
            or (origin or {}).get("params", {}).get("caption")
            or ""
        )
        update = {
            "update_id": uid,
            "callback_query": {
                "id": str(uid),
                "from": USER,
                "chat_instance": "1",
                "data": body["callback"],
                "message": {**_message(text), "message_id": int(body.get("message_id", 1))},
            },
        }
    else:
        text = body["text"]
        update = {
            "update_id": uid,
            "message": {
                **_message(text),
                "entities": [{"type": "bot_command", "offset": 0, "length": len(text.split()[0])}],
            },
        }
    state["updates"].append(update)
    state["event"].set()
    return web.json_response({"ok": True, "update_id": uid})


async def sent(request: web.Request) -> web.Response:
    return web.json_response(state["sent"], dumps=lambda o: json.dumps(o, ensure_ascii=False))


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8081
    app = web.Application()
    app.add_routes(
        [
            web.post("/bot{token}/{method}", api),
            web.get("/bot{token}/{method}", api),
            web.post("/_push", push),
            web.get("/_sent", sent),
        ]
    )
    print(f"fake telegram on http://localhost:{port}", flush=True)
    web.run_app(app, port=port, print=None)


if __name__ == "__main__":
    main()
