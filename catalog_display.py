"""Русские подписи для карточек."""
from __future__ import annotations

from typing import Any

from config import MEDIA_BOOK, MEDIA_MOVIE

# Если в JSON только английское название
TITLE_RU: dict[str, dict[int, str]] = {
    MEDIA_BOOK: {
        70: "Осада и буря",
        71: "Разрушение и восстание",
        85: "Брюсингр",
        86: "Наследие",
        92: "Джейн Эйр",
        94: "Эмма",
        99: "451 градус по Фаренгейту",
    },
    MEDIA_MOVIE: {
        4: "La-La Land",
        35: "Send Help",
        78: "Бегущий по лезвию",
        81: "1+1",
        82: "1+1",
        83: "Зелёная книга",
        85: "Одержимость",
        88: "Кинг-Конг",
        96: "Робокоп",
        98: "Безумный Макс: Дорога ярости",
        100: "Дюна",
    },
}


def display_title(media_type: str, item: dict[str, Any]) -> str:
    raw_ru = item.get("title_ru")
    if raw_ru:
        return str(raw_ru)
    item_id = int(item["id"])
    override = TITLE_RU.get(media_type, {}).get(item_id)
    if override:
        return override
    return str(item.get("title") or "Без названия")
