from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from config import MAX_SAME_AUTHOR_IN_BATCH, RECOMMENDATION_BATCH_SIZE
from catalog import book_by_id


@dataclass
class BooksProfile:
    tags_include: set[str]
    tags_exclude: set[str]
    volume_preference: str
    favorite_book_id: int | None = None
    favorite_book_raw: str = ""
    favorite_author: str | None = None


@dataclass
class RecommendationMeta:
    relaxed: bool = False
    dropped_tags: list[str] = field(default_factory=list)
    volume_relaxed: bool = False
    tags_used: list[str] = field(default_factory=list)
    includes_same_author: bool = False
    same_author_name: str | None = None


def _pages_match(pages: int | None, volume: str) -> bool:
    if volume == "any" or pages is None:
        return True
    if volume == "short":
        return pages <= 300
    if volume == "medium":
        return 300 < pages <= 600
    if volume == "long":
        return pages > 600
    return True


def _has_excluded_tags(book: dict[str, Any], exclude: set[str]) -> bool:
    book_tags = set(book.get("tags") or [])
    return bool(book_tags & exclude)


def _has_all_tags(book: dict[str, Any], include: set[str]) -> bool:
    if not include:
        return True
    book_tags = set(book.get("tags") or [])
    return include.issubset(book_tags)


