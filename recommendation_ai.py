from __future__ import annotations

from typing import Any

from aiogram.fsm.context import FSMContext
from aiogram.types import InlineKeyboardButton, InlineKeyboardMarkup, Message

from catalog import item_by_id, load_books, load_movies
from config import (
    DURATION_OPTIONS,
    MEDIA_BOOK,
    MEDIA_MOVIE,
    MOVIE_TAGS,
    RECOMMENDATION_BATCH_SIZE,
    TAGS,
    VOLUME_OPTIONS,
)
from database import add_shown_ids, load_books_profile, load_movies_profile
from llm_client import llm_enabled, rank_catalog_items, summarize_taste
from media_cards import send_book_card, send_movie_card
from recommendation import BooksProfile, is_same_author_book, recommend_books, recommendation_intro
from recommendation_movies import (
    MoviesProfile,
    is_same_director_movie,
    recommend_movies,
    recommendation_intro_movies,
)


def _tag_labels(media_type: str, tag_ids: set[str]) -> list[str]:
    mapping = TAGS if media_type == MEDIA_BOOK else MOVIE_TAGS
    return [mapping.get(tag, tag) for tag in sorted(tag_ids)]


def _size_label(media_type: str, key: str) -> str:
    options = VOLUME_OPTIONS if media_type == MEDIA_BOOK else DURATION_OPTIONS
    return options.get(key, key)


async def build_taste_summary(
    media_type: str,
    *,
    tags_include: set[str],
    tags_exclude: set[str],
    size_key: str,
    favorite_raw: str,
    expectations_raw: str,
) -> str:
    media_label = "книги" if media_type == MEDIA_BOOK else "фильмы/сериалы"
    return await summarize_taste(
        media_label=media_label,
        favorite_raw=favorite_raw,
        expectations_raw=expectations_raw,
        tags_want=_tag_labels(media_type, tags_include),
        tags_avoid=_tag_labels(media_type, tags_exclude),
        size_label=_size_label(media_type, size_key),
    )


async def apply_llm_order(
    media_type: str,
    profile_row: dict[str, Any],
    candidates: list[dict[str, Any]],
    limit: int,
) -> tuple[list[dict[str, Any]], dict[int, str]]:
    taste = str(profile_row.get("taste_summary") or "")
    favorite_raw = str(
        profile_row.get("favorite_book_raw")
        if media_type == MEDIA_BOOK
        else profile_row.get("favorite_movie_raw")
        or ""
    )
    expectations_raw = str(profile_row.get("expectations_raw") or "")
    tags_include = set(profile_row.get("tags_include") or [])
    tags_exclude = set(profile_row.get("tags_exclude") or [])
    size_key = str(
        profile_row.get("volume_preference")
        if media_type == MEDIA_BOOK
        else profile_row.get("duration_preference")
        or "any"
    )

    if not llm_enabled():
        return candidates[:limit], {}

    ranked = await rank_catalog_items(
        media_label="книги" if media_type == MEDIA_BOOK else "фильмы",
        taste_summary=taste,
        favorite_raw=favorite_raw,
        expectations_raw=expectations_raw,
        tags_want=_tag_labels(media_type, tags_include),
        tags_avoid=_tag_labels(media_type, tags_exclude),
        size_label=_size_label(media_type, size_key),
        candidates=candidates,
        limit=limit,
    )
    if not ranked:
        return candidates[:limit], {}

    why_map = {item_id: why for item_id, why in ranked}
    ordered: list[dict[str, Any]] = []
    catalog = load_books() if media_type == MEDIA_BOOK else load_movies()
    for item_id, _ in ranked:
        item = item_by_id(catalog, item_id)
        if item:
            ordered.append(item)

    seen = {int(item["id"]) for item in ordered}
    for item in candidates:
        item_id = int(item["id"])
        if item_id in seen:
            continue
        ordered.append(item)
        seen.add(item_id)
        if len(ordered) >= limit:
            break

    return ordered[:limit], why_map


def _books_profile_from_row(row: dict[str, Any]) -> BooksProfile:
    return BooksProfile(
        tags_include=set(row.get("tags_include") or []),
        tags_exclude=set(row.get("tags_exclude") or []),
        volume_preference=str(row.get("volume_preference") or "any"),
        favorite_book_id=row.get("favorite_book_id"),
        favorite_book_raw=str(row.get("favorite_book_raw") or ""),
        favorite_author=row.get("favorite_author"),
    )


