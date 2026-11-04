from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from catalog import item_by_id
from config import MEDIA_BOOK, MEDIA_MOVIE, MIN_RATINGS_FOR_PUBLIC_SCORE, RECOMMENDATION_BATCH_SIZE, TAGS, MOVIE_TAGS
from database import (
    get_blocked_item_ids,
    get_dnf_items,
    get_high_rated_item_ids,
    get_item_rating_stats,
    load_books_profile,
    load_movies_profile,
)
from recommendation import BooksProfile, recommend_books
from recommendation_movies import MoviesProfile, recommend_movies


@dataclass
class PersonalPick:
    item: dict[str, Any]
    why: str
    priority: int


def _tag_labels(tags: set[str], media_type: str) -> str:
    mapping = TAGS if media_type == MEDIA_BOOK else MOVIE_TAGS
    names = [mapping.get(tag, tag) for tag in sorted(tags)][:3]
    return ", ".join(names)


async def _rule_same_creator(
    user_id: int,
    media_type: str,
    catalog: list[dict[str, Any]],
    blocked: set[int],
) -> list[PersonalPick]:
    picks: list[PersonalPick] = []
    high_rated = await get_high_rated_item_ids(user_id, media_type)
    creator_field = "author" if media_type == MEDIA_BOOK else "director"
    for item_id, rating in high_rated:
        source = item_by_id(catalog, item_id)
        if not source:
            continue
        creator = str(source.get(creator_field) or "").strip().lower()
        if not creator:
            continue
        for candidate in catalog:
            candidate_id = int(candidate["id"])
            if candidate_id in blocked or candidate_id == item_id:
                continue
            if str(candidate.get(creator_field) or "").strip().lower() != creator:
                continue
            title = str(candidate.get("title") or "")
            source_title = str(source.get("title") or "")
            picks.append(
                PersonalPick(
                    item=candidate,
                    priority=1,
                    why=(
                        f"Тебе зашло «{source_title}» (★{rating}) — "
                        f"это тот же {'автор' if media_type == MEDIA_BOOK else 'режиссёр'}, попробуй «{title}»."
                    ),
                )
            )
    return picks


async def _rule_similar_tags(
    user_id: int,
    media_type: str,
    catalog: list[dict[str, Any]],
    blocked: set[int],
) -> list[PersonalPick]:
    picks: list[PersonalPick] = []
    high_rated = await get_high_rated_item_ids(user_id, media_type)
    if not high_rated:
        return picks

    tag_weights: dict[str, float] = {}
    for item_id, rating in high_rated:
        item = item_by_id(catalog, item_id)
        if not item:
            continue
        weight = 1.0 if rating == 4 else 1.5
        for tag in item.get("tags") or []:
            tag_weights[str(tag)] = tag_weights.get(str(tag), 0.0) + weight

    if not tag_weights:
        return picks

    scored: list[tuple[int, dict[str, Any], set[str]]] = []
    rated_ids = {item_id for item_id, _ in high_rated}
    for candidate in catalog:
        candidate_id = int(candidate["id"])
        if candidate_id in blocked or candidate_id in rated_ids:
            continue
        c_tags = set(candidate.get("tags") or [])
        overlap = c_tags & set(tag_weights.keys())
        if not overlap:
            continue
        score = sum(tag_weights[tag] for tag in overlap)
        scored.append((int(score * 100), candidate, overlap))

    scored.sort(key=lambda row: row[0], reverse=True)
    for _, candidate, overlap in scored:
        picks.append(
            PersonalPick(
                item=candidate,
                priority=2,
                why=(
                    "Похоже на то, что ты уже оценил(а) высоко: общие темы — "
                    f"{_tag_labels(overlap, media_type)}."
                ),
            )
        )
    return picks


