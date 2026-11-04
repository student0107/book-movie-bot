from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from catalog import load_movies
from config import MEDIA_MOVIE, MOVIE_TAGS, DURATION_OPTIONS
from database import add_shown_ids, save_movies_profile
from media_cards import send_movie_card
from recommendation_movies import (
    MoviesProfile,
    recommend_movies,
    recommendation_intro_movies,
    is_same_director_movie,
)
from recommendation_ai import (
    apply_llm_order,
    build_taste_summary,
    deliver_survey_recommendations,
    profile_row_for_user,
    profile_row_from_state,
)

router = Router()

M2_SKIP_MARKUP = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="⏭ Пропустить", callback_data="m2_skip")]]
)
M5_SKIP_MARKUP = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="⏭ Пропустить", callback_data="m5_skip")]]
)


class MoviesStates(StatesGroup):
    q1_tags = State()
    q2_favorite = State()
    q3_exclude = State()
    q4_volume = State()
    q5_expectations = State()


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
    text = "Чего точно не хочешь? Выбери теги, «Готово» или нажми «Пропустить»."
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


async def _go_to_movies_q3(message: Message, state: FSMContext) -> None:
    await state.set_state(MoviesStates.q3_exclude)
    await state.update_data(tags_exclude=[])
    msg = await message.answer("Дальше — что точно не хочешь 👇")
    await show_movies_q3(msg, state, edit=False)


async def _finish_movies_survey(
    message: Message,
    state: FSMContext,
    user_id: int,
    expectations: str,
) -> None:
    await state.update_data(expectations_raw=expectations)
    data = await state.get_data()
    tags_include = _as_tag_set(data.get("tags_include"))
    tags_exclude = _as_tag_set(data.get("tags_exclude"))
    duration_key = str(data.get("duration_preference") or "any")
    favorite_raw = str(data.get("favorite_movie_raw") or "")

    wait_msg = await message.answer("Сохраняю ответы и собираю подборку…")

    taste_summary = await build_taste_summary(
        MEDIA_MOVIE,
        tags_include=tags_include,
        tags_exclude=tags_exclude,
        size_key=duration_key,
        favorite_raw=favorite_raw,
        expectations_raw=expectations,
    )
    await state.update_data(taste_summary=taste_summary)

    completed_at = datetime.now(timezone.utc).isoformat()
    await save_movies_profile(
        user_id,
        tags_include=tags_include,
        tags_exclude=tags_exclude,
        duration_preference=duration_key,
        favorite_movie_raw=favorite_raw,
        favorite_movie_id=None,
        favorite_director=None,
        expectations_raw=expectations,
        taste_summary=taste_summary,
        completed_at=completed_at,
    )

    await wait_msg.edit_text("Готово — вот что подобрал:")
    await send_recommendations(message, state)


async def send_recommendations(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile_row = profile_row_from_state(data, MEDIA_MOVIE)
    await deliver_survey_recommendations(
        message,
        message.from_user.id,
        MEDIA_MOVIE,
        profile_row,
        state,
    )


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
        "Какой фильм или сериал реально зацепил? Напиши своими словами — "
        "название или «про что» было. Или нажми «Пропустить».",
        reply_markup=M2_SKIP_MARKUP,
    )
    await callback.answer()


@router.callback_query(MoviesStates.q2_favorite, F.data == "m2_skip")
async def m2_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(
        favorite_movie_raw="",
        favorite_movie_id=None,
        favorite_director=None,
    )
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.edit_text("Ок, пропускаем этот вопрос.")
    await _go_to_movies_q3(callback.message, state)
    await callback.answer()


@router.message(MoviesStates.q2_favorite)
async def q2_favorite_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer(
            "Напиши ответ текстом или нажми «Пропустить» под предыдущим вопросом.",
        )
        return

    if text.lower() in {"пропустить", "skip", "-"}:
        await state.update_data(
            favorite_movie_raw="",
            favorite_movie_id=None,
            favorite_director=None,
        )
    else:
        await state.update_data(
            favorite_movie_raw=text,
            favorite_movie_id=None,
            favorite_director=None,
        )
        await message.answer("Запомнил — учту это в подборке.")

    await _go_to_movies_q3(message, state)


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
    await state.set_state(MoviesStates.q5_expectations)
    await callback.message.edit_text(
        "Чего ты ждёшь от просмотра? Например: лёгкий вечер, адреналин, "
        "сериал на несколько дней, чтобы думать — своими словами. "
        "Или нажми «Пропустить».",
        reply_markup=M5_SKIP_MARKUP,
    )
    await callback.answer()


@router.callback_query(MoviesStates.q5_expectations, F.data == "m5_skip")
async def m5_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
    await _finish_movies_survey(
        callback.message,
        state,
        callback.from_user.id,
        expectations="",
    )


@router.message(MoviesStates.q5_expectations)
async def q5_expectations_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer(
            "Напиши ответ текстом или нажми «Пропустить» под вопросом выше.",
        )
        return

    if text.lower() in {"пропустить", "skip", "-"}:
        expectations = ""
    else:
        expectations = text

    await _finish_movies_survey(
        message,
        state,
        message.from_user.id,
        expectations=expectations,
    )


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

    profile_row = await profile_row_for_user(callback.from_user.id, MEDIA_MOVIE, data)

    books, why_map = await apply_llm_order(
        MEDIA_MOVIE,
        profile_row,
        books,
        len(books),
    )

    await callback.message.answer(recommendation_intro_movies(meta))
    new_ids: list[int] = []
    for book in books:
        same = is_same_director_movie(book, profile, catalog)
        why = why_map.get(int(book["id"]), "")
        await send_movie_card(callback.message, book, same_director=same, why=why)
        new_ids.append(int(book["id"]))

    await add_shown_ids(callback.from_user.id, MEDIA_MOVIE, new_ids)
    await state.update_data(recommendation_offset=offset + len(new_ids))
    await callback.answer()
