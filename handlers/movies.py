from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from catalog import find_favorite_movie, load_movies
from catalog_display import display_title
from config import MEDIA_MOVIE, MOVIE_TAGS, DURATION_OPTIONS
from database import add_shown_ids, save_movies_profile
from media_cards import send_movie_card
from recommendation_movies import (
    MoviesProfile,
    recommend_movies,
    recommendation_intro_movies,
    is_same_director_movie,
)

router = Router()


class MoviesStates(StatesGroup):
    q1_tags = State()
    q2_favorite = State()
    q2_favorite_confirm = State()
    q3_exclude = State()
    q4_volume = State()


def _as_tag_set(raw) -> set[str]:
    if isinstance(raw, set):
        return raw
    if isinstance(raw, list):
        return set(raw)
    return set()


def tags_keyboard(
    selected: set[str],
    prefix: str,
    done_data: str,
    allowed_tags: set[str] | None = None,
    extra_rows: list[list[InlineKeyboardButton]] | None = None,
) -> InlineKeyboardMarkup:
    rows: list[list[InlineKeyboardButton]] = []
    row: list[InlineKeyboardButton] = []
    for tag_id, label in MOVIE_TAGS.items():
        if allowed_tags is not None and tag_id not in allowed_tags:
            continue
        mark = "✓ " if tag_id in selected else ""
        row.append(
            InlineKeyboardButton(
                text=f"{mark}{label}",
                callback_data=f"{prefix}:{tag_id}",
            )
        )
        if len(row) == 2:
            rows.append(row)
            row = []
    if row:
        rows.append(row)
    rows.append([InlineKeyboardButton(text="✅ Готово", callback_data=done_data)])
    if extra_rows:
        rows.extend(extra_rows)
    return InlineKeyboardMarkup(inline_keyboard=rows)


async def show_movies_q1(message: Message, state: FSMContext, *, edit: bool) -> None:
    data = await state.get_data()
    selected = _as_tag_set(data.get("tags_include"))
    text = "Какие жанры тебе заходят? Можно несколько — жми теги, потом «Готово»."
    markup = tags_keyboard(selected, "m1t", "m1_done")
    if edit:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.answer(text, reply_markup=markup)


async def show_movies_q3(message: Message, state: FSMContext, *, edit: bool = True) -> None:
    data = await state.get_data()
    selected = _as_tag_set(data.get("tags_exclude"))
    include = _as_tag_set(data.get("tags_include"))
    allowed = set(MOVIE_TAGS.keys()) - include
    skip_row = [[InlineKeyboardButton(text="⏭ Пропустить", callback_data="m3_skip")]]
    text = "Чего точно не хочешь? Можно несколько или пропустить."
    markup = tags_keyboard(
        selected,
        "m3t",
        "m3_done",
        allowed_tags=allowed,
        extra_rows=skip_row,
    )
    if edit:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.answer(text, reply_markup=markup)


async def send_recommendations(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    catalog = load_movies()
    profile = MoviesProfile(
        tags_include=_as_tag_set(data.get("tags_include")),
        tags_exclude=_as_tag_set(data.get("tags_exclude")),
        duration_preference=str(data.get("duration_preference") or "any"),
        favorite_movie_id=data.get("favorite_movie_id"),
        favorite_movie_raw=str(data.get("favorite_movie_raw") or ""),
        favorite_director=data.get("favorite_director"),
    )

    books, meta = recommend_movies(catalog, profile, offset=0)
    if not books:
        await message.answer(
            "Пока в каталоге мало фильмов под твой запрос — скоро добавим ещё. "
            "Можешь пройти анкету заново: /start"
        )
        await state.clear()
        return

    await message.answer(recommendation_intro_movies(meta))
    profile_for_cards = profile
    shown_ids: list[int] = []
    for book in books:
        same = is_same_director_movie(book, profile_for_cards, catalog)
        await send_movie_card(message, book, same_director=same)
        shown_ids.append(int(book["id"]))

    await add_shown_ids(message.from_user.id, MEDIA_MOVIE, shown_ids)
    await state.update_data(recommendation_offset=len(shown_ids))
    await message.answer(
        "Хочешь ещё варианты?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Ещё варианты", callback_data="movies_more")],
                [InlineKeyboardButton(text="🏠 В меню", callback_data="go_start")],
            ]
        ),
    )
    await state.set_state(None)


