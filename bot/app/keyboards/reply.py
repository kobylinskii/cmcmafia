"""Единственная оставшаяся нижняя клавиатура -- запрос номера телефона.

Меню внизу больше нет. Reply-клавиатура шлёт в чат обычное текстовое
сообщение на каждое нажатие: история диалога превращалась в колонку из
«👤 Профиль», «📋 Мои регистрации», «🛠️ Админ-меню». Навигация целиком
переехала на инлайн-кнопки (keyboards/inline.main_menu_keyboard) и команды
Telegram, которые в чате не видны вовсе.

Телефон -- исключение по техническим причинам: `request_contact` существует
только у reply-кнопки, инлайновой такой не бывает. Клавиатура показывается
один раз при регистрации и убирается сразу после получения номера
(ui.hide_reply_keyboard).
"""

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup


def request_contact_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[[KeyboardButton(text="📱 Поделиться номером телефона", request_contact=True)]],
        resize_keyboard=True,
        one_time_keyboard=True,
        input_field_placeholder="Нажмите кнопку ниже",
    )
