import logging

from aiogram import Bot
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup

from catalog import item_by_id, load_books, load_movies
from config import MEDIA_BOOK, MEDIA_MOVIE
from database import fetch_due_reminders, mark_reminder_sent

logger = logging.getLogger(__name__)


def _reminder_keyboard(prefix: str, item_id: int) -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="Читаю / смотрю",
                    callback_data=f"rs:reading:{prefix}:{item_id}",
                ),
                InlineKeyboardButton(
                    text="Досмотрел(а)",
                    callback_data=f"rs:finished:{prefix}:{item_id}",
                ),
            ],
            [
                InlineKeyboardButton(
                    text="Забросил(а)",
                    callback_data=f"rs:dnf:{prefix}:{item_id}",
                ),
                InlineKeyboardButton(
                    text="Ещё не начинал(а)",
                    callback_data=f"rs:later:{prefix}:{item_id}",
                ),
            ],
        ]
    )


async def process_due_reminders(bot: Bot) -> None:
    reminders = await fetch_due_reminders()
    for reminder in reminders:
        user_id = int(reminder["user_id"])
        media_type = str(reminder["media_type"])
        item_id = int(reminder["item_id"])
        prefix = "b" if media_type == MEDIA_BOOK else "m"
        catalog = load_books() if media_type == MEDIA_BOOK else load_movies()
        item = item_by_id(catalog, item_id)
        if not item:
            await mark_reminder_sent(int(reminder["id"]))
            continue

        title = str(item.get("title") or "")
        kind_note = " (сериал)" if item.get("kind") == "series" else ""
        text = (
            f"Прошло около 10 дней — как тебе «{title}»{kind_note}? "
            "Обнови статус, а если досмотрел(а) — потом попросим оценку."
        )
        try:
            await bot.send_message(
                user_id,
                text,
                reply_markup=_reminder_keyboard(prefix, item_id),
            )
        except Exception as exc:
            logger.warning("Не удалось отправить напоминание user=%s: %s", user_id, exc)
            continue
        await mark_reminder_sent(int(reminder["id"]))