def _apply_hard_filters(
    catalog: list[dict[str, Any]],
    exclude: set[str],
    volume: str,
    *,
    volume_strict: bool,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for book in catalog:
        if _has_excluded_tags(book, exclude):
            continue
        pages = book.get("pages")
        if volume_strict and not _pages_match(pages if pages is None else int(pages), volume):
            continue
        result.append(book)
    return result


def _narrowest_tag(pool: list[dict[str, Any]], active_tags: set[str]) -> str | None:
    if not active_tags:
        return None
    counts: dict[str, int] = {tag: 0 for tag in active_tags}
    for book in pool:
        book_tags = set(book.get("tags") or [])
        for tag in active_tags:
            if tag in book_tags:
                counts[tag] += 1
    return min(active_tags, key=lambda tag: (counts[tag], tag))


def _score_book(
    book: dict[str, Any],
    original_tags: set[str],
    exclude: set[str],
    volume: str,
    *,
    same_author: bool,
) -> float:
    book_tags = set(book.get("tags") or [])
    overlap = len(book_tags & original_tags)
    exclude_hits = len(book_tags & exclude)
    pages = book.get("pages")
    volume_ok = _pages_match(pages if pages is None else int(pages), volume)

    score = overlap * 10.0
    score -= exclude_hits * 50.0
    if volume_ok:
        score += 3.0
    if same_author:
        score += 25.0
    if overlap == len(original_tags) and original_tags:
        score += 5.0
    return score


def _tag_based_search(
    catalog: list[dict[str, Any]],
    profile: BooksProfile,
) -> tuple[list[dict[str, Any]], RecommendationMeta]:
    meta = RecommendationMeta()
    original_tags = set(profile.tags_include)
    active_tags = set(profile.tags_include)
    exclude = set(profile.tags_exclude)
    volume = profile.volume_preference

    base_pool = _apply_hard_filters(catalog, exclude, volume, volume_strict=True)
    volume_relaxed = False

    while True:
        matched = [book for book in base_pool if _has_all_tags(book, active_tags)]
        if matched:
            meta.tags_used = sorted(active_tags)
            meta.dropped_tags = sorted(original_tags - active_tags)
            meta.relaxed = bool(meta.dropped_tags)
            meta.volume_relaxed = volume_relaxed
            matched.sort(
                key=lambda book: _score_book(
                    book,
                    original_tags,
                    exclude,
                    volume,
                    same_author=is_same_author_book(book, profile),
                ),
                reverse=True,
            )
            return matched, meta

        if active_tags:
            narrow = _narrowest_tag(base_pool, active_tags)
            if narrow is None:
                break
            active_tags.remove(narrow)
            continue

        if volume != "any" and not volume_relaxed:
            volume_relaxed = True
            base_pool = _apply_hard_filters(catalog, exclude, "any", volume_strict=True)
            active_tags = set()
            continue

        break

    scored_pool = _apply_hard_filters(catalog, exclude, "any", volume_strict=False)
    scored_pool.sort(
        key=lambda book: _score_book(
            book,
            original_tags,
            exclude,
            volume,
            same_author=is_same_author_book(book, profile),
        ),
        reverse=True,
    )
    meta.relaxed = True
    meta.volume_relaxed = volume != "any"
    meta.tags_used = []
    meta.dropped_tags = sorted(original_tags)
    return scored_pool, meta


def _normalize_author(author: str | None) -> str | None:
    if not author:
        return None
    return " ".join(str(author).lower().split())


def is_same_author_book(book: dict[str, Any], profile: BooksProfile) -> bool:
    author = _normalize_author(profile.favorite_author)
    if not author:
        return False
    return _normalize_author(str(book.get("author") or "")) == author


def _resolve_favorite_author(profile: BooksProfile, catalog: list[dict[str, Any]]) -> str | None:
    if profile.favorite_author:
        return _normalize_author(profile.favorite_author)
    if profile.favorite_book_id is not None:
        book = book_by_id(catalog, profile.favorite_book_id)
        if book:
            return _normalize_author(str(book.get("author") or ""))
    return None


def same_author_books(
    catalog: list[dict[str, Any]],
    profile: BooksProfile,
    *,
    skip_ids: set[int],
) -> list[dict[str, Any]]:
    author = _resolve_favorite_author(profile, catalog)
    if not author:
        return []

    exclude = set(profile.tags_exclude)
    favorite_id = profile.favorite_book_id
    original_tags = set(profile.tags_include)
    volume = profile.volume_preference

    candidates: list[dict[str, Any]] = []
    for book in catalog:
        book_id = int(book["id"])
        if book_id in skip_ids:
            continue
        if favorite_id is not None and book_id == int(favorite_id):
            continue
        if _normalize_author(str(book.get("author") or "")) != author:
            continue
        if _has_excluded_tags(book, exclude):
            continue
        candidates.append(book)

    candidates.sort(
        key=lambda book: _score_book(
            book,
            original_tags,
            exclude,
            volume,
            same_author=True,
        ),
        reverse=True,
    )
    return candidates


def recommend_books(
    catalog: list[dict[str, Any]],
    profile: BooksProfile,
    *,
    offset: int = 0,
    limit: int = RECOMMENDATION_BATCH_SIZE,
    already_shown: set[int] | None = None,
) -> tuple[list[dict[str, Any]], RecommendationMeta]:
    shown = set(already_shown or [])
    tag_results, meta = _tag_based_search(catalog, profile)

    author = _resolve_favorite_author(profile, catalog)
    if author:
        meta.same_author_name = author
        favorite = book_by_id(catalog, profile.favorite_book_id)
        if favorite:
            meta.same_author_name = str(favorite.get("author") or author)

    merged: list[dict[str, Any]] = []
    seen_ids: set[int] = set()

    for book in tag_results:
        book_id = int(book["id"])
        if book_id in seen_ids:
            continue
        merged.append(book)
        seen_ids.add(book_id)

    same_author = same_author_books(
        catalog,
        profile,
        skip_ids=seen_ids | shown,
    )
    injected = 0
    for book in same_author:
        if injected >= MAX_SAME_AUTHOR_IN_BATCH:
            break
        book_id = int(book["id"])
        if book_id in seen_ids:
            continue
        merged.append(book)
        seen_ids.add(book_id)
        injected += 1

    if injected > 0:
        meta.includes_same_author = True

    merged.sort(
        key=lambda book: (
            0 if is_same_author_book(book, profile) else 1,
            -_score_book(
                book,
                set(profile.tags_include),
                set(profile.tags_exclude),
                profile.volume_preference,
                same_author=is_same_author_book(book, profile),
            ),
        ),
    )

    slice_start = offset
    slice_end = offset + limit
    page = [book for book in merged[slice_start:slice_end] if int(book["id"]) not in shown]

    if not page and offset == 0:
        for book in merged:
            book_id = int(book["id"])
            if book_id in shown:
                continue
            page.append(book)
            if len(page) >= limit:
                break

    return page, meta


def recommendation_intro(meta: RecommendationMeta) -> str:
    parts: list[str] = []
    if meta.relaxed and meta.dropped_tags:
        parts.append(
            "Точного совпадения по всем темам не нашлось — подобрал максимально близкое."
        )
    elif not meta.relaxed:
        parts.append("Вот что попало под твои темы и настройки.")

    if meta.volume_relaxed:
        parts.append("По объёму чуть шире, чем ты просил — но в тему.")

    if meta.includes_same_author and meta.same_author_name:
        parts.append(
            f"Добавил ещё книги автора {meta.same_author_name} — раз его книга тебе зашла."
        )

    return " ".join(parts) if parts else "Лови подборку:"


def format_book_card(book: dict[str, Any], *, same_author: bool) -> str:
    title = str(book.get("title") or "Без названия")
    author = str(book.get("author") or "Автор не указан")
    pages = book.get("pages")
    pages_line = f"{pages} стр." if pages is not None else "объём не указан"
    prefix = "📌 Ещё от этого автора\n" if same_author else ""
    return f"{prefix}📖 {title}\n✍️ {author}\n📄 {pages_line}"
