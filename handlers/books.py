from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from catalog import load_books
from config import MEDIA_BOOK, RECOMMENDATION_BATCH_SIZE, TAGS, VOLUME_OPTIONS
from database import add_shown_ids, save_books_profile
from media_cards import send_book_card
from recommendation import (
    BooksProfile,
    recommend_books,
    recommendation_intro,
    is_same_author_book,
)
from recommendation_ai import (
    SURVEY_CANDIDATE_POOL,
    catalog_exhausted_message,
    more_options_limit_message,
    build_taste_summary,
    deliver_survey_recommendations,
    filter_not_shown,
    pick_ranked_batch,
    profile_row_for_user,
    profile_row_from_state,
    send_more_options_prompt,
)

router = Router()

BOOKS_BACK = "books_back"

BOOKS_Q2_TEXT = (
    "Какая книга реально зацепила? Напиши своими словами — "
    "название, автора или просто «про что» было. Или нажми «Пропустить»."
)
BOOKS_Q5_TEXT = (
    "Чего ты ждёшь от следующей книги? Например: лёгко читать перед сном, "
    "сильные эмоции, чтобы думать, похоже на … — своими словами. "
    "Или нажми «Пропустить»."
)


def _back_row(callback_data: str) -> list[list[InlineKeyboardButton]]:
    return [[InlineKeyboardButton(text="◀ Назад", callback_data=callback_data)]]


def books_q2_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⏭ Пропустить", callback_data="q2_skip"),
                InlineKeyboardButton(text="◀ Назад", callback_data=BOOKS_BACK),
            ],
        ]
    )


def books_q5_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="⏭ Пропустить", callback_data="q5_skip"),
                InlineKeyboardButton(text="◀ Назад", callback_data=BOOKS_BACK),
            ],
        ]
    )


def books_q4_keyboard() -> InlineKeyboardMarkup:
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"q4vol:{key}")]
        for key, label in VOLUME_OPTIONS.items()
    ]
    rows.extend(_back_row(BOOKS_BACK))
    return InlineKeyboardMarkup(inline_keyboard=rows)


class BooksStates(StatesGroup):
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
    for tag_id, label in TAGS.items():
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


async def show_books_q1(message: Message, state: FSMContext, *, edit: bool) -> None:
    data = await state.get_data()
    selected = _as_tag_set(data.get("tags_include"))
    text = "Какие темы тебе заходят? Можно несколько — жми теги, потом «Готово»."
    markup = tags_keyboard(
        selected,
        "q1t",
        "q1_done",
        extra_rows=_back_row(BOOKS_BACK),
    )
    if edit:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.answer(text, reply_markup=markup)


async def show_books_q2(message: Message, state: FSMContext, *, edit: bool) -> None:
    await state.set_state(BooksStates.q2_favorite)
    if edit:
        await message.edit_text(BOOKS_Q2_TEXT, reply_markup=books_q2_keyboard())
    else:
        await message.answer(BOOKS_Q2_TEXT, reply_markup=books_q2_keyboard())


async def show_books_q4(message: Message, state: FSMContext, *, edit: bool = True) -> None:
    await state.set_state(BooksStates.q4_volume)
    text = "Сколько страниц тебе комфортно?"
    markup = books_q4_keyboard()
    if edit:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.answer(text, reply_markup=markup)


async def show_books_q5(message: Message, state: FSMContext, *, edit: bool = True) -> None:
    await state.set_state(BooksStates.q5_expectations)
    if edit:
        await message.edit_text(BOOKS_Q5_TEXT, reply_markup=books_q5_keyboard())
    else:
        await message.answer(BOOKS_Q5_TEXT, reply_markup=books_q5_keyboard())


async def show_books_q3(message: Message, state: FSMContext, *, edit: bool = True) -> None:
    data = await state.get_data()
    selected = _as_tag_set(data.get("tags_exclude"))
    include = _as_tag_set(data.get("tags_include"))
    allowed = set(TAGS.keys()) - include
    skip_row = [[InlineKeyboardButton(text="⏭ Пропустить", callback_data="q3_skip")]]
    text = "Чего точно не хочешь? Выбери теги, «Готово» или нажми «Пропустить»."
    markup = tags_keyboard(
        selected,
        "q3t",
        "q3_done",
        allowed_tags=allowed,
        extra_rows=skip_row + _back_row(BOOKS_BACK),
    )
    if edit:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.answer(text, reply_markup=markup)


