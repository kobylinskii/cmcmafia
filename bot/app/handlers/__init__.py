from aiogram import Dispatcher

from .admin import router as admin_router
from .common import router as common_router
from .profile import router as profile_router
from .registration import router as registration_router
from .schedule import router as schedule_router


def setup_routers(dp: Dispatcher) -> None:
    # Порядок важен ровно в двух местах:
    #  * registration идёт первым -- его обработчики привязаны к состояниям
    #    незавершённой регистрации и не должны конкурировать с меню;
    #  * common идёт последним -- в нём catch-all на любой текст.
    dp.include_router(registration_router)
    dp.include_router(profile_router)
    dp.include_router(schedule_router)
    dp.include_router(admin_router)
    dp.include_router(common_router)
