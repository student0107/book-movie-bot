from aiogram import F, Router
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from handlers.books import BooksStates, show_books_q1
from handlers.movies import MoviesStates, show_movies_q1

router = Router()


def welcome_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="▶ Старт", callback_data="go_start")],
        ]
    )


def main_choice_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📚 Книги", callback_data="pick_books"),
                InlineKeyboardButton(text="🎬 Фильмы", callback_data="pick_movies"),
            ],
        ]
    )


@router.message(CommandStart())
async def cmd_start(message: Message, state: FSMContext) -> None:
    await state.clear()
    await message.answer(
        "Привет! Я помогу подобрать книгу или фильм под твой вайб. "
        "Когда будешь готов — жми старт 👇",
        reply_markup=welcome_keyboard(),
    )


@router.callback_query(F.data == "go_start")
async def on_go_start(callback: CallbackQuery) -> None:
    await callback.message.edit_text(
        "Что ищем?",
        reply_markup=main_choice_keyboard(),
    )
    await callback.answer()


@router.callback_query(F.data == "pick_movies")
async def on_pick_movies(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(MoviesStates.q1_tags)
    await state.update_data(tags_include=[])
    await show_movies_q1(callback.message, state, edit=True)
    await callback.answer()


@router.callback_query(F.data == "pick_books")
async def on_pick_books(callback: CallbackQuery, state: FSMContext) -> None:
    await state.clear()
    await state.set_state(BooksStates.q1_tags)
    await state.update_data(tags_include=[])
    await show_books_q1(callback.message, state, edit=True)
    await callback.answer()
