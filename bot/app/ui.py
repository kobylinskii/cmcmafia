"""Один живой экран на раздел.

Главная причина, по которой старый бот выглядел сломанным: каждый шаг слал
НОВОЕ сообщение со своей инлайн-клавиатурой, а прежние оставались в чате
живыми. Человек мог ткнуть вчерашний «выберите день» и провалиться в
устаревший список, а после «Назад» кнопки прошлых шагов продолжали висеть.

Отсюда правило, которого держится весь бот:

* нажатие инлайн-кнопки РЕДАКТИРУЕТ то же сообщение (`edit`) -- в чате не
  появляется ничего нового, и старой клавиатуры не остаётся;
* приход обычного сообщения (ввод текста) УДАЛЯЕТ предыдущий экран и присылает
  новый (`open`) -- чтобы разговор шёл снизу вверх, а наверху не оставалось
  кликабельного мусора.

Второе правило появилось позже первого: в чате копились сообщения самого
человека. Нижнее меню слало «👤 Профиль» текстом на каждое нажатие, а даты и
время админ набирал руками -- в истории оставалась колонка из «06.09.2026» и
«15:00-17:00». Поэтому нижнего меню больше нет вовсе (навигация инлайновая,
см. keyboards/inline.main_menu_keyboard), а всё, что человек всё-таки вводит
руками, бот убирает из чата сразу после разбора (`consume_input`).

Идентификатор актуального экрана лежит в данных FSM, поэтому переживает
рестарт бота вместе с остальным состоянием.
"""

from __future__ import annotations

import logging
from contextlib import suppress

from aiogram.exceptions import TelegramBadRequest
from aiogram.fsm.context import FSMContext
from aiogram.types import (
    BufferedInputFile,
    CallbackQuery,
    InaccessibleMessage,
    InlineKeyboardMarkup,
    Message,
    ReplyKeyboardRemove,
)

logger = logging.getLogger(__name__)

SCREEN_KEY = "screen_message_id"


def _is_not_modified(exc: TelegramBadRequest) -> bool:
    return "message is not modified" in str(exc).lower()


def screen_message(callback: CallbackQuery) -> Message | None:
    """Сообщение, по кнопке которого нажали, если с ним ещё можно работать.

    Telegram отдаёт InaccessibleMessage вместо самого сообщения, когда ему
    больше 48 часов: ни отредактировать, ни ответить на него нельзя. Экран из
    вчерашнего диалога вполне может дожить до такого возраста, и без этой
    проверки нажатие на него падало бы с невнятной ошибкой Telegram вместо
    понятной подсказки открыть раздел заново.
    """
    message = callback.message
    if message is None or isinstance(message, InaccessibleMessage):
        return None
    return message


async def open_screen(
    message: Message, state: FSMContext, text: str, keyboard: InlineKeyboardMarkup | None = None
) -> Message:
    """Показать экран в ответ на обычное сообщение, убрав предыдущий."""
    data = await state.get_data()
    previous = data.get(SCREEN_KEY)
    if previous:
        with suppress(TelegramBadRequest):
            await message.bot.delete_message(chat_id=message.chat.id, message_id=int(previous))
    sent = await message.answer(text, reply_markup=keyboard)
    await state.update_data(**{SCREEN_KEY: sent.message_id})
    return sent


async def open_photo_screen(
    message: Message,
    state: FSMContext,
    photo: bytes,
    text: str,
    keyboard: InlineKeyboardMarkup | None = None,
) -> Message:
    """То же, что open_screen, но экран -- картинка с подписью.

    Нужен ровно одному месту: карточке правки фото в разделе «На проверке».
    Смысл карточки в том, чтобы посмотреть на фото, а текстовое сообщение
    заменить картинкой Telegram не даёт -- только удалить и прислать заново,
    что open_screen и делает.

    Обратный переход (назад к списку) отдельной поддержки не требует:
    edit_screen попробует edit_text, получит от Telegram отказ и сам пришлёт
    текстовый экран взамен этого.
    """
    data = await state.get_data()
    previous = data.get(SCREEN_KEY)
    if previous:
        with suppress(TelegramBadRequest):
            await message.bot.delete_message(chat_id=message.chat.id, message_id=int(previous))
    sent = await message.answer_photo(
        BufferedInputFile(photo, "photo.jpg"), caption=text, reply_markup=keyboard
    )
    await state.update_data(**{SCREEN_KEY: sent.message_id})
    return sent


async def edit_screen(
    callback: CallbackQuery,
    state: FSMContext,
    text: str,
    keyboard: InlineKeyboardMarkup | None = None,
    *,
    alert: str | None = None,
) -> None:
    """Перерисовать экран, по кнопке которого нажали."""
    message = screen_message(callback)
    if message is None:
        await callback.answer(
            "Это сообщение слишком старое. Откройте бота заново командой /menu.", show_alert=True
        )
        return
    try:
        await message.edit_text(text, reply_markup=keyboard)
        await state.update_data(**{SCREEN_KEY: message.message_id})
    except TelegramBadRequest as exc:
        if _is_not_modified(exc):
            # Повторное нажатие той же кнопки -- не ошибка и не требует ответа
            # сверх всплывающего уведомления ниже.
            pass
        else:
            # Сообщение слишком старое для редактирования (Telegram запрещает
            # править чужие и очень давние). Тогда честнее прислать новый
            # экран, чем молча проглотить нажатие.
            logger.info("Не удалось отредактировать экран, присылаем новый: %s", exc)
            await open_screen(message, state, text, keyboard)
    await callback.answer(alert or "", show_alert=bool(alert and len(alert) > 60))


async def drop_screen(state: FSMContext) -> None:
    """Забыть текущий экран, не трогая сообщение (оно уже перерисовано в
    финальное состояние и кнопок не несёт)."""
    await state.update_data(**{SCREEN_KEY: None})


async def consume_input(message: Message) -> None:
    """Убрать из чата то, что человек ввёл руками.

    Введённое значение бот всё равно немедленно показывает в экране раздела,
    так что второй его копией -- сообщением пользователя -- история только
    засоряется. В личном чате бот вправе удалять входящие сообщения, но право
    это не безусловное: сообщению может быть больше 48 часов, у бота могли
    отобрать доступ. Неудача здесь ничего не ломает -- разбор уже прошёл.
    """
    with suppress(TelegramBadRequest):
        await message.delete()


async def hide_reply_keyboard(message: Message) -> None:
    """Убрать нижнюю клавиатуру, не оставив следа в чате.

    Нижних клавиатур в боте осталась ровно одна -- разовый запрос телефона при
    регистрации. Убрать её можно только сообщением с ReplyKeyboardRemove,
    поэтому такое сообщение отправляется и тут же удаляется. Тем же способом
    у старых пользователей снимается меню, оставшееся от прошлой версии бота.
    """
    with suppress(TelegramBadRequest):
        sent = await message.answer("⌛", reply_markup=ReplyKeyboardRemove())
        # Удаляем через bot, а не sent.delete(): ответ Telegram -- это только
        # данные о сообщении, и рассчитывать на привязанный к нему клиент
        # нельзя (в тестах его там и нет).
        await message.bot.delete_message(chat_id=message.chat.id, message_id=sent.message_id)
