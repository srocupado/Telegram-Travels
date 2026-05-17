from aiogram import Router

from bot.handlers import (
    compras,
    congress,
    followup,
    manage,
    ping,
    roteiro,
    search,
    start,
    traffic,
    watch,
)

router = Router(name="root")
router.include_router(start.router)
router.include_router(ping.router)
router.include_router(roteiro.router)
router.include_router(compras.router)
router.include_router(followup.router)
router.include_router(search.router)
router.include_router(manage.router)
router.include_router(congress.router)
router.include_router(traffic.router)
router.include_router(watch.router)
