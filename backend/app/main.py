from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded

from app.config import get_settings
from app.rate_limit import limiter
from app.routers import admin, admin_schedule, auth, bot, bot_admin, public

settings = get_settings()

# Фоновых задач у API больше нет. Раньше здесь жил свип, сам переводивший
# прошедшую игру в 'played': в «Ждут оценки» из-за него попадало всё подряд,
# включая игры, которые не собрались. Теперь проведение подтверждает человек
# кнопкой в админке сайта (game_service.mark_session_played).
app = FastAPI(title="Mafia Club API")

app.state.limiter = limiter
app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE"],
    allow_headers=["Content-Type", "X-CSRF-Token", "Authorization"],
)

app.mount("/media/players", StaticFiles(directory=settings.media_root, check_dir=False), name="media")

app.include_router(public.router)
app.include_router(auth.router)
app.include_router(admin.router)
app.include_router(admin_schedule.router)
app.include_router(bot.router)
app.include_router(bot_admin.router)


@app.get("/health")
def health() -> dict:
    return {"status": "ok"}
