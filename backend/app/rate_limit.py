from fastapi import Request
from slowapi import Limiter
from slowapi.util import get_remote_address

from app.config import get_settings

settings = get_settings()


def _rate_limit_key(request: Request) -> str:
    """Единая key-функция для всех эндпоинтов (нужен один Limiter на app.state,
    иначе дефолтный обработчик RateLimitExceeded в slowapi берёт заголовки не с
    того инстанса). Бот-трафик приходит с одного IP (сервер бота), поэтому для
    /api/bot/* лимитируем по telegram_id из query, а не по IP — иначе один
    пользователь бота исчерпает лимит для всех. Для /api/admin/* — по сессии
    (cookie), чтобы админы не делили общий лимит."""
    path = request.url.path
    if path.startswith("/api/bot/"):
        tg_id = request.query_params.get("telegram_id")
        if tg_id:
            return f"tg:{tg_id}"
    elif path.startswith("/api/admin/"):
        token = request.cookies.get("access_token")
        if token:
            return f"site:{token}"
    return get_remote_address(request)


limiter = Limiter(key_func=_rate_limit_key, storage_uri=settings.redis_url)
