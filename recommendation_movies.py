from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from catalog import movie_by_id
from config import MAX_SAME_AUTHOR_IN_BATCH, RECOMMENDATION_BATCH_SIZE
from recommendation import RecommendationMeta, _has_all_tags, _has_excluded_tags, _narrowest_tag


@dataclass
class MoviesProfile:
    tags_include: set[str]
    tags_exclude: set[str]
    duration_preference: str
    favorite_movie_id: int | None = None
    favorite_movie_raw: str = ""
    favorite_director: str | None = None


def _minutes_match(minutes: int | None, duration: str) -> bool:
    if duration == "any" or minutes is None:
        return True
    if duration == "short":
        return minutes <= 90
    if duration == "medium":
        return 90 < minutes <= 150
    if duration == "long":
        return minutes > 150
    return True


def _apply_hard_filters(
    catalog: list[dict[str, Any]],
    exclude: set[str],
    duration: str,
    *,
    duration_strict: bool,
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for movie in catalog:
        if _has_excluded_tags(movie, exclude):
            continue
        minutes = movie.get("minutes")
        if duration_strict and not _minutes_match(
            minutes if minutes is None else int(minutes), duration
        ):
            continue
        result.append(movie)
    return result


def _normalize_director(name: str | None) -> str | None:
    if not name:
        return None
    return " ".join(str(name).lower().split())


def is_same_director_movie(
    movie: dict[str, Any],
    profile: MoviesProfile,
    catalog: list[dict[str, Any]] | None = None,
) -> bool:
    director = _resolve_favorite_director(profile, catalog or [])
    if not director:
        return False
    return _normalize_director(str(movie.get("director") or "")) == director


def _resolve_favorite_director(
    profile: MoviesProfile, catalog: list[dict[str, Any]]
) -> str | None:
    if profile.favorite_director:
        return _normalize_director(profile.favorite_director)
    if profile.favorite_movie_id is not None and catalog:
        movie = movie_by_id(catalog, profile.favorite_movie_id)
        if movie:
            return _normalize_director(str(movie.get("director") or ""))
    return _normalize_director(profile.favorite_director)


def _score_movie(
    movie: dict[str, Any],
    original_tags: set[str],
    exclude: set[str],
    duration: str,
    *,
    same_director: bool,
) -> float:
    movie_tags = set(movie.get("tags") or [])
    overlap = len(movie_tags & original_tags)
    exclude_hits = len(movie_tags & exclude)
    minutes = movie.get("minutes")
    duration_ok = _minutes_match(minutes if minutes is None else int(minutes), duration)

    score = overlap * 10.0
    score -= exclude_hits * 50.0
    if duration_ok:
        score += 3.0
    if same_director:
        score += 25.0
    if overlap == len(original_tags) and original_tags:
        score += 5.0
    return score


def _tag_based_search(
    catalog: list[dict[str, Any]],
    profile: MoviesProfile,
) -> tuple[list[dict[str, Any]], RecommendationMeta]:
    meta = RecommendationMeta()
    original_tags = set(profile.tags_include)
    active_tags = set(profile.tags_include)
    exclude = set(profile.tags_exclude)
    duration = profile.duration_preference

    base_pool = _apply_hard_filters(catalog, exclude, duration, duration_strict=True)
    duration_relaxed = False

    while True:
        matched = [movie for movie in base_pool if _has_all_tags(movie, active_tags)]
        if matched:
            meta.tags_used = sorted(active_tags)
            meta.dropped_tags = sorted(original_tags - active_tags)
            meta.relaxed = bool(meta.dropped_tags)
            meta.volume_relaxed = duration_relaxed
            matched.sort(
                key=lambda movie: _score_movie(
                    movie,
                    original_tags,
                    exclude,
                    duration,
                    same_director=is_same_director_movie(movie, profile),
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

        if duration != "any" and not duration_relaxed:
            duration_relaxed = True
            base_pool = _apply_hard_filters(catalog, exclude, "any", duration_strict=True)
            active_tags = set()
            continue

        break

    scored_pool = _apply_hard_filters(catalog, exclude, "any", duration_strict=False)
    scored_pool.sort(
        key=lambda movie: _score_movie(
            movie,
            original_tags,
            exclude,
            duration,
            same_director=is_same_director_movie(movie, profile),
        ),
        reverse=True,
    )
    meta.relaxed = True
    meta.volume_relaxed = duration != "any"
    meta.tags_used = []
    meta.dropped_tags = sorted(original_tags)
    return scored_pool, meta


def same_director_movies(
    catalog: list[dict[str, Any]],
    profile: MoviesProfile,
    *,
    skip_ids: set[int],
) -> list[dict[str, Any]]:
    director = _resolve_favorite_director(profile, catalog)
    if not director:
        return []

    exclude = set(profile.tags_exclude)
    favorite_id = profile.favorite_movie_id
    original_tags = set(profile.tags_include)
    duration = profile.duration_preference

    candidates: list[dict[str, Any]] = []
    for movie in catalog:
        movie_id = int(movie["id"])
        if movie_id in skip_ids:
            continue
        if favorite_id is not None and movie_id == int(favorite_id):
            continue
        if _normalize_director(str(movie.get("director") or "")) != director:
            continue
        if _has_excluded_tags(movie, exclude):
            continue
        candidates.append(movie)

    candidates.sort(
        key=lambda movie: _score_movie(
            movie,
            original_tags,
            exclude,
            duration,
            same_director=True,
        ),
        reverse=True,
    )
    return candidates


def _next_unshown_items(
    items: list[dict[str, Any]],
    shown: set[int],
    limit: int,
) -> list[dict[str, Any]]:
    page: list[dict[str, Any]] = []
    for item in items:
        item_id = int(item["id"])
        if item_id in shown:
            continue
        page.append(item)
        if len(page) >= limit:
            break
    return page


def _fallback_unshown_from_catalog(
    catalog: list[dict[str, Any]],
    profile: MoviesProfile,
    shown: set[int],
    limit: int,
) -> list[dict[str, Any]]:
    exclude = set(profile.tags_exclude)
    original_tags = set(profile.tags_include)
    duration = profile.duration_preference
    candidates: list[dict[str, Any]] = []
    for movie in catalog:
        movie_id = int(movie["id"])
        if movie_id in shown:
            continue
        if _has_excluded_tags(movie, exclude):
            continue
        candidates.append(movie)
    candidates.sort(
        key=lambda movie: _score_movie(
            movie,
            original_tags,
            exclude,
            duration,
            same_director=is_same_director_movie(movie, profile),
        ),
        reverse=True,
    )
    return candidates[:limit]


def recommend_movies(
    catalog: list[dict[str, Any]],
    profile: MoviesProfile,
    *,
    limit: int = RECOMMENDATION_BATCH_SIZE,
    already_shown: set[int] | None = None,
) -> tuple[list[dict[str, Any]], RecommendationMeta]:
    shown = set(already_shown or [])
    tag_results, meta = _tag_based_search(catalog, profile)

    director = _resolve_favorite_director(profile, catalog)
    if director:
        favorite = movie_by_id(catalog, profile.favorite_movie_id)
        if favorite:
            meta.same_author_name = str(favorite.get("director") or director)

    merged: list[dict[str, Any]] = []
    seen_ids: set[int] = set()

    for movie in tag_results:
        movie_id = int(movie["id"])
        if movie_id in seen_ids:
            continue
        merged.append(movie)
        seen_ids.add(movie_id)

    same_director = same_director_movies(catalog, profile, skip_ids=seen_ids | shown)
    injected = 0
    for movie in same_director:
        if injected >= MAX_SAME_AUTHOR_IN_BATCH:
            break
        movie_id = int(movie["id"])
        if movie_id in seen_ids:
            continue
        merged.append(movie)
        seen_ids.add(movie_id)
        injected += 1

    if injected > 0:
        meta.includes_same_author = True

    merged.sort(
        key=lambda movie: (
            0 if is_same_director_movie(movie, profile) else 1,
            -_score_movie(
                movie,
                set(profile.tags_include),
                set(profile.tags_exclude),
                profile.duration_preference,
                same_director=is_same_director_movie(movie, profile),
            ),
        ),
    )

    page = _next_unshown_items(merged, shown, limit)
    if not page:
        page = _fallback_unshown_from_catalog(catalog, profile, shown, limit)
        if page:
            meta.relaxed = True

    return page, meta


def recommendation_intro_movies(meta: RecommendationMeta) -> str:
    parts: list[str] = []
    if meta.relaxed and meta.dropped_tags:
        parts.append(
            "Точного совпадения по всем жанрам не нашлось — подобрал максимально близкое."
        )
    elif not meta.relaxed:
        parts.append("Вот что попало под твои жанры и настройки.")

    if meta.volume_relaxed:
        parts.append("По длительности чуть шире, чем ты просил — но в тему.")

    if meta.includes_same_author and meta.same_author_name:
        parts.append(
            f"Добавил ещё фильмы режиссёра {meta.same_author_name} — раз его работа тебе зашла."
        )

    return " ".join(parts) if parts else "Лови подборку:"
