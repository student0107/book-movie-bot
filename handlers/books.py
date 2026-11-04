from datetime import datetime, timezone

from aiogram import F, Router
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from catalog import find_favorite_book, load_books
from catalog_display import display_title
from config import MEDIA_BOOK, TAGS, VOLUME_OPTIONS
from database import add_shown_ids, save_books_profile
from media_cards import send_book_card
from recommendation import (
    BooksProfile,
    recommend_books,
    recommendation_intro,
    is_same_author_book,
)

router = Router()


class BooksStates(StatesGroup):
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
    text = "Чего точно не хочешь? Можно несколько или пропустить."
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


async def send_recommendations(message: Message, state: FSMContext) -> None:
    data = await state.get_data()
    catalog = load_books()
    profile = BooksProfile(
        tags_include=_as_tag_set(data.get("tags_include")),
        tags_exclude=_as_tag_set(data.get("tags_exclude")),
        volume_preference=str(data.get("volume_preference") or "any"),
        favorite_book_id=data.get("favorite_book_id"),
        favorite_book_raw=str(data.get("favorite_book_raw") or ""),
        favorite_author=data.get("favorite_author"),
    )

    books, meta = recommend_books(catalog, profile, offset=0)
    if not books:
        await message.answer(
            "Пока в каталоге мало книг под твой запрос — скоро добавим ещё. "
            "Можешь пройти анкету заново: /start"
        )
        await state.clear()
        return

    await message.answer(recommendation_intro(meta))
    profile_for_cards = profile
    shown_ids: list[int] = []
    for book in books:
        same = is_same_author_book(book, profile_for_cards)
        await send_book_card(message, book, same_author=same)
        shown_ids.append(int(book["id"]))

    await add_shown_ids(message.from_user.id, MEDIA_BOOK, shown_ids)
    await state.update_data(recommendation_offset=len(shown_ids))
    await message.answer(
        "Хочешь ещё варианты?",
        reply_markup=InlineKeyboardMarkup(
            inline_keyboard=[
                [InlineKeyboardButton(text="🔄 Ещё варианты", callback_data="books_more")],
                [InlineKeyboardButton(text="🏠 В меню", callback_data="go_start")],
            ]
        ),
    )
    await state.set_state(None)


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
        "Какая книга реально зацепила? Напиши название как помнишь — с опечатками норм."
    )
    await callback.answer()


@router.message(BooksStates.q2_favorite)
async def q2_favorite_text(message: Message, state: FSMContext) -> None:
    text = (message.text or "").strip()
    if not text:
        await message.answer("Напиши хотя бы пару букв — или «пропустить», если не хочешь отвечать.")
        return

    if text.lower() in {"пропустить", "skip", "-"}:
        await state.update_data(
            favorite_book_raw="",
            favorite_book_id=None,
            favorite_author=None,
        )
        await state.set_state(BooksStates.q3_exclude)
        await state.update_data(tags_exclude=[])
        msg = await message.answer("Ок, идём дальше.")
        await show_books_q3(msg, state, edit=False)
        return

    catalog = load_books()
    book, suggestions = find_favorite_book(text, catalog)
    await state.update_data(favorite_book_raw=text)

    if book is not None:
        await state.update_data(
            favorite_book_id=int(book["id"]),
            favorite_author=str(book.get("author") or ""),
        )
        await state.set_state(BooksStates.q3_exclude)
        await state.update_data(tags_exclude=[])
        msg = await message.answer(
            f"Запомнил: «{display_title(MEDIA_BOOK, book)}» — дальше подкинем ещё от этого автора 📚"
        )
        await show_books_q3(msg, state, edit=False)
        return

    if suggestions:
        rows = []
        for suggested_book, score in suggestions:
            title = display_title(MEDIA_BOOK, suggested_book)
            rows.append(
                [
                    InlineKeyboardButton(
                        text=f"{title} — совпадение {score}%",
                        callback_data=f"q2pick:{suggested_book['id']}",
                    )
                ]
            )
        rows.append([InlineKeyboardButton(text="Ничего из этого", callback_data="q2_none")])
        await state.set_state(BooksStates.q2_favorite_confirm)
        await message.answer(
            "Похоже, ты имел в виду одно из этого?",
            reply_markup=InlineKeyboardMarkup(inline_keyboard=rows),
        )
        return

    await state.update_data(favorite_book_id=None, favorite_author=None)
    await state.set_state(BooksStates.q3_exclude)
    await state.update_data(tags_exclude=[])
    await message.answer(
        "Такой книги пока нет в каталоге — сохранил название. "
        "Подбор по темам всё равно сработает; по автору добавим, когда книга появится в базе."
    )
    msg = await message.answer("Идём дальше.")
    await show_books_q3(msg, state, edit=False)


@router.callback_query(BooksStates.q2_favorite_confirm, F.data.startswith("q2pick:"))
async def q2_pick_suggestion(callback: CallbackQuery, state: FSMContext) -> None:
    book_id = int(callback.data.split(":", 1)[1])
    catalog = load_books()
    book = next((item for item in catalog if int(item["id"]) == book_id), None)
    if book is None:
        await callback.answer("Книга не найдена", show_alert=True)
        return
    await state.update_data(
        favorite_book_id=book_id,
        favorite_author=str(book.get("author") or ""),
    )
    await state.set_state(BooksStates.q3_exclude)
    await state.update_data(tags_exclude=[])
    await callback.message.edit_text(
        f"Отлично, берём «{display_title(MEDIA_BOOK, book)}» — учту автора в подборке."
    )
    msg = await callback.message.answer("Выбирай, чего не хочешь 👇")
    await show_books_q3(msg, state, edit=False)
    await callback.answer()


@router.callback_query(BooksStates.q2_favorite_confirm, F.data == "q2_none")
async def q2_none(callback: CallbackQuery, state: FSMContext) -> None:
    await state.update_data(favorite_book_id=None, favorite_author=None)
    await state.set_state(BooksStates.q3_exclude)
    await state.update_data(tags_exclude=[])
    await callback.message.edit_text("Ок, идём без привязки к автору.")
    msg = await callback.message.answer("Выбирай, чего не хочешь 👇")
    await show_books_q3(msg, state, edit=False)
    await callback.answer()


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
    data = await state.get_data()
    completed_at = datetime.now(timezone.utc).isoformat()

    await save_books_profile(
        callback.from_user.id,
        tags_include=_as_tag_set(data.get("tags_include")),
        tags_exclude=_as_tag_set(data.get("tags_exclude")),
        volume_preference=volume_key,
        favorite_book_raw=str(data.get("favorite_book_raw") or ""),
        favorite_book_id=data.get("favorite_book_id"),
        favorite_author=data.get("favorite_author"),
        completed_at=completed_at,
    )

    await callback.message.edit_text("Супер, профиль сохранён. Собираю подборку…")
    await send_recommendations(callback.message, state)
    await callback.answer()


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

    await callback.message.answer(recommendation_intro(meta))
    new_ids: list[int] = []
    for book in books:
        same = is_same_author_book(book, profile)
        await send_book_card(callback.message, book, same_author=same)
        new_ids.append(int(book["id"]))

    await add_shown_ids(callback.from_user.id, MEDIA_BOOK, new_ids)
    await state.update_data(recommendation_offset=offset + len(new_ids))
    await callback.answer()
