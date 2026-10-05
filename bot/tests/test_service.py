"""AlertService с заглушками backend и отправителя: отбор, ожидание chat_id, review."""

from datetime import UTC, datetime, timedelta

from dg_bot.api import ApiError
from dg_bot.config import Config
from dg_bot.service import AlertService
from tests.test_format import EVENT

SEED_TYPES = ["microsleep", "phone", "camera_sabotage", "sos"]
# «Сейчас» для опроса — рядом с ts тестового события: окно бота 24 ч, а тесты не должны
# ломаться с течением календаря
NOW = datetime.fromisoformat(EVENT["ts"]).astimezone(UTC) + timedelta(minutes=5)


def cfg(chat_env: str = "") -> Config:
    return Config(
        token="t",
        api_url="http://backend",
        api_email="bot@driverguard.kz",
        api_password="x",
        chat_id_env=chat_env,
        poll_s=0,
        settings_refresh_s=0,  # без кэша — каждый вызов читает «настройки»
        tz="Asia/Almaty",
        web_url="http://localhost:3000",
        telegram_api_base=None,
    )


class FakeApi:
    def __init__(self, events: list[dict], chat_id: str = "777"):
        self.events = events
        self.notif = {"telegram_chat_id": chat_id, "critical_types": list(SEED_TYPES)}
        self.reviews: list[tuple] = []
        self.fail_review: ApiError | None = None

    async def new_events(self, ts_from: str, page_size: int = 200) -> list[dict]:
        return list(self.events)

    async def notifications(self) -> dict:
        return self.notif

    async def review(self, uuid: str, status: str, comment: str | None) -> dict:
        if self.fail_review:
            raise self.fail_review
        self.reviews.append((uuid, status, comment))
        return {"status": status}

    async def clip_bytes(self, uuid: str) -> bytes | None:
        return b"clip-bytes"


class FakeSender:
    def __init__(self):
        self.sent: list[dict] = []

    async def send_alert(self, chat_id, text, keyboard, media) -> None:
        self.sent.append({"chat_id": chat_id, "text": text, "keyboard": keyboard, "media": media})


def make(events, chat_id="777", chat_env=""):
    api, sender = FakeApi(events, chat_id), FakeSender()
    return AlertService(api, cfg(chat_env), sender), api, sender


async def test_startup_primes_without_resending_then_alerts_new():
    seed = {**EVENT, "uuid": "seed-0000-0000-0001"}
    service, api, sender = make([seed])
    assert await service.poll_once(NOW) == 0 and sender.sent == []  # seed не пересылаем

    fresh = {**EVENT, "clip_key": "clips/x.mp4"}
    api.events = [fresh, seed]
    assert await service.poll_once(NOW) == 1
    msg = sender.sent[0]
    assert msg["chat_id"] == "777" and "Засыпание за рулём" in msg["text"]
    assert msg["media"] == (b"clip-bytes", "x.mp4")
    assert any(d == f"fp:{EVENT['uuid']}" for row in msg["keyboard"] for _, d in row)
    assert await service.poll_once(NOW) == 0  # повторно не шлём


async def test_filters_by_severity_and_panel_types():
    service, api, sender = make([])
    await service.poll_once(NOW)
    api.events = [
        {**EVENT, "uuid": "w", "severity": "warning", "type": "phone"},
        {**EVENT, "uuid": "s", "type": "speeding"},
        {**EVENT, "uuid": "c", "type": "camera_sabotage", "clip_key": None},
    ]
    assert await service.poll_once(NOW) == 1
    assert "Саботаж камеры" in sender.sent[0]["text"] and sender.sent[0]["media"] is None
    assert {"w", "s", "c"} <= set(service.seen)


async def test_waits_for_chat_id_then_delivers_backlog():
    service, api, sender = make([], chat_id="")
    await service.poll_once(NOW)
    api.events = [EVENT]
    assert await service.poll_once(NOW) == 0 and EVENT["uuid"] not in service.seen
    api.notif["telegram_chat_id"] = "-1001234"
    assert await service.poll_once(NOW) == 1 and sender.sent[0]["chat_id"] == "-1001234"


