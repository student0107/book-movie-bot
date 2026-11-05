from aiogram import F, Router
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup

from catalog import item_by_id, load_books, load_movies
from config import MEDIA_BOOK, MEDIA_MOVIE
from database import reschedule_reminder, set_library_entry, set_rating
from media_cards import apply_choice_to_caption, reaction_keyboard

router = Router()


def _media_from_prefix(prefix: str) -> str:
    return MEDIA_BOOK if prefix == "b" else MEDIA_MOVIE


def _catalog(media_type: str):
    return load_books() if media_type == MEDIA_BOOK else load_movies()


def rating_keyboard(prefix: str, item_id: int) -> InlineKeyboardMarkup:
    row = [
        InlineKeyboardButton(text=f"★{star}", callback_data=f"rt:{prefix}:{item_id}:{star}")
        for star in range(1, 6)
    ]
    return InlineKeyboardMarkup(
        inline_keyboard=[
            row,
            [InlineKeyboardButton(text="Пропустить", callback_data=f"rx:{prefix}:{item_id}")],
        ]
    )


async def _update_card_reaction(
    callback: CallbackQuery,
    media_type: str,
    item_id: int,
    choice: str,
) -> None:
    if not callback.message:
        return
    markup = reaction_keyboard(media_type, item_id, choice)  # type: ignore[arg-type]
    current = callback.message.caption or callback.message.text or ""
    new_text = apply_choice_to_caption(current, choice)  # type: ignore[arg-type]
    if callback.message.photo:
        await callback.message.edit_caption(caption=new_text, reply_markup=markup)
    else:
        await callback.message.edit_text(new_text, reply_markup=markup)


@router.callback_query(F.data.regexp(r"^ry:(b|m):\d+$"))
async def on_reaction_yes(callback: CallbackQuery) -> None:
    _, prefix, item_id_raw = callback.data.split(":")
    media_type = _media_from_prefix(prefix)
    item_id = int(item_id_raw)
    await set_library_entry(
        callback.from_user.id,
        media_type,
        item_id,
        "planned",
        schedule_rating=True,
    )
    await _update_card_reaction(callback, media_type, item_id, "planned")
    await callback.answer("В планах ✓")


@router.callback_query(F.data.regexp(r"^rn:(b|m):\d+$"))
async def on_reaction_no(callback: CallbackQuery) -> None:
    _, prefix, item_id_raw = callback.data.split(":")
    media_type = _media_from_prefix(prefix)
    item_id = int(item_id_raw)

    await set_library_entry(
        callback.from_user.id,
        media_type,
        item_id,
        "not_interested",
        schedule_rating=False,
    )
    await _update_card_reaction(callback, media_type, item_id, "not_interested")
    await callback.answer("Отметил: не моё")


@router.callback_query(F.data.regexp(r"^rt:(b|m):\d+:[1-5]$"))
async def on_rating(callback: CallbackQuery) -> None:
    _, prefix, item_id_raw, star_raw = callback.data.split(":")
    media_type = _media_from_prefix(prefix)
    item_id = int(item_id_raw)
    rating = int(star_raw)

    await set_rating(callback.from_user.id, media_type, item_id, rating)
    await callback.answer(f"Спасибо! Записал ★{rating}")
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.regexp(r"^rx:(b|m):\d+$"))
async def on_rating_skip(callback: CallbackQuery) -> None:
    await callback.answer("Ок")
    if callback.message:
        await callback.message.edit_reply_markup(reply_markup=None)


@router.callback_query(F.data.regexp(r"^rs:(reading|finished|dnf|later):(b|m):\d+$"))
async def on_reminder_status(callback: CallbackQuery) -> None:
    _, status, prefix, item_id_raw = callback.data.split(":")
    media_type = _media_from_prefix(prefix)
    item_id = int(item_id_raw)
    user_id = callback.from_user.id

    if status == "later":
        await set_library_entry(user_id, media_type, item_id, "planned", schedule_rating=False)
        await reschedule_reminder(user_id, media_type, item_id, days=7)
        await callback.answer("Напомню через неделю")
        return

    await set_library_entry(user_id, media_type, item_id, status, schedule_rating=False)
    if status == "finished":
        item = item_by_id(_catalog(media_type), item_id)
        title = str(item.get("title") if item else "")
        await callback.message.answer(
            f"Круто! Поставь оценку «{title}» от 1 до 5:",
            reply_markup=rating_keyboard(prefix, item_id),
        )
        await callback.answer()
        return

    await callback.answer("Записал статус")
