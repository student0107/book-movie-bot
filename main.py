import asyncio
import logging
import os
from pathlib import Path

from aiogram import Bot, Dispatcher
from aiogram.fsm.storage.memory import MemoryStorage
from dotenv import load_dotenv

from database import init_db
from handlers import (
    books_router,
    history_router,
    movies_router,
    reactions_router,
    recommend_router,
    start_router,
)
from scheduler import process_due_reminders
from single_instance import ensure_single_instance

load_dotenv()
if not os.getenv("BOT_TOKEN"):
    load_dotenv(Path(__file__).resolve().parent / "moviesb00ks_bot")

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def reminder_worker(bot: Bot) -> None:
    while True:
        try:
            await process_due_reminders(bot)
        except Exception:
            logger.exception("Ошибка в планировщике напоминаний")
        await asyncio.sleep(3600)


async def main() -> None:
    token = os.getenv("BOT_TOKEN")
    if not token:
        raise RuntimeError("Создай файл .env и добавь BOT_TOKEN (см. .env.example)")

    await init_db()

    bot = Bot(token=token)
    dp = Dispatcher(storage=MemoryStorage())

    dp.include_router(start_router)
    dp.include_router(books_router)
    dp.include_router(movies_router)
    dp.include_router(reactions_router)
    dp.include_router(history_router)
    dp.include_router(recommend_router)

    asyncio.create_task(reminder_worker(bot))

    await dp.start_polling(bot)


if __name__ == "__main__":
    ensure_single_instance()
    asyncio.run(main())