def _movies_profile_from_row(row: dict[str, Any]) -> MoviesProfile:
    return MoviesProfile(
        tags_include=set(row.get("tags_include") or []),
        tags_exclude=set(row.get("tags_exclude") or []),
        duration_preference=str(row.get("duration_preference") or "any"),
        favorite_movie_id=row.get("favorite_movie_id"),
        favorite_movie_raw=str(row.get("favorite_movie_raw") or ""),
        favorite_director=row.get("favorite_director"),
    )


async def profile_row_for_user(
    user_id: int,
    media_type: str,
    state_data: dict[str, Any],
) -> dict[str, Any]:
    row = profile_row_from_state(state_data, media_type)
    db_row = (
        await load_books_profile(user_id)
        if media_type == MEDIA_BOOK
        else await load_movies_profile(user_id)
    )
    if not db_row:
        return row
    for key in (
        "tags_include",
        "tags_exclude",
        "taste_summary",
        "expectations_raw",
        "volume_preference",
        "duration_preference",
        "favorite_book_raw",
        "favorite_movie_raw",
        "favorite_book_id",
        "favorite_movie_id",
        "favorite_author",
        "favorite_director",
    ):
        if key in db_row and db_row[key]:
            row[key] = db_row[key]
    return row


def profile_row_from_state(data: dict[str, Any], media_type: str) -> dict[str, Any]:
    row: dict[str, Any] = {
        "tags_include": data.get("tags_include") or [],
        "tags_exclude": data.get("tags_exclude") or [],
        "expectations_raw": str(data.get("expectations_raw") or ""),
        "taste_summary": str(data.get("taste_summary") or ""),
    }
    if media_type == MEDIA_BOOK:
        row["volume_preference"] = str(data.get("volume_preference") or "any")
        row["favorite_book_raw"] = str(data.get("favorite_book_raw") or "")
        row["favorite_book_id"] = data.get("favorite_book_id")
        row["favorite_author"] = data.get("favorite_author")
    else:
        row["duration_preference"] = str(data.get("duration_preference") or "any")
        row["favorite_movie_raw"] = str(data.get("favorite_movie_raw") or "")
        row["favorite_movie_id"] = data.get("favorite_movie_id")
        row["favorite_director"] = data.get("favorite_director")
    return row


async def deliver_survey_recommendations(
    message: Message,
    user_id: int,
    media_type: str,
    profile_row: dict[str, Any],
    state: FSMContext,
    *,
    candidate_pool: int = 25,
) -> None:
    if media_type == MEDIA_BOOK:
        catalog = load_books()
        profile = _books_profile_from_row(profile_row)
        candidates, meta = recommend_books(
            catalog,
            profile,
            offset=0,
            limit=candidate_pool,
        )
        intro_fn = recommendation_intro
    else:
        catalog = load_movies()
        profile = _movies_profile_from_row(profile_row)
        candidates, meta = recommend_movies(
            catalog,
            profile,
            offset=0,
            limit=candidate_pool,
        )
        intro_fn = recommendation_intro_movies

    if not candidates:
        await message.answer(
            "Пока в каталоге мало вариантов под твой запрос — скоро добавим ещё. "
            "Можешь пройти анкету заново: /start"
        )
        await state.clear()
        return

    books, why_map = await apply_llm_order(
        media_type,
        profile_row,
        candidates,
        RECOMMENDATION_BATCH_SIZE,
    )

    intro = intro_fn(meta)
    taste = str(profile_row.get("taste_summary") or "").strip()
    if taste and llm_enabled():
        intro = f"{intro}\n\n🧠 Учитываю твои ответы: {taste}"

    await message.answer(intro)
    shown_ids: list[int] = []
    for item in books:
        item_id = int(item["id"])
        why = why_map.get(item_id, "")
        if media_type == MEDIA_BOOK:
            same = is_same_author_book(item, profile)  # type: ignore[arg-type]
            await send_book_card(message, item, same_author=same, why=why)
        else:
            same = is_same_director_movie(item, profile, catalog)  # type: ignore[arg-type]
            await send_movie_card(message, item, same_director=same, why=why)
        shown_ids.append(item_id)

    await add_shown_ids(user_id, media_type, shown_ids)
    await state.update_data(recommendation_offset=len(shown_ids))
    more_data = "books_more" if media_type == MEDIA_BOOK else "movies_more"
    await message.answer(
        "Хочешь ещё варианты?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Ещё варианты", callback_data=more_data)],
                [InlineKeyboardButton(text="🏠 В меню", callback_data="go_start")],
            ]
        ),
    )
    await state.set_state(None)
