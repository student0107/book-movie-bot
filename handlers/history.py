from aiogram import F, Router
from aiogram.filters import Command
from aiogram.types import CallbackQuery, InlineKeyboardButton, InlineKeyboardMarkup, Message

from catalog import item_by_id, load_books, load_movies
from catalog_display import display_title
from config import MEDIA_BOOK, MEDIA_MOVIE
from database import list_library
from media_cards import status_label

router = Router()


def _title(media_type: str, item_id: int) -> str:
    catalog = load_books() if media_type == MEDIA_BOOK else load_movies()
    item = item_by_id(catalog, item_id)
    if not item:
        return f"запись №{item_id}"
    prefix = "📺 " if item.get("kind") == "series" else ""
    return prefix + display_title(media_type, item)


def _format_section(title: str, rows: list[str]) -> str:
    if not rows:
        return ""
    body = "\n".join(f"• {line}" for line in rows)
    return f"\n{title}\n{body}"


def _format_plans_group(title: str, rows: list[str]) -> str:
    if rows:
        body = "\n".join(f"• {line}" for line in rows)
    else:
        body = "• пока ничего"
    return f"\n{title}\n{body}"


def plans_menu_keyboard() -> InlineKeyboardMarkup:
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [InlineKeyboardButton(text="◀ В меню", callback_data="go_start")],
        ]
    )


async def build_plans_text(user_id: int) -> str:
    entries = await list_library(user_id)
    planned = [entry for entry in entries if str(entry.get("status") or "") == "planned"]
    if not planned:
        return (
            "📝 Мои планы\n\n"
            "Пока пусто. Отмечай 👍 «В планы» под карточками в подборке."
        )

    book_titles: list[str] = []
    movie_titles: list[str] = []
    for entry in planned:
        media = str(entry.get("media_type") or "")
        title = _title(media, int(entry["item_id"]))
        if media == MEDIA_BOOK:
            book_titles.append(title)
        elif media == MEDIA_MOVIE:
            movie_titles.append(title)

    text = "📝 Мои планы"
    text += _format_plans_group("📚 Книги", book_titles)
    text += _format_plans_group("🎬 Фильмы и сериалы", movie_titles)
    return text.strip()


@router.message(Command("plans"))
async def cmd_plans(message: Message) -> None:
    text = await build_plans_text(message.from_user.id)
    await message.answer(text, reply_markup=plans_menu_keyboard())


@router.callback_query(F.data == "show_plans")
async def on_show_plans(callback: CallbackQuery) -> None:
    text = await build_plans_text(callback.from_user.id)
    await callback.message.answer(text, reply_markup=plans_menu_keyboard())
    await callback.answer()


@router.message(Command("history"))
@router.message(Command("histiry"))
async def cmd_history(message: Message) -> None:
    user_id = message.from_user.id
    entries = await list_library(user_id)
    if not entries:
        await message.answer(
            "История пока пустая. Пройди подбор (/start) или жми /recommend — "
            "и отмечай 👍/👎 под карточками."
        )
        return

    grouped: dict[str, list[str]] = {
        "reading": [],
        "planned": [],
        "finished": [],
        "dnf": [],
        "not_interested": [],
    }

    for entry in entries:
        status = str(entry.get("status") or "")
        if status not in grouped:
            continue
        media = str(entry.get("media_type") or "")
        media_label = "📚" if media == MEDIA_BOOK else "🎬"
        line = f"{media_label} {_title(media, int(entry['item_id']))} — {status_label(status)}"
        rating = entry.get("rating")
        if rating:
            line += f" · ★{rating}"
        grouped[status].append(line)

    text = "Твоя история:"
    text += _format_section("▶️ Читаю / смотрю", grouped["reading"])
    text += _format_section("📝 В планах", grouped["planned"])
    text += _format_section("✅ Прочитал(а) / досмотрел(а)", grouped["finished"])
    text += _format_section("⏸ Забросил(а)", grouped["dnf"])
    text += _format_section("🚫 Не интересно", grouped["not_interested"])

    await message.answer(text.strip())