async def test_env_chat_id_is_fallback_and_seen_is_pruned():
    service, api, sender = make([], chat_id="", chat_env="555")
    await service.poll_once(NOW)
    api.events = [EVENT]
    await service.poll_once(NOW)
    assert sender.sent[0]["chat_id"] == "555" and service.is_allowed_chat(555)
    assert not service.is_allowed_chat(556)
    api.events = []  # событие ушло из выдачи (review) — помним его, чтобы не слать повторно
    await service.poll_once(NOW)
    assert EVENT["uuid"] in service.seen
    service.seen[EVENT["uuid"]] = "2000-01-01T00:00:00+00:00"  # а старше окна — забываем
    await service.poll_once(NOW)
    assert service.seen == {}


async def test_handle_review_calls_backend_and_reports_errors():
    service, api, _ = make([])
    ok, footer = await service.handle_review(EVENT["uuid"], "fp", "Айгерим")
    assert ok and api.reviews == [(EVENT["uuid"], "false_positive", "Telegram: Айгерим")]
    assert "❌ Ложное срабатывание · Айгерим" in footer
    api.fail_review = ApiError(404, "Событие не найдено")
    assert await service.handle_review(EVENT["uuid"], "ok", "А") == (
        False,
        "Не удалось: Событие не найдено",
    )


async def test_settings_failure_keeps_last_known_recipients():
    service, api, sender = make([])
    await service.poll_once(NOW)

    async def boom():
        raise ApiError(503, "down")

    await service.recipients()  # кэш заполнен
    api.notifications = boom  # type: ignore[assignment]
    api.events = [EVENT]
    assert await service.poll_once(NOW) == 1 and sender.sent[0]["chat_id"] == "777"


async def test_send_failure_is_retried_then_given_up():
    service, api, sender = make([])
    await service.poll_once(NOW)
    api.events = [EVENT]
    calls = {"n": 0}

    async def flaky(chat_id, text, keyboard, media):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("Telegram: chat not found")
        sender.sent.append({"chat_id": chat_id})

    service.sender.send_alert = flaky  # type: ignore[method-assign]
    assert await service.poll_once(NOW) == 0 and EVENT["uuid"] not in service.seen
    assert await service.poll_once(NOW) == 1 and calls["n"] == 2  # вторая попытка удалась
    assert service.attempts == {}

    async def dead(chat_id, text, keyboard, media):
        raise RuntimeError("down")

    api.events = [{**EVENT, "uuid": "second-0000-0000"}]
    service.sender.send_alert = dead  # type: ignore[method-assign]
    for _ in range(3):
        await service.poll_once(NOW)
    assert "second-0000-0000" in service.seen  # после MAX_ATTEMPTS — не долбим Telegram вечно


async def test_reviewed_then_reverted_event_is_not_resent():
    """Событие исчезло из status=new (review), потом снова new — второй алерт не шлём."""
    service, api, sender = make([])
    await service.poll_once(NOW)
    api.events = [EVENT]
    assert await service.poll_once(NOW) == 1
    api.events = []  # координатор сделал review
    await service.poll_once(NOW)
    api.events = [EVENT]  # и вернул в new
    assert await service.poll_once(NOW) == 0 and len(sender.sent) == 1


async def test_backend_down_gives_api_error_not_crash():
    import httpx

    from dg_bot.api import ApiError, DgApi

    class Boom(httpx.AsyncClient):
        async def request(self, *a, **k):
            raise httpx.ConnectError("refused")

        async def post(self, *a, **k):
            raise httpx.ConnectError("refused")

    api = DgApi("http://localhost:1", "e", "p", client=Boom())
    try:
        await api.summary()
    except ApiError as exc:
        assert exc.status == 503 and "недоступен" in exc.detail
    else:
        raise AssertionError("ожидали ApiError")


async def test_retry_after_waits_without_burning_attempts():
    service, api, sender = make([])
    await service.poll_once(NOW)
    api.events = [EVENT]
    calls = {"n": 0}

    class RetryAfter(Exception):
        retry_after = 0

    async def flaky(chat_id, text, keyboard, media):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RetryAfter()
        sender.sent.append({"chat_id": chat_id})

    service.sender.send_alert = flaky  # type: ignore[method-assign]
    assert await service.poll_once(NOW) == 0 and service.attempts == {}  # попытка не потрачена
    assert await service.poll_once(NOW) == 1
