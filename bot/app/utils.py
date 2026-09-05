import re

_FULL_NAME_PATTERN = re.compile(r"^[А-ЯЁа-яё]+(?: [А-ЯЁа-яё]+){2}$")
_NICKNAME_PATTERN = re.compile(r"^[A-Za-zА-ЯЁа-яё]+$")


def validate_full_name(raw: str) -> str | None:
    """Ровно 3 слова на русском, только буквы. Возвращает нормализованную строку или None."""
    normalized = " ".join((raw or "").strip().split())
    if _FULL_NAME_PATTERN.fullmatch(normalized):
        return normalized
    return None


def validate_nickname(raw: str) -> str | None:
    """Только русские/латинские буквы, без цифр и прочих символов."""
    cleaned = (raw or "").strip()
    if _NICKNAME_PATTERN.fullmatch(cleaned):
        return cleaned
    return None


def normalize_phone(raw: str) -> str:
    return "".join(ch for ch in raw if ch.isdigit())
