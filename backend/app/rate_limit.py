from fastapi import Request
from jose import JWTError
from slowapi import Limiter
from slowapi.util import get_remote_address

from app import security
from app.config import get_settings

settings = get_settings()


def _rate_limit_key(request: Request) -> str:
    """Единая key-функция для всех эндпоинтов (нужен один Limiter на app.state,
    иначе дефолтный обработчик RateLimitExceeded в slowapi берёт заголовки не с
    того инстанса). Бот-трафик приходит с одного IP (сервер бота), поэтому для
    /api/bot/* лимитируем по telegram_id из query, а не по IP — иначе один
    пользователь бота исчерпает лимит для всех. Для /api/admin/* — по сессии
    (cookie), чтобы админы не делили общий лимит.

    Во всех остальных случаях ключ -- IP клиента, и он обязан быть настоящим:
    за nginx uvicorn подставит IP из X-Forwarded-For только если ему разрешили
    доверять прокси (FORWARDED_ALLOW_IPS, выставляется в docker-compose.yml).
    Без этого request.client.host -- это IP контейнера nginx, один и тот же для
    всех посетителей, и лимит 60/мин становится лимитом на весь сайт целиком.

    Тело запроса в key-функции недоступно (оно ещё не прочитано), поэтому бот
    дублирует telegram_id в query даже там, где сервер берёт его из тела --
    см. bot/mafia-tg-bot/app/api_client.py."""
    path = request.url.path
    if path.startswith("/api/bot/"):
        tg_id = request.query_params.get("telegram_id")
        if tg_id:
            return f"tg:{tg_id}"
    elif path.startswith("/api/admin/"):
        token = request.cookies.get("access_token")
        if token:
            # Ключуем по идентификатору админа, а не по самому токену: access
            # живёт 15 минут, и на ключе-токене лимит обнулялся после каждого
            # обновления сессии. Заодно полный JWT не оседает в ключах Redis.
            # Подпись здесь не проверяем -- это делает require_site_admin;
            # ключ нужен лишь для того, чтобы админы не делили общий лимит.
            try:
                return f"site:{security.decode_token(token, 'access')['sub']}"
            except JWTError:
                pass
    return get_remote_address(request)


limiter = Limiter(key_func=_rate_limit_key, storage_uri=settings.redis_url)
