from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from catalog import load_books, load_movies
from config import MEDIA_BOOK, MEDIA_MOVIE
from database import load_books_profile, load_movies_profile
from media_cards import send_book_card, send_movie_card
from personal_recommend import recommend_personal
from recommendation_movies import is_same_director_movie, MoviesProfile
from recommendation import is_same_author_book, BooksProfile

router = Router()


async def _send_personal(message: Message, media_type: str) -> None:
    catalog = load_books() if media_type == MEDIA_BOOK else load_movies()
    picks = await recommend_personal(message.from_user.id, media_type, catalog)
    if not picks:
        await message.answer(
            "Пока не могу собрать персональную подборку — пройди анкету через /start "
            "или отметь несколько книг/фильмов 👍 и поставь оценки."
        )
        return

    label = "книг" if media_type == MEDIA_BOOK else "фильмов"
    await message.answer(f"Персональные рекомендации ({label}) — с объяснением, почему советую:")

    if media_type == MEDIA_BOOK:
        profile_row = await load_books_profile(message.from_user.id)
        profile = BooksProfile(
            tags_include=set(profile_row.get("tags_include") or []) if profile_row else set(),
            tags_exclude=set(profile_row.get("tags_exclude") or []) if profile_row else set(),
            volume_preference=str(profile_row.get("volume_preference") or "any") if profile_row else "any",
            favorite_book_id=profile_row.get("favorite_book_id") if profile_row else None,
            favorite_author=profile_row.get("favorite_author") if profile_row else None,
        )
        for pick in picks:
            same = is_same_author_book(pick.item, profile)
            await send_book_card(message, pick.item, same_author=same, why=pick.why)
    else:
        profile_row = await load_movies_profile(message.from_user.id)
        profile = MoviesProfile(
            tags_include=set(profile_row.get("tags_include") or []) if profile_row else set(),
            tags_exclude=set(profile_row.get("tags_exclude") or []) if profile_row else set(),
            duration_preference=str(profile_row.get("duration_preference") or "any") if profile_row else "any",
            favorite_movie_id=profile_row.get("favorite_movie_id") if profile_row else None,
            favorite_director=profile_row.get("favorite_director") if profile_row else None,
        )
        catalog_list = catalog
        for pick in picks:
            same = is_same_director_movie(pick.item, profile, catalog_list)
            await send_movie_card(message, pick.item, same_director=same, why=pick.why)


@router.message(Command("recommend"))
async def cmd_recommend(message: Message) -> None:
    books_profile = await load_books_profile(message.from_user.id)
    movies_profile = await load_movies_profile(message.from_user.id)

    if books_profile and movies_profile:
        await message.answer(
            "Что рекомендуем?",
            reply_markup=InlineKeyboardMarkup(
                inline_keyboard=[
                    [
                        InlineKeyboardButton(text="📚 Книги", callback_data="rec:book"),
                        InlineKeyboardButton(text="🎬 Фильмы", callback_data="rec:movie"),
                    ],
                    [InlineKeyboardButton(text="📚+🎬 Оба", callback_data="rec:both")],
                ]
            ),
        )
        return

    if books_profile:
        await _send_personal(message, MEDIA_BOOK)
        return
    if movies_profile:
        await _send_personal(message, MEDIA_MOVIE)
        return

    await message.answer("Сначала пройди анкету: /start → выбери книги или фильмы.")


@router.callback_query(F.data.startswith("rec:"))
async def on_recommend_choice(callback: CallbackQuery) -> None:
    choice = callback.data.split(":", 1)[1]
    if choice == "book":
        await _send_personal(callback.message, MEDIA_BOOK)
    elif choice == "movie":
        await _send_personal(callback.message, MEDIA_MOVIE)
    else:
        await _send_personal(callback.message, MEDIA_BOOK)
        await _send_personal(callback.message, MEDIA_MOVIE)
    await callback.answer()
