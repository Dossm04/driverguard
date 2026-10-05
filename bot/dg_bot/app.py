"""Сборка бота: aiogram polling Telegram + фоновый опрос backend."""

import asyncio
import logging
import sys
import time

from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.enums import ParseMode
from aiogram.types import BotCommand
from aiogram.utils.token import TokenValidationError

from dg_bot import config
from dg_bot.api import DgApi
from dg_bot.handlers import TelegramSender, router
from dg_bot.service import AlertService

log = logging.getLogger("driverguard.bot")
COMMANDS = [
    BotCommand(command="status", description="Машины онлайн и KPI дня"),
    BotCommand(command="leaderboard", description="Score водителей за 7 дней"),
    BotCommand(command="help", description="Что умеет бот и Chat ID"),
]


def build_bot(cfg: config.Config) -> Bot:
    session = None
    if cfg.telegram_api_base:  # локальный/тестовый сервер Bot API (docs/telegram.md)
        session = AiohttpSession(api=TelegramAPIServer.from_base(cfg.telegram_api_base))
    return Bot(cfg.token, session=session, default=DefaultBotProperties(parse_mode=ParseMode.HTML))


async def run(cfg: config.Config) -> None:
    bot = build_bot(cfg)
    api = DgApi(cfg.api_url, cfg.api_email, cfg.api_password)
    service = AlertService(api, cfg, TelegramSender(bot))
    dp = Dispatcher()
    dp.include_router(router)
    dp["service"] = service
    me = await bot.get_me()
    await bot.set_my_commands(COMMANDS)
    log.info(
        "Бот @%s запущен; backend %s; опрос каждые %.0f с", me.username, cfg.api_url, cfg.poll_s
    )
    poller = asyncio.create_task(service.run_forever(), name="backend-poller")
    try:
        await dp.start_polling(bot, handle_signals=False)
    finally:
        poller.cancel()
        await api.close()
        await bot.session.close()


def main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s"
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)  # не логировать каждый опрос
    cfg = config.load()
    if not cfg.token:
        log.info("TELEGRAM_BOT_TOKEN не задан — бот в режиме ожидания (см. docs/telegram.md)")
        try:
            while True:  # не выходим: compose с restart перезапускал бы контейнер бесконечно
                time.sleep(3600)
        except KeyboardInterrupt:
            return 0
    try:
        asyncio.run(run(cfg))
    except TokenValidationError:
        log.error("TELEGRAM_BOT_TOKEN неверного формата: ожидается «123456:ABC-…» от BotFather")
        return 1
    except KeyboardInterrupt:
        log.info("Остановлен")
    return 0


if __name__ == "__main__":
    sys.exit(main())
