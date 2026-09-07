import re

_FULL_NAME_PATTERN = re.compile(r"^[А-ЯЁа-яё]+(?: [А-ЯЁа-яё]+){2}$")
# Пробел внутри ника разрешён: «Дядя Фёдор» и «Дед Мороз» -- обычные клубные
# ники, и запрет на них выглядел поломкой. Крайние и повторные пробелы
# схлопываются до разбора, так что «Дядя   Фёдор» и «Дядя Фёдор» -- один ник.
_NICKNAME_PATTERN = re.compile(r"^[A-Za-zА-ЯЁа-яё]+(?: [A-Za-zА-ЯЁа-яё]+)*$")

# Ник -- это как человека зовут в клубе, а не идентификатор: однобуквенный «Я»
# такой же нормальный ник, как и любой другой. Верхняя граница -- от строки в
# составе игры, которая иначе перестаёт помещаться.
NICKNAME_MIN_LENGTH = 1
NICKNAME_MAX_LENGTH = 32


def validate_full_name(raw: str) -> str | None:
    """Ровно 3 слова на русском, только буквы. Возвращает нормализованную строку или None."""
    normalized = " ".join((raw or "").strip().split())
    if _FULL_NAME_PATTERN.fullmatch(normalized):
        return normalized
    return None


def validate_nickname(raw: str) -> str | None:
    """Русские/латинские буквы и пробелы между ними, 1-32 символа.

    Возвращает нормализованную строку или None. Длину проверяет здесь же: она
    и раньше проверялась в двух местах (регистрация и правка профиля) двумя
    копиями одного условия, и границы в них успели разъехаться.
    """
    cleaned = " ".join((raw or "").split())
    if not _NICKNAME_PATTERN.fullmatch(cleaned):
        return None
    if not (NICKNAME_MIN_LENGTH <= len(cleaned) <= NICKNAME_MAX_LENGTH):
        return None
    return cleaned


def normalize_phone(raw: str) -> str:
    return "".join(ch for ch in raw if ch.isdigit())
