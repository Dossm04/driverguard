"""scripts/check_telegram.py: чаты из getUpdates и запись chat_id в панель (фейковые серверы)."""

import json
import sys
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
import check_telegram  # noqa: E402


class Fake(BaseHTTPRequestHandler):
    saved: dict = {}
    sent: list = []

    def log_message(self, *a):
        pass

    def _json(self, code, body):
        data = json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}")

    def do_POST(self):
        body = self._body()
        if self.path.endswith("/getMe"):
            return self._json(
                200,
                {
                    "ok": True,
                    "result": {"username": "DriverGguard_bot", "first_name": "DriverGuard"},
                },
            )
        if self.path.endswith("/getUpdates"):
            return self._json(
                200,
                {
                    "ok": True,
                    "result": [
                        {
                            "update_id": 1,
                            "message": {
                                "chat": {"id": 777, "type": "private", "first_name": "Айгерим"},
                                "text": "/start",
                            },
                        },
                        {
                            "update_id": 2,
                            "message": {
                                "chat": {
                                    "id": -1001234,
                                    "type": "supergroup",
                                    "title": "Диспетчеры",
                                },
                                "text": "/start",
                            },
                        },
                    ],
                },
            )
        if self.path.endswith("/sendMessage"):
            Fake.sent.append(body)
            return self._json(200, {"ok": True, "result": {"message_id": 1}})
        if self.path.endswith("/auth/login"):
            return self._json(200, {"access_token": "t"})
        return self._json(404, {"ok": False, "description": "нет"})

    def do_GET(self):
        if self.path.endswith("/settings/notifications"):
            return self._json(
                200, {"value": {"telegram_chat_id": "", "critical_types": ["sos"]}, "version": 1}
            )
        return self._json(404, {})

    def do_PUT(self):
        Fake.saved = self._body()
        return self._json(200, {"key": "notifications", "value": Fake.saved["value"], "version": 2})


@pytest.fixture
def server():
    Fake.saved, Fake.sent = {}, []
    srv = HTTPServer(("127.0.0.1", 0), Fake)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def test_lists_chats_and_sets_last_one(server, capsys):
    rc = check_telegram.main(
        [
            "--token",
            "123:ABC",
            "--api-base",
            server,
            "--api",
            f"{server}/api/v1",
            "--set-chat",
            "auto",
            "--send-test",
        ]
    )
    out = capsys.readouterr().out
    assert rc == 0 and "@DriverGguard_bot" in out and "chat_id 777" in out and "Диспетчеры" in out
    assert Fake.saved["value"] == {"telegram_chat_id": "-1001234", "critical_types": ["sos"]}
    assert Fake.sent[0]["chat_id"] == -1001234 and "связь есть" in Fake.sent[0]["text"]


def test_explicit_chat_id_and_missing_token(server):
    assert (
        check_telegram.main(
            [
                "--token",
                "123:ABC",
                "--api-base",
                server,
                "--api",
                f"{server}/api/v1",
                "--set-chat",
                "777",
            ]
        )
        == 0
    )
    assert Fake.saved["value"]["telegram_chat_id"] == "777"
    assert check_telegram.main(["--token", "", "--api-base", server]) == 2