@router.callback_query(MoviesStates.q1_tags, F.data.startswith("m1t:"))
async def q1_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    tag_id = callback.data.split(":", 1)[1]
    data = await state.get_data()
    selected = _as_tag_set(data.get("tags_include"))
    if tag_id in selected:
        selected.remove(tag_id)
    else:
        selected.add(tag_id)
    await state.update_data(tags_include=sorted(selected))
    await show_movies_q1(callback.message, state, edit=True)
    await callback.answer()


@router.callback_query(MoviesStates.q1_tags, F.data == "m1_done")
async def m1_done(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    selected = _as_tag_set(data.get("tags_include"))
    if not selected:
        await callback.answer("Выбери хотя бы один жанр", show_alert=True)
        return
    await state.set_state(MoviesStates.q2_favorite)
    await callback.message.edit_text(
        "Какой фильм реально зацепил? Напиши название как помнишь — с опечатками норм."
    )
    await callback.answer()


@router.message(MoviesStates.q2_favorite)
async def q2_favorite_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Напиши хотя бы пару букв — или «пропустить», если не хочешь отвечать.")
        return

    if text.lower() in {"пропустить", "skip", "-"}:
        await state.update_data(
            favorite_movie_raw="",
            favorite_movie_id=None,
            favorite_director=None,
        )
        await state.set_state(MoviesStates.q3_exclude)
        await state.update_data(tags_exclude=[])
        msg = await message.answer("Ок, идём дальше.")
        await show_movies_q3(msg, state, edit=False)
        return

    catalog = load_movies()
    book, suggestions = find_favorite_movie(text, catalog)
    await state.update_data(favorite_movie_raw=text)

    if book is not None:
        await state.update_data(
            favorite_movie_id=int(book["id"]),
            favorite_director=str(book.get("director") or ""),
        )
        await state.set_state(MoviesStates.q3_exclude)
        await state.update_data(tags_exclude=[])
        msg = await message.answer(
            f"Запомнил: «{display_title(MEDIA_MOVIE, book)}» — дальше подкинем ещё от этого режиссёра 🎬"
        )
        await show_movies_q3(msg, state, edit=False)
        return

    if suggestions:
        rows = []
        for suggested_book, score in suggestions:
            title = display_title(MEDIA_MOVIE, suggested_book)
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"{title} — совпадение {score}%",
                        callback_data=f"m2pick:{suggested_book['id']}",
                    )
                ]
            )
        rows.append([InlineKeyboardButton(text="Ничего из этого", callback_data="m2_none")])
        await state.set_state(MoviesStates.q2_favorite_confirm)
        await message.answer(
            "Похоже, ты имел в виду одно из этого?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
        return

    await state.update_data(favorite_movie_id=None, favorite_director=None)
    await state.set_state(MoviesStates.q3_exclude)
    await state.update_data(tags_exclude=[])
    await message.answer(
        "Такого фильма пока нет в каталоге — сохранил название. "
        "Подбор по жанрам всё равно сработает; по режиссёру добавим, когда фильм появится в базе."
    )
    msg = await message.answer("Идём дальше.")
    await show_movies_q3(msg, state, edit=False)


@router.callback_query(MoviesStates.q2_favorite_confirm, F.data.startswith("m2pick:"))
async def q2_pick_suggestion(callback: CallbackQuery, state: FSMContext) -> None:
    book_id = int(callback.data.split(":", 1)[1])
    catalog = load_movies()
    book = next((item for item in catalog if int(item["id"]) == book_id), None)
    if book is None:
        await callback.answer("Фильм не найден", show_alert=True)
        return
    await state.update_data(
        favorite_movie_id=book_id,
        favorite_director=str(book.get("director") or ""),
    )
    await state.set_state(MoviesStates.q3_exclude)
    await state.update_data(tags_exclude=[])
    await callback.message.edit_text(
        f"Отлично, берём «{display_title(MEDIA_MOVIE, book)}» — учту режиссёра в подборке."
    )
    msg = await callback.message.answer("Выбирай, чего не хочешь 👇")
    await show_movies_q3(msg, state, edit=False)
    await callback.answer()


@router.callback_query(MoviesStates.q2_favorite_confirm, F.data == "m2_none")
async def m2_none(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(favorite_movie_id=None, favorite_director=None)
    await state.set_state(MoviesStates.q3_exclude)
    await state.update_data(tags_exclude=[])
    await callback.message.edit_text("Ок, идём без привязки к режиссёру.")
    msg = await callback.message.answer("Выбирай, чего не хочешь 👇")
    await show_movies_q3(msg, state, edit=False)
    await callback.answer()


@router.callback_query(MoviesStates.q3_exclude, F.data.startswith("m3t:"))
async def q3_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    tag_id = callback.data.split(":", 1)[1]
    data = await state.get_data()
    selected = _as_tag_set(data.get("tags_exclude"))
    if tag_id in selected:
        selected.remove(tag_id)
    else:
        selected.add(tag_id)
    await state.update_data(tags_exclude=sorted(selected))
    await show_movies_q3(callback.message, state)
    await callback.answer()


@router.callback_query(MoviesStates.q3_exclude, F.data == "m3_skip")
async def m3_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(tags_exclude=[])
    await state.set_state(MoviesStates.q4_volume)
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"m4dur:{key}")]
        for key, label in DURATION_OPTIONS.items()
    ]
    await callback.message.edit_text(
        "Какая длительность тебе комфортна? (Для сериалов — одна серия.)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(MoviesStates.q3_exclude, F.data == "m3_done")
async def m3_done(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(MoviesStates.q4_volume)
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"m4dur:{key}")]
        for key, label in DURATION_OPTIONS.items()
    ]
    await callback.message.edit_text(
        "Какая длительность тебе комфортна? (Для сериалов — одна серия.)",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(MoviesStates.q4_volume, F.data.startswith("m4dur:"))
async def q4_volume(callback: CallbackQuery, state: FSMContext) -> None:
    volume_key = callback.data.split(":", 1)[1]
    if volume_key not in DURATION_OPTIONS:
        await callback.answer("Неизвестный вариант", show_alert=True)
        return

    await state.update_data(duration_preference=volume_key)
    data = await state.get_data()
    completed_at = datetime.now(timezone.utc).isoformat()

    await save_movies_profile(
        callback.from_user.id,
        tags_include=_as_tag_set(data.get("tags_include")),
        tags_exclude=_as_tag_set(data.get("tags_exclude")),
        duration_preference=volume_key,
        favorite_movie_raw=str(data.get("favorite_movie_raw") or ""),
        favorite_movie_id=data.get("favorite_movie_id"),
        favorite_director=data.get("favorite_director"),
        completed_at=completed_at,
    )

    await callback.message.edit_text("Супер, профиль сохранён. Собираю подборку…")
    await send_recommendations(callback.message, state)
    await callback.answer()


@router.callback_query(F.data == "movies_more")
async def movies_more(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("tags_include"):
        await callback.answer("Сначала пройди подбор фильмов через /start", show_alert=True)
        return

    from database import get_shown_ids

    catalog = load_movies()
    profile = MoviesProfile(
        tags_include=_as_tag_set(data.get("tags_include")),
        tags_exclude=_as_tag_set(data.get("tags_exclude")),
        duration_preference=str(data.get("duration_preference") or "any"),
        favorite_movie_id=data.get("favorite_movie_id"),
        favorite_movie_raw=str(data.get("favorite_movie_raw") or ""),
        favorite_director=data.get("favorite_director"),
    )
    shown = await get_shown_ids(callback.from_user.id, MEDIA_MOVIE)
    offset = int(data.get("recommendation_offset") or 0)
    books, meta = recommend_movies(
        catalog,
        profile,
        offset=offset,
        already_shown=shown,
    )

    if not books:
        await callback.message.answer("Похоже, варианты на сегодня закончились — загляни позже или смени жанры.")
        await callback.answer()
        return

    await callback.message.answer(recommendation_intro_movies(meta))
    new_ids: list[int] = []
    for book in books:
        same = is_same_director_movie(book, profile, catalog)
        await send_movie_card(callback.message, book, same_director=same)
        new_ids.append(int(book["id"]))

    await add_shown_ids(callback.from_user.id, MEDIA_MOVIE, new_ids)
    await state.update_data(recommendation_offset=offset + len(new_ids))
    await callback.answer()