async def _go_to_books_q3(message: Message, state: FSMContext) -> None:
    await state.set_state(BooksStates.q3_exclude)
    await state.update_data(tags_exclude=[])
    msg = await message.answer("Дальше — что точно не хочешь 👇")
    await show_books_q3(msg, state, edit=False)


async def _finish_books_survey(
    message: Message,
    state: FSMContext,
    user_id: int,
    expectations: str,
) -> None:
    await state.update_data(expectations_raw=expectations)
    data = await state.get_data()
    tags_include = _as_tag_set(data.get("tags_include"))
    tags_exclude = _as_tag_set(data.get("tags_exclude"))
    volume_key = str(data.get("volume_preference") or "any")
    favorite_raw = str(data.get("favorite_book_raw") or "")

    wait_msg = await message.answer("Сохраняю ответы и собираю подборку…")

    taste_summary = await build_taste_summary(
        MEDIA_BOOK,
        tags_include=tags_include,
        tags_exclude=tags_exclude,
        size_key=volume_key,
        favorite_raw=favorite_raw,
        expectations_raw=expectations,
    )
    await state.update_data(taste_summary=taste_summary)

    completed_at = datetime.now(timezone.utc).isoformat()
    await save_books_profile(
        user_id,
        tags_include=tags_include,
        tags_exclude=tags_exclude,
        volume_preference=volume_key,
        favorite_book_raw=favorite_raw,
        favorite_book_id=None,
        favorite_author=None,
        expectations_raw=expectations,
        taste_summary=taste_summary,
        completed_at=completed_at,
    )

    await wait_msg.edit_text("Готово — вот что подобрал:")
    await send_recommendations(message, state)


