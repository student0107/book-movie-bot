from typing import Any

from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from catalog_display import display_title
from config import MEDIA_BOOK, MEDIA_MOVIE, MIN_RATINGS_FOR_PUBLIC_SCORE, STATUS_LABELS
from database import get_item_rating_stats


def reaction_keyboard(media_type: str, item_id: int) -> InlineKeyboardMarkup:
    prefix = "b" if media_type == MEDIA_BOOK else "m"
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(
                    text="👍 В планы",
                    callback_data=f"ry:{prefix}:{item_id}",
                ),
                InlineKeyboardButton(
                    text="👎 Не моё",
                    callback_data=f"rn:{prefix}:{item_id}",
                ),
            ],
        ]
    )


async def public_rating_line(media_type: str, item_id: int) -> str:
    avg, count = await get_item_rating_stats(media_type, item_id)
    if avg is None or count < MIN_RATINGS_FOR_PUBLIC_SCORE:
        return ""
    word = "читателей" if media_type == MEDIA_BOOK else "зрителей"
    return f"\n⭐ {avg:.1f} · {count} {word}"


def format_book_caption(
    book: dict[str, Any],
    *,
    same_author: bool = False,
    why: str = "",
    rating_line: str = "",
) -> str:
    title = display_title(MEDIA_BOOK, book)
    author = str(book.get("author") or "Автор не указан")
    pages = book.get("pages")
    pages_line = f"{pages} стр." if pages is not None else "объём не указан"
    lines = []
    if same_author:
        lines.append("📌 Ещё от этого автора")
    lines.append(f"📖 {title}")
    lines.append(f"✍️ {author}")
    lines.append(f"📄 {pages_line}")
    if why:
        lines.append(f"💡 {why}")
    if rating_line:
        lines.append(rating_line.strip())
    return "\n".join(lines)


def format_movie_caption(
    movie: dict[str, Any],
    *,
    same_director: bool = False,
    why: str = "",
    rating_line: str = "",
) -> str:
    title = display_title(MEDIA_MOVIE, movie)
    director = str(movie.get("director") or "Режиссёр не указан")
    year = movie.get("year")
    minutes = movie.get("minutes")
    kind = str(movie.get("kind") or "film")
    lines = []
    if kind == "series":
        lines.append("📺 Сериал")
    if same_director:
        lines.append("📌 Ещё от этого режиссёра")
    lines.append(f"📽 {title}")
    if year:
        lines.append(f"🎬 {director} · {year}")
    else:
        lines.append(f"🎬 {director}")
    if minutes:
        suffix = "мин/серия" if kind == "series" else "мин"
        lines.append(f"⏱ {minutes} {suffix}")
    if why:
        lines.append(f"💡 {why}")
    if rating_line:
        lines.append(rating_line.strip())
    return "\n".join(lines)


async def send_book_card(
    message: Message,
    book: dict[str, Any],
    *,
    same_author: bool = False,
    why: str = "",
) -> None:
    from config import MEDIA_BOOK

    item_id = int(book["id"])
    rating_line = await public_rating_line(MEDIA_BOOK, item_id)
    caption = format_book_caption(
        book,
        same_author=same_author,
        why=why,
        rating_line=rating_line,
    )
    cover = (book.get("cover_url") or "").strip()
    markup = reaction_keyboard(MEDIA_BOOK, item_id)
    if cover:
        await message.answer_photo(cover, caption=caption, reply_markup=markup)
    else:
        await message.answer(caption, reply_markup=markup)


async def send_movie_card(
    message: Message,
    movie: dict[str, Any],
    *,
    same_director: bool = False,
    why: str = "",
) -> None:
    from config import MEDIA_MOVIE

    item_id = int(movie["id"])
    rating_line = await public_rating_line(MEDIA_MOVIE, item_id)
    caption = format_movie_caption(
        movie,
        same_director=same_director,
        why=why,
        rating_line=rating_line,
    )
    poster = (movie.get("poster_url") or "").strip()
    markup = reaction_keyboard(MEDIA_MOVIE, item_id)
    if poster:
        await message.answer_photo(poster, caption=caption, reply_markup=markup)
    else:
        await message.answer(caption, reply_markup=markup)


def status_label(status: str) -> str:
    return STATUS_LABELS.get(status, status)
