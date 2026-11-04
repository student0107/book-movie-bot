import json
from pathlib import Path
from typing import Any

from rapidfuzz import fuzz, process

from config import FAVORITE_MATCH_THRESHOLD

BOOKS_PATH = Path(__file__).resolve().parent / "data" / "books.json"
MOVIES_PATH = Path(__file__).resolve().parent / "data" / "movies.json"


def load_catalog(path: Path) -> list[dict[str, Any]]:
    with path.open(encoding="utf-8") as file:
        data = json.load(file)
    if not isinstance(data, list):
        raise ValueError(f"{path.name} должен содержать список")
    return data


def load_books() -> list[dict[str, Any]]:
    return load_catalog(BOOKS_PATH)


def load_movies() -> list[dict[str, Any]]:
    return load_catalog(MOVIES_PATH)


def normalize_title(text: str) -> str:
    return " ".join(text.lower().split())


def build_search_choices(catalog: list[dict[str, Any]]) -> dict[str, int]:
    choices: dict[str, int] = {}
    for item in catalog:
        item_id = int(item["id"])
        title = str(item["title"])
        choices[normalize_title(title)] = item_id
        for alias in item.get("aliases") or []:
            choices[normalize_title(str(alias))] = item_id
    return choices


def find_in_catalog(
    user_text: str, catalog: list[dict[str, Any]]
) -> tuple[dict[str, Any] | None, list[tuple[dict[str, Any], int]]]:
    raw = user_text.strip()
    if not raw:
        return None, []

    choices = build_search_choices(catalog)
    if not choices:
        return None, []

    normalized = normalize_title(raw)
    if normalized in choices:
        item_id = choices[normalized]
        item = next(entry for entry in catalog if int(entry["id"]) == item_id)
        return item, [(item, 100)]

    results = process.extract(
        normalized,
        list(choices.keys()),
        scorer=fuzz.WRatio,
        limit=3,
    )
    suggestions: list[tuple[dict[str, Any], int]] = []
    for matched_title, score, _ in results:
        if score < FAVORITE_MATCH_THRESHOLD:
            continue
        item_id = choices[matched_title]
        item = next(entry for entry in catalog if int(entry["id"]) == item_id)
        suggestions.append((item, int(score)))

    if not suggestions:
        return None, []

    best_item, best_score = suggestions[0]
    if len(suggestions) == 1 and best_score >= FAVORITE_MATCH_THRESHOLD:
        return best_item, suggestions

    return None, suggestions


def find_favorite_book(user_text: str, catalog: list[dict[str, Any]] | None = None):
    catalog = catalog or load_books()
    return find_in_catalog(user_text, catalog)


def find_favorite_movie(user_text: str, catalog: list[dict[str, Any]] | None = None):
    catalog = catalog or load_movies()
    return find_in_catalog(user_text, catalog)


def item_by_id(catalog: list[dict[str, Any]], item_id: int | None) -> dict[str, Any] | None:
    if item_id is None:
        return None
    for item in catalog:
        if int(item["id"]) == int(item_id):
            return item
    return None




def book_by_id(catalog: list[dict[str, Any]], book_id: int | None) -> dict[str, Any] | None:
    return item_by_id(catalog, book_id)


def movie_by_id(catalog: list[dict[str, Any]], movie_id: int | None) -> dict[str, Any] | None:
    return item_by_id(catalog, movie_id)
