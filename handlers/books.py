from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from catalog import load_books
from config import MEDIA_BOOK, TAGS, VOLUME_OPTIONS
from database import add_shown_ids, save_books_profile
from media_cards import send_book_card
from recommendation import (
    BooksProfile,
    recommend_books,
    recommendation_intro,
    is_same_author_book,
)
from recommendation_ai import (
    apply_llm_order,
    build_taste_summary,
    deliver_survey_recommendations,
    profile_row_for_user,
    profile_row_from_state,
)

router = Router()

Q2_SKIP_MARKUP = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="⏭ Пропустить", callback_data="q2_skip")]]
)
Q5_SKIP_MARKUP = InlineKeyboardMarkup(
    inline_keyboard=[[InlineKeyboardButton(text="⏭ Пропустить", callback_data="q5_skip")]]
)


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
    markup = tags_keyboard(selected, "q1t", "q1_done")
    if edit:
        await message.edit_text(text, reply_markup=markup)
    else:
        await message.answer(text, reply_markup=markup)


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
        extra_rows=skip_row,
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
    await state.set_state(BooksStates.q2_favorite)
    await callback.message.edit_text(
        "Какая книга реально зацепила? Напиши своими словами — "
        "название, автора или просто «про что» было. Или нажми «Пропустить».",
        reply_markup=Q2_SKIP_MARKUP,
    )
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
    await state.set_state(BooksStates.q4_volume)
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"q4vol:{key}")]
        for key, label in VOLUME_OPTIONS.items()
    ]
    await callback.message.edit_text(
        "Сколько страниц тебе комфортно?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(BooksStates.q3_exclude, F.data == "q3_done")
async def q3_done(callback: CallbackQuery, state: FSMContext) -> None:
    await state.set_state(BooksStates.q4_volume)
    rows = [
        [InlineKeyboardButton(text=label, callback_data=f"q4vol:{key}")]
        for key, label in VOLUME_OPTIONS.items()
    ]
    await callback.message.edit_text(
        "Сколько страниц тебе комфортно?",
        reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
    )
    await callback.answer()


@router.callback_query(BooksStates.q4_volume, F.data.startswith("q4vol:"))
async def q4_volume(callback: CallbackQuery, state: FSMContext) -> None:
    volume_key = callback.data.split(":", 1)[1]
    if volume_key not in VOLUME_OPTIONS:
        await callback.answer("Неизвестный вариант", show_alert=True)
        return

    await state.update_data(volume_preference=volume_key)
    await state.set_state(BooksStates.q5_expectations)
    await callback.message.edit_text(
        "Чего ты ждёшь от следующей книги? Например: лёгко читать перед сном, "
        "сильные эмоции, чтобы думать, похоже на … — своими словами. "
        "Или нажми «Пропустить».",
        reply_markup=Q5_SKIP_MARKUP,
    )
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

    from database import get_shown_ids

    catalog = load_books()
    profile = BooksProfile(
        tags_include=_as_tag_set(data.get("tags_include")),
        tags_exclude=_as_tag_set(data.get("tags_exclude")),
        volume_preference=str(data.get("volume_preference") or "any"),
        favorite_book_id=data.get("favorite_book_id"),
        favorite_book_raw=str(data.get("favorite_book_raw") or ""),
        favorite_author=data.get("favorite_author"),
    )
    shown = await get_shown_ids(callback.from_user.id, MEDIA_BOOK)
    offset = int(data.get("recommendation_offset") or 0)
    books, meta = recommend_books(
        catalog,
        profile,
        offset=offset,
        already_shown=shown,
    )

    if not books:
        await callback.message.answer("Похоже, варианты на сегодня закончились — загляни позже или смени темы.")
        await callback.answer()
        return

    profile_row = await profile_row_for_user(callback.from_user.id, MEDIA_BOOK, data)

    books, why_map = await apply_llm_order(
        MEDIA_BOOK,
        profile_row,
        books,
        len(books),
    )

    await callback.message.answer(recommendation_intro(meta))
    new_ids: list[int] = []
    for book in books:
        same = is_same_author_book(book, profile)
        why = why_map.get(int(book["id"]), "")
        await send_book_card(callback.message, book, same_author=same, why=why)
        new_ids.append(int(book["id"]))

    await add_shown_ids(callback.from_user.id, MEDIA_BOOK, new_ids)
    await state.update_data(recommendation_offset=offset + len(new_ids))
    await callback.answer()