async def send_recommendations(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    profile_row = profile_row_from_state(data, MEDIA_BOOK)
    await deliver_survey_recommendations(
        message,
        message.from_user.id,
        MEDIA_BOOK,
        profile_row,
        state,
    )


@router.callback_query(BooksStates.q1_tags, F.data.startswith("q1t:"))
async def q1_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    tag_id = callback.data.split(":", 1)[1]
    data = await state.get_data()
    selected = _as_tag_set(data.get("tags_include"))
    if tag_id in selected:
        selected.remove(tag_id)
    else:
        selected.add(tag_id)
    await state.update_data(tags_include=sorted(selected))
    await show_books_q1(callback.message, state, edit=True)
    await callback.answer()


@router.callback_query(BooksStates.q1_tags, F.data == "q1_done")
async def q1_done(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    selected = _as_tag_set(data.get("tags_include"))
    if not selected:
        await callback.answer("Выбери хотя бы один тег", show_alert=True)
        return
    await show_books_q2(callback.message, state, edit=True)
    await callback.answer()


@router.callback_query(F.data == BOOKS_BACK)
async def books_back(callback: CallbackQuery, state: FSMContext) -> None:
    current = await state.get_state()
    if current == BooksStates.q1_tags.state:
        from handlers.start import main_choice_keyboard

        await state.clear()
        await callback.message.edit_text(
            "Что ищем?",
            reply_markup=main_choice_keyboard(),
        )
    elif current == BooksStates.q2_favorite.state:
        await state.set_state(BooksStates.q1_tags)
        await show_books_q1(callback.message, state, edit=True)
    elif current == BooksStates.q3_exclude.state:
        await show_books_q2(callback.message, state, edit=True)
    elif current == BooksStates.q4_volume.state:
        await state.set_state(BooksStates.q3_exclude)
        await show_books_q3(callback.message, state, edit=True)
    elif current == BooksStates.q5_expectations.state:
        await show_books_q4(callback.message, state, edit=True)
    else:
        await callback.answer()
        return
    await callback.answer()


@router.callback_query(BooksStates.q2_favorite, F.data == "q2_skip")
async def q2_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(
        favorite_book_raw="",
        favorite_book_id=None,
        favorite_author=None,
    )
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.message.edit_text("Ок, пропускаем этот вопрос.")
    await _go_to_books_q3(callback.message, state)
    await callback.answer()


@router.message(BooksStates.q2_favorite)
async def q2_favorite_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer(
            "Напиши ответ текстом или нажми «Пропустить» под предыдущим вопросом.",
        )
        return

    if text.lower() in {"пропустить", "skip", "-"}:
        await state.update_data(
            favorite_book_raw="",
            favorite_book_id=None,
            favorite_author=None,
        )
    else:
        await state.update_data(
            favorite_book_raw=text,
            favorite_book_id=None,
            favorite_author=None,
        )
        await message.answer("Запомнил — учту это в подборке.")

    await _go_to_books_q3(message, state)


@router.callback_query(BooksStates.q3_exclude, F.data.startswith("q3t:"))
async def q3_toggle(callback: CallbackQuery, state: FSMContext) -> None:
    tag_id = callback.data.split(":", 1)[1]
    data = await state.get_data()
    selected = _as_tag_set(data.get("tags_exclude"))
    if tag_id in selected:
        selected.remove(tag_id)
    else:
        selected.add(tag_id)
    await state.update_data(tags_exclude=sorted(selected))
    await show_books_q3(callback.message, state)
    await callback.answer()


@router.callback_query(BooksStates.q3_exclude, F.data == "q3_skip")
async def q3_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(tags_exclude=[])
    await show_books_q4(callback.message, state, edit=True)
    await callback.answer()


@router.callback_query(BooksStates.q3_exclude, F.data == "q3_done")
async def q3_done(callback: CallbackQuery, state: FSMContext) -> None:
    await show_books_q4(callback.message, state, edit=True)
    await callback.answer()


@router.callback_query(BooksStates.q4_volume, F.data.startswith("q4vol:"))
async def q4_volume(callback: CallbackQuery, state: FSMContext) -> None:
    volume_key = callback.data.split(":", 1)[1]
    if volume_key not in VOLUME_OPTIONS:
        await callback.answer("Неизвестный вариант", show_alert=True)
        return

    await state.update_data(volume_preference=volume_key)
    await show_books_q5(callback.message, state, edit=True)
    await callback.answer()


@router.callback_query(BooksStates.q5_expectations, F.data == "q5_skip")
async def q5_skip(callback: CallbackQuery, state: FSMContext) -> None:
    await callback.message.edit_reply_markup(reply_markup=None)
    await callback.answer()
    await _finish_books_survey(
        callback.message,
        state,
        callback.from_user.id,
        expectations="",
    )


@router.message(BooksStates.q5_expectations)
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

    await _finish_books_survey(
        message,
        state,
        message.from_user.id,
        expectations=expectations,
    )


@router.callback_query(F.data == "books_more")
async def books_more(callback: CallbackQuery, state: FSMContext) -> None:
    data = await state.get_data()
    if not data.get("tags_include"):
        await callback.answer("Сначала пройди подбор книг через /start", show_alert=True)
        return

    from database import get_shown_ids, is_more_options_used, set_more_options_used

    user_id = callback.from_user.id
    if await is_more_options_used(user_id, MEDIA_BOOK):
        await callback.message.answer(more_options_limit_message(MEDIA_BOOK))
        await callback.answer()
        return

    catalog = load_books()
    profile = BooksProfile(
        tags_include=_as_tag_set(data.get("tags_include")),
        tags_exclude=_as_tag_set(data.get("tags_exclude")),
        volume_preference=str(data.get("volume_preference") or "any"),
        favorite_book_id=data.get("favorite_book_id"),
        favorite_book_raw=str(data.get("favorite_book_raw") or ""),
        favorite_author=data.get("favorite_author"),
    )
    shown = await get_shown_ids(user_id, MEDIA_BOOK)
    candidates, meta = recommend_books(
        catalog,
        profile,
        limit=SURVEY_CANDIDATE_POOL,
        already_shown=shown,
    )
    candidates = filter_not_shown(candidates, shown)

    if not candidates:
        await set_more_options_used(user_id, MEDIA_BOOK)
        await callback.message.answer(catalog_exhausted_message(MEDIA_BOOK))
        await callback.answer()
        return

    profile_row = await profile_row_for_user(user_id, MEDIA_BOOK, data)

    books, why_map = await pick_ranked_batch(
        MEDIA_BOOK,
        profile_row,
        candidates,
        shown,
        RECOMMENDATION_BATCH_SIZE,
    )

    to_show = [book for book in books if int(book["id"]) not in shown]
    if not to_show:
        await set_more_options_used(user_id, MEDIA_BOOK)
        await callback.message.answer(catalog_exhausted_message(MEDIA_BOOK))
        await callback.answer()
        return

    await set_more_options_used(user_id, MEDIA_BOOK)
    await callback.message.answer(recommendation_intro(meta))
    new_ids: list[int] = []
    for book in to_show:
        book_id = int(book["id"])
        same = is_same_author_book(book, profile)
        why = why_map.get(book_id, "")
        await send_book_card(
            callback.message,
            book,
            same_author=same,
            why=why,
            user_id=user_id,
        )
        new_ids.append(book_id)

    await add_shown_ids(user_id, MEDIA_BOOK, new_ids)
    await send_more_options_prompt(callback.message, MEDIA_BOOK)
    await callback.answer()
