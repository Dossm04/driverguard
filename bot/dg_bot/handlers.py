"""aiogram-обработчики: команды и inline-кнопки. Логика — в service.py."""

import logging

from aiogram import Bot, F, Router
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
from aiogram.filters import Command, CommandStart
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    Message,
)

from dg_bot import format as fmt
from dg_bot.api import ApiError
from dg_bot.service import AlertService

log = logging.getLogger("driverguard.bot.handlers")
router = Router()


def keyboard(rows: list[list[tuple[str, str]]]) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text=t, callback_data=d) for t, d in row] for row in rows
        ]
    )


class TelegramSender:
    """Sender для AlertService: кадр/клип (если скачался) с подписью, иначе текст."""

    def __init__(self, bot: Bot):
        self.bot = bot

    async def send_alert(
        self,
        chat_id: str,
        text: str,
        rows: list[list[tuple[str, str]]],
        media: tuple[bytes, str] | None,
    ) -> None:
        markup = keyboard(rows)
        if media:
            data, name = media
            file = BufferedInputFile(data, filename=name)
            ext = name.rsplit(".", 1)[-1].lower()
            send = (
                self.bot.send_photo
                if ext in ("jpg", "jpeg", "png", "webp")
                else self.bot.send_video
                if ext in ("mp4", "mov", "webm")
                else self.bot.send_document
            )
            try:
                await send(chat_id, file, caption=text, reply_markup=markup)
                return
            except TelegramRetryAfter:
                raise  # flood-control: сервис подождёт и повторит целиком
            except TelegramAPIError as exc:  # слишком большой/битый файл и т.п. — шлём текст
                log.info("Кадр не принят Telegram (%s) — шлём текст", exc)
        await self.bot.send_message(chat_id, text, reply_markup=markup)


async def _guard(message: Message, service: AlertService) -> bool:
    """Команды принимаем только из чата координатора (Настройки → Уведомления)."""
    await service.recipients()
    if service.is_allowed_chat(message.chat.id):
        return True
    await message.answer("⛔ Нет доступа. " + fmt.help_text(message.chat.id, configured=False))
    return False


@router.message(CommandStart())
@router.message(Command("help"))
async def cmd_start(message: Message, service: AlertService) -> None:
    await service.recipients()
    await message.answer(fmt.help_text(message.chat.id, service.is_allowed_chat(message.chat.id)))


@router.message(Command("status"))
async def cmd_status(message: Message, service: AlertService) -> None:
    if not await _guard(message, service):
        return
    try:
        summary, devices = await service.api.summary(), await service.api.devices()
    except ApiError as exc:
        await message.answer(f"Backend недоступен: {exc.detail}")
        return
    await message.answer(fmt.status_text(summary, devices))


@router.message(Command("leaderboard"))
async def cmd_leaderboard(message: Message, service: AlertService) -> None:
    if not await _guard(message, service):
        return
    try:
        lb = await service.api.leaderboard()
    except ApiError as exc:
        await message.answer(f"Backend недоступен: {exc.detail}")
        return
    await message.answer(fmt.leaderboard_text(lb))


@router.callback_query(F.data.regexp(r"^(call|ok|fp):"))
async def on_button(callback: CallbackQuery, service: AlertService) -> None:
    parsed = fmt.parse_callback(callback.data)
    msg = callback.message
    if parsed is None or not isinstance(msg, Message):
        await callback.answer("Кнопка устарела")
        return
    await service.recipients()
    if not service.is_allowed_chat(msg.chat.id):
        await callback.answer("Нет доступа", show_alert=True)
        return
    action, event_uuid = parsed
    actor = callback.from_user.full_name if callback.from_user else "координатор"

    if action == "call":  # tel:-ссылки Telegram в кнопках не принимает — шлём контакт
        try:
            phone, name = await service.driver_phone(event_uuid)
        except ApiError as exc:
            await callback.answer(f"Не удалось: {exc.detail}", show_alert=True)
            return
        if not phone:
            await callback.answer("Телефон водителя не указан", show_alert=True)
            return
        await msg.answer_contact(phone_number=phone, first_name=name)
        await callback.answer()
        return

    ok, text = await service.handle_review(event_uuid, action, actor)
    if not ok:
        await callback.answer(text, show_alert=True)
        return
    try:
        if msg.text is not None:
            await msg.edit_text(msg.html_text + text, reply_markup=None)
        else:
            await msg.edit_caption(caption=(msg.html_text or "") + text, reply_markup=None)
    except TelegramBadRequest as exc:
        log.info("Не удалось обновить сообщение: %s", exc)
    await callback.answer("Статус обновлён")
