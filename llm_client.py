from __future__ import annotations

import json
import logging
import os
import re
from typing import Any

from openai import AsyncOpenAI

logger = logging.getLogger(__name__)

DEFAULT_MODEL = "openai/gpt-4o-mini"
OPENROUTER_BASE = "https://openrouter.ai/api/v1"


def llm_enabled() -> bool:
    return bool((os.getenv("OPENROUTER_API_KEY") or os.getenv("LLM_API_KEY") or "").strip())


def _api_key() -> str:
    return (os.getenv("OPENROUTER_API_KEY") or os.getenv("LLM_API_KEY") or "").strip()


def _model() -> str:
    return (os.getenv("OPENROUTER_MODEL") or os.getenv("LLM_MODEL") or DEFAULT_MODEL).strip()


def _client() -> AsyncOpenAI:
    return AsyncOpenAI(api_key=_api_key(), base_url=OPENROUTER_BASE)


def _extract_json_object(text: str) -> dict[str, Any] | None:
    text = text.strip()
    if not text:
        return None
    try:
        parsed = json.loads(text)
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        pass
    match = re.search(r"\{[\s\S]*\}", text)
    if not match:
        return None
    try:
        parsed = json.loads(match.group(0))
        if isinstance(parsed, dict):
            return parsed
    except json.JSONDecodeError:
        return None
    return None


async def _chat(system: str, user: str, *, max_tokens: int = 800) -> str | None:
    if not llm_enabled():
        return None
    try:
        response = await _client().chat.completions.create(
            model=_model(),
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.4,
            max_tokens=max_tokens,
        )
        content = response.choices[0].message.content
        return (content or "").strip() if content else None
    except Exception:
        logger.exception("LLM request failed")
        return None


async def summarize_taste(
    *,
    media_label: str,
    favorite_raw: str,
    expectations_raw: str,
    tags_want: list[str],
    tags_avoid: list[str],
    size_label: str,
) -> str:
    """Краткое резюме вкуса для последующих подборов."""
    system = (
        "Ты помощник бота рекомендаций книг и фильмов. "
        "Сожми ответы пользователя в 2–4 коротких предложения на русском. "
        "Не выдумывай названия произведений, которых пользователь не называл. "
        "Не добавляй советы «что посмотреть» — только описание предпочтений."
    )
    user = (
        f"Тип: {media_label}\n"
        f"Темы/жанры (хочу): {', '.join(tags_want) or 'не указано'}\n"
        f"Исключить: {', '.join(tags_avoid) or 'ничего'}\n"
        f"Объём/длительность: {size_label}\n"
        f"Что зацепило (своими словами): {favorite_raw or 'не указано'}\n"
        f"Чего ждёт от следующего: {expectations_raw or 'не указано'}"
    )
    text = await _chat(system, user, max_tokens=350)
    if text:
        return text
    parts = []
    if favorite_raw:
        parts.append(f"Нравится: {favorite_raw}.")
    if expectations_raw:
        parts.append(f"Ожидает: {expectations_raw}.")
    return " ".join(parts) if parts else ""


async def rank_catalog_items(
    *,
    media_label: str,
    taste_summary: str,
    favorite_raw: str,
    expectations_raw: str,
    tags_want: list[str],
    tags_avoid: list[str],
    size_label: str,
    candidates: list[dict[str, Any]],
    limit: int,
) -> list[tuple[int, str]]:
    """
    Выбирает id только из candidates, возвращает (id, why) в порядке приоритета.
    """
    if not llm_enabled() or not candidates:
        return []

    allowed_ids = {int(item["id"]) for item in candidates}
    compact = []
    for item in candidates:
        compact.append(
            {
                "id": int(item["id"]),
                "title": str(item.get("title") or ""),
                "creator": str(item.get("author") or item.get("director") or ""),
                "tags": list(item.get("tags") or []),
            }
        )

    system = (
        "Ты помощник подбора книг/фильмов из фиксированного каталога. "
        "Ответь ТОЛЬКО валидным JSON без markdown:\n"
        '{"picks":[{"id": число, "why": "1-2 предложения на русском"}]}\n'
        f"В picks не больше {limit} элементов. "
        "Используй только id из списка candidates. "
        "Не придумывай новые id и названия вне каталога. "
        "why должно опираться на ожидания пользователя и его вкус."
    )
    user_payload = {
        "media": media_label,
        "taste_summary": taste_summary,
        "favorite_raw": favorite_raw,
        "expectations_raw": expectations_raw,
        "tags_want": tags_want,
        "tags_avoid": tags_avoid,
        "size_preference": size_label,
        "candidates": compact,
    }
    raw = await _chat(system, json.dumps(user_payload, ensure_ascii=False), max_tokens=1200)
    if not raw:
        return []

    data = _extract_json_object(raw)
    if not data:
        return []

    picks_raw = data.get("picks")
    if not isinstance(picks_raw, list):
        return []

    result: list[tuple[int, str]] = []
    seen: set[int] = set()
    for entry in picks_raw:
        if not isinstance(entry, dict):
            continue
        try:
            item_id = int(entry.get("id"))
        except (TypeError, ValueError):
            continue
        if item_id not in allowed_ids or item_id in seen:
            continue
        why = str(entry.get("why") or "").strip()
        if len(why) > 400:
            why = why[:397] + "..."
        seen.add(item_id)
        result.append((item_id, why))
        if len(result) >= limit:
            break
    return result


async def personalize_why_lines(
    *,
    media_label: str,
    taste_summary: str,
    expectations_raw: str,
    items: list[tuple[dict[str, Any], str]],
) -> dict[int, str]:
    """Уточняет текст «почему советую» для уже выбранных позиций (команда /recommend)."""
    if not llm_enabled() or not items:
        return {}

    compact = []
    for item, base_why in items:
        compact.append(
            {
                "id": int(item["id"]),
                "title": str(item.get("title") or ""),
                "base_why": base_why,
            }
        )

    system = (
        "Ты помощник бота рекомендаций. Ответь ТОЛЬКО JSON:\n"
        '{"lines":[{"id": число, "why": "1-2 предложения на русском"}]}\n'
        "Сохрани смысл base_why, но добавь отсылку к вкусу пользователя если уместно. "
        "Только id из списка."
    )
    user_payload = {
        "media": media_label,
        "taste_summary": taste_summary,
        "expectations_raw": expectations_raw,
        "items": compact,
    }
    raw = await _chat(system, json.dumps(user_payload, ensure_ascii=False), max_tokens=900)
    if not raw:
        return {}

    data = _extract_json_object(raw)
    if not data or not isinstance(data.get("lines"), list):
        return {}

    out: dict[int, str] = {}
    allowed = {int(item["id"]) for item, _ in items}
    for entry in data["lines"]:
        if not isinstance(entry, dict):
            continue
        try:
            item_id = int(entry.get("id"))
        except (TypeError, ValueError):
            continue
        if item_id not in allowed:
            continue
        why = str(entry.get("why") or "").strip()
        if why:
            out[item_id] = why
    return out
