"""Логика бота без Telegram: опрос backend, отбор событий, review по кнопкам.

Sender — то, что умеет отправить алерт (в проде — aiogram, в тестах — заглушка).
"""

import asyncio
import logging
import time
from datetime import UTC, datetime, timedelta
from typing import Protocol

from dg_bot import format as fmt
from dg_bot.api import ApiError, DgApi
from dg_bot.config import Config

log = logging.getLogger("driverguard.bot")
WINDOW = timedelta(hours=24)  # события старше суток бот не «догоняет»
MAX_ATTEMPTS = 3  # после трёх неудачных отправок алерт считается потерянным (в лог — error)


class Sender(Protocol):
    async def send_alert(
        self,
        chat_id: str,
        text: str,
        keyboard: list[list[tuple[str, str]]],
        media: tuple[bytes, str] | None,
    ) -> None: ...


class AlertService:
    def __init__(self, api: DgApi, cfg: Config, sender: Sender):
        self.api = api
        self.cfg = cfg
        self.sender = sender
        self.seen: dict[str, str] = {}  # uuid → ts события; забываем только старше окна
        self.attempts: dict[str, int] = {}
        self.primed = False
        self._recipients: tuple[str, list[str]] = (cfg.chat_id_env, [])
        self._recipients_at = 0.0
        self._warned_no_chat = 0.0

    async def recipients(self) -> tuple[str, list[str]]:
        """(chat_id, типы) из Настроек панели (BOT-4); chat_id из .env — запасной вариант."""
        now = time.monotonic()
        if now - self._recipients_at < self.cfg.settings_refresh_s:
            return self._recipients
        try:
            value = await self.api.notifications()
            chat_id = (value.get("telegram_chat_id") or "").strip() or self.cfg.chat_id_env
            self._recipients = (chat_id, list(value.get("critical_types") or []))
            self._recipients_at = now
        except (ApiError, Exception) as exc:  # noqa: BLE001 — сеть/backend: работаем на старом кэше
            log.warning("Не удалось прочитать настройки уведомлений: %s", exc)
        return self._recipients

    def is_allowed_chat(self, chat_id: int | str) -> bool:
        return bool(self._recipients[0]) and str(chat_id) == self._recipients[0]

    async def poll_once(self, now: datetime | None = None) -> int:
        """Один цикл опроса: новые критические события → алерты. Возвращает число отправленных."""
        now = now or datetime.now(UTC)
        events = await self.api.new_events((now - WINDOW).isoformat())
        if not self.primed:  # при старте не пересылаем накопившееся (в т.ч. seed)
            self.seen = {e["uuid"]: e["ts"] for e in events}
            self.primed = True
            return 0
        chat_id, types = await self.recipients()
        sent = 0
        for e in sorted(events, key=lambda x: x["ts"]):  # старые раньше
            if e["uuid"] in self.seen:
                continue
            if not fmt.should_alert(e, types):
                self.seen[e["uuid"]] = e["ts"]
                continue
            if not chat_id:
                if time.monotonic() - self._warned_no_chat > 60:
                    log.warning("Есть критическое событие, но chat_id не задан — алерт ждёт")
                    self._warned_no_chat = time.monotonic()
                continue  # не помечаем: отправим, когда координатор укажет chat_id
            media = None
            if e.get("clip_key"):
                data = await self.api.clip_bytes(e["uuid"])
                if data:
                    media = (data, e["clip_key"].rsplit("/", 1)[-1] or "clip.mp4")
            try:
                await self.sender.send_alert(
                    chat_id,
                    fmt.alert_text(e, self.cfg.tz, self.cfg.web_url),
                    fmt.alert_keyboard(e["uuid"], bool(e.get("driver_phone"))),
                    media,
                )
            except Exception as exc:  # noqa: BLE001 — Telegram/сеть: повторим на следующем опросе
                retry_after = getattr(exc, "retry_after", None)
                if retry_after is not None:  # flood-control Telegram: ждём, попытку не тратим
                    log.warning("Telegram просит подождать %s с", retry_after)
                    await asyncio.sleep(float(retry_after))
                    continue
                attempts = self.attempts.get(e["uuid"], 0) + 1
                self.attempts[e["uuid"]] = attempts
                if attempts >= MAX_ATTEMPTS:
                    log.error(
                        "Алерт %s не доставлен после %d попыток: %s", e["uuid"], attempts, exc
                    )
                    self.seen[e["uuid"]] = e["ts"]
                else:
                    log.warning("Алерт %s не отправлен (попытка %d): %s", e["uuid"], attempts, exc)
                continue
            self.attempts.pop(e["uuid"], None)
            self.seen[e["uuid"]] = e["ts"]
            sent += 1
        # Забываем только события старше окна: обрезка по странице ответа (200 шт.) или уход
        # события из status=new после review вернули бы уже отправленные алерты
        horizon = (now - WINDOW - timedelta(hours=1)).isoformat()
        self.seen = {u: ts for u, ts in self.seen.items() if ts >= horizon}
        return sent

    async def run_forever(self) -> None:
        while True:
            try:
                n = await self.poll_once()
                if n:
                    log.info("Отправлено алертов: %d", n)
            except Exception:  # noqa: BLE001 — цикл опроса не должен умирать
                log.exception("Опрос backend не удался")
            await asyncio.sleep(self.cfg.poll_s)

    async def handle_review(self, event_uuid: str, action: str, actor: str) -> tuple[bool, str]:
        """Кнопка «Подтвердить»/«Ложное» → POST /events/{uuid}/review. (успех, текст)."""
        status = fmt.REVIEW_ACTIONS[action]
        try:
            await self.api.review(event_uuid, status, comment=f"Telegram: {actor}")
        except ApiError as exc:
            return False, f"Не удалось: {exc.detail}"
        when = fmt.local_time(datetime.now(UTC).isoformat(), self.cfg.tz)
        return True, fmt.review_footer(status, actor, when)

    async def driver_phone(self, event_uuid: str) -> tuple[str | None, str]:
        """Телефон водителя для «Позвонить»: (телефон, имя)."""
        e = await self.api.request("GET", f"/events/{event_uuid}")
        return e.get("driver_phone"), e.get("driver_name") or "Водитель"