async def _rule_series_continue(
    user_id: int,
    media_type: str,
    catalog: list[dict[str, Any]],
    blocked: set[int],
) -> list[PersonalPick]:
    picks: list[PersonalPick] = []
    dnf_ids = await get_dnf_items(user_id, media_type)
    series_field = "series"
    part_field = "series_part" if media_type == MEDIA_BOOK else "franchise_part"
    franchise_field = "franchise" if media_type == MEDIA_MOVIE else "series"

    for dnf_id in dnf_ids:
        dropped = item_by_id(catalog, dnf_id)
        if not dropped:
            continue
        franchise = dropped.get(franchise_field) or dropped.get(series_field)
        part = dropped.get(part_field)
        if not franchise or part is None:
            continue
        next_part = int(part) + 1
        for candidate in catalog:
            candidate_id = int(candidate["id"])
            if candidate_id in blocked:
                continue
            if (candidate.get(franchise_field) or candidate.get(series_field)) != franchise:
                continue
            if candidate.get(part_field) != next_part:
                continue
            picks.append(
                PersonalPick(
                    item=candidate,
                    priority=3,
                    why=(
                        f"Ты бросил(а) «{dropped.get('title')}» — логично продолжить "
                        f"{'серию' if media_type == MEDIA_BOOK else 'франшизу'}: «{candidate.get('title')}»."
                    ),
                )
            )
    return picks


async def _rule_popular_fallback(
    user_id: int,
    media_type: str,
    catalog: list[dict[str, Any]],
    blocked: set[int],
) -> list[PersonalPick]:
    profile = await load_books_profile(user_id) if media_type == MEDIA_BOOK else await load_movies_profile(user_id)
    if not profile:
        return []

    include = set(profile.get("tags_include") or [])
    exclude = set(profile.get("tags_exclude") or [])
    candidates: list[tuple[float, dict[str, Any]]] = []

    for item in catalog:
        item_id = int(item["id"])
        if item_id in blocked:
            continue
        tags = set(item.get("tags") or [])
        if exclude & tags:
            continue
        if include and not (include & tags):
            continue
        avg, count = await get_item_rating_stats(media_type, item_id)
        popularity = (avg or 0.0) * (count if count >= MIN_RATINGS_FOR_PUBLIC_SCORE else 0)
        tag_bonus = len(include & tags) * 2.0
        candidates.append((popularity + tag_bonus, item))

    candidates.sort(key=lambda row: row[0], reverse=True)

    if not candidates:
        if media_type == MEDIA_BOOK:
            survey_profile = BooksProfile(
                tags_include=include,
                tags_exclude=exclude,
                volume_preference=str(profile.get("volume_preference") or "any"),
                favorite_book_id=profile.get("favorite_book_id"),
                favorite_author=profile.get("favorite_author"),
            )
            items, _ = recommend_books(catalog, survey_profile)
        else:
            survey_profile = MoviesProfile(
                tags_include=include,
                tags_exclude=exclude,
                duration_preference=str(profile.get("duration_preference") or "any"),
                favorite_movie_id=profile.get("favorite_movie_id"),
                favorite_director=profile.get("favorite_director"),
            )
            items, _ = recommend_movies(catalog, survey_profile)
        for item in items:
            if int(item["id"]) in blocked:
                continue
            candidates.append((0.0, item))

    picks: list[PersonalPick] = []
    for score, item in candidates:
        avg, count = await get_item_rating_stats(media_type, int(item["id"]))
        audience = "читателей" if media_type == MEDIA_BOOK else "зрителей"
        if avg and count >= MIN_RATINGS_FOR_PUBLIC_SCORE:
            why = (
                f"Популярно среди {audience} с похожими вкусами ({_tag_labels(include, media_type)}): "
                f"★{avg:.1f} ({count} оценок)."
            )
        else:
            why = (
                "Стартовая подборка по жанрам из твоей анкеты — "
                "пока мало оценок от других, опираемся на теги."
            )
        picks.append(PersonalPick(item=item, priority=4, why=why))
    return picks


async def recommend_personal(
    user_id: int,
    media_type: str,
    catalog: list[dict[str, Any]],
    *,
    limit: int = RECOMMENDATION_BATCH_SIZE,
) -> list[PersonalPick]:
    blocked = await get_blocked_item_ids(user_id, media_type)
    rules = [
        await _rule_same_creator(user_id, media_type, catalog, blocked),
        await _rule_similar_tags(user_id, media_type, catalog, blocked),
        await _rule_series_continue(user_id, media_type, catalog, blocked),
        await _rule_popular_fallback(user_id, media_type, catalog, blocked),
    ]

    result: list[PersonalPick] = []
    seen: set[int] = set()
    for priority_index, bucket in enumerate(rules, start=1):
        for pick in bucket:
            item_id = int(pick.item["id"])
            if item_id in seen or item_id in blocked:
                continue
            seen.add(item_id)
            result.append(
                PersonalPick(item=pick.item, why=pick.why, priority=priority_index)
            )
            if len(result) >= limit:
                return result
    return result
