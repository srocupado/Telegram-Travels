from aiogram import Router

from bot.handlers import manage, ping, roteiro, search, start, watch

router = Router(name="root")
router.include_router(start.router)
router.include_router(ping.router)
router.include_router(roteiro.router)
router.include_router(search.router)
router.include_router(manage.router)
router.include_router(watch.router)
