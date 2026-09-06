"""Подписи и словари значений, общие для клавиатур и текстов экранов.

Раньше карты «текст кнопки -> значение для API» лежали копиями в каждом
обработчике (обращение разбиралось в трёх местах, статус прохода -- в двух), и
добавление эмодзи к кнопке ломало разбор в том файле, который забыли поправить.
Теперь значение приезжает в callback_data, а эти словари нужны только для
показа.
"""

from __future__ import annotations

SALUTATIONS: dict[str, str] = {
    "господин": "🤵 Господин",
    "госпожа": "👒 Госпожа",
}

AFFILIATIONS: dict[str, str] = {
    "vmk": "🎓 С ВМК",
    "mgu_no_pass": "🏛️ Из МГУ, пропуск не нужен",
    "outside_need_pass": "🪪 Вне МГУ, нужен пропуск",
}

# Короткие подписи для карточки профиля: там уже есть заголовок поля, и эмодзи
# из кнопок только шумит.
AFFILIATION_SHORT: dict[str, str] = {
    "vmk": "с ВМК",
    "mgu_no_pass": "из МГУ, пропуск не нужен",
    "outside_need_pass": "вне МГУ, нужен пропуск",
}

FAVORITE_ROLES: dict[str, str] = {
    "mafia": "🖤 Мафия",
    "don": "🎩 Дон",
    "sheriff": "⭐ Шериф",
    "citizen": "👤 Мирный",
}

GAME_TYPES: dict[str, str] = {
    "funky": "🎉 Фанки",
    "training": "📚 Обучающие",
}

ALL_GAMES = "all"
ALL_GAMES_LABEL = "📋 Все форматы"

REGISTRATION_ROLES: dict[str, str] = {
    "player": "🎭 Игрок",
    "staff": "🎙️ Ведущий/судья",
}

ROSTER_ROLES: dict[str, str] = {
    "host": "Ведущий",
    "judge": "Судья",
    "player": "Игрок",
    "reserve": "Резерв",
}

CONFIRMATION_STATUS: dict[str, str] = {
    "pending": "⏳ На проверке у администратора",
    "confirmed": "✅ Подтверждён",
    "rejected": "⛔ Заявка отклонена",
}


def game_type_title(game_type: str) -> str:
    return ALL_GAMES_LABEL if game_type == ALL_GAMES else GAME_TYPES.get(game_type, game_type)


def is_known_game_type(game_type: str) -> bool:
    return game_type == ALL_GAMES or game_type in GAME_TYPES


def preferred_roles_text(can_play: bool, can_staff: bool) -> str:
    parts = [name for name, flag in (("игрок", can_play), ("ведущий/судья", can_staff)) if flag]
    return ", ".join(parts) if parts else "не выбраны"
