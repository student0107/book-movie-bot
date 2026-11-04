import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import aiosqlite

from config import MEDIA_BOOK, MEDIA_MOVIE, RATING_REMINDER_DAYS

DB_PATH = Path(__file__).resolve().parent / "bot_data.db"


async def init_db() -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS books_profile (
                user_id INTEGER PRIMARY KEY,
                tags_include TEXT NOT NULL,
                tags_exclude TEXT NOT NULL,
                volume_preference TEXT NOT NULL,
                favorite_book_raw TEXT NOT NULL,
                favorite_book_id INTEGER,
                favorite_author TEXT,
                stage1_completed_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS movies_profile (
                user_id INTEGER PRIMARY KEY,
                tags_include TEXT NOT NULL,
                tags_exclude TEXT NOT NULL,
                duration_preference TEXT NOT NULL,
                favorite_movie_raw TEXT NOT NULL,
                favorite_movie_id INTEGER,
                favorite_director TEXT,
                stage1_completed_at TEXT NOT NULL
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS recommendation_session (
                user_id INTEGER NOT NULL,
                media_type TEXT NOT NULL,
                shown_ids TEXT NOT NULL DEFAULT '[]',
                PRIMARY KEY (user_id, media_type)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS user_library (
                user_id INTEGER NOT NULL,
                media_type TEXT NOT NULL,
                item_id INTEGER NOT NULL,
                status TEXT NOT NULL,
                planned_at TEXT,
                updated_at TEXT NOT NULL,
                rating INTEGER,
                rated_at TEXT,
                PRIMARY KEY (user_id, media_type, item_id)
            )
            """
        )
        await db.execute(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                media_type TEXT NOT NULL,
                item_id INTEGER NOT NULL,
                run_at TEXT NOT NULL,
                kind TEXT NOT NULL,
                sent INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        await db.commit()
        await _migrate_profile_columns(db)


async def _migrate_profile_columns(db: aiosqlite.Connection) -> None:
    for table in ("books_profile", "movies_profile"):
        cursor = await db.execute(f"PRAGMA table_info({table})")
        columns = {row[1] for row in await cursor.fetchall()}
        if "expectations_raw" not in columns:
            await db.execute(
                f"ALTER TABLE {table} ADD COLUMN expectations_raw TEXT NOT NULL DEFAULT ''"
            )
        if "taste_summary" not in columns:
            await db.execute(
                f"ALTER TABLE {table} ADD COLUMN taste_summary TEXT NOT NULL DEFAULT ''"
            )
    await db.commit()


def _loads_tags(raw: str) -> set[str]:
    return set(json.loads(raw))


async def save_books_profile(
    user_id: int,
    *,
    tags_include: set[str],
    tags_exclude: set[str],
    volume_preference: str,
    favorite_book_raw: str,
    favorite_book_id: int | None,
    favorite_author: str | None,
    expectations_raw: str,
    taste_summary: str,
    completed_at: str,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO books_profile (
                user_id, tags_include, tags_exclude, volume_preference,
                favorite_book_raw, favorite_book_id, favorite_author,
                expectations_raw, taste_summary, stage1_completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                tags_include = excluded.tags_include,
                tags_exclude = excluded.tags_exclude,
                volume_preference = excluded.volume_preference,
                favorite_book_raw = excluded.favorite_book_raw,
                favorite_book_id = excluded.favorite_book_id,
                favorite_author = excluded.favorite_author,
                expectations_raw = excluded.expectations_raw,
                taste_summary = excluded.taste_summary,
                stage1_completed_at = excluded.stage1_completed_at
            """,
            (
                user_id,
                json.dumps(sorted(tags_include), ensure_ascii=False),
                json.dumps(sorted(tags_exclude), ensure_ascii=False),
                volume_preference,
                favorite_book_raw,
                favorite_book_id,
                favorite_author,
                expectations_raw,
                taste_summary,
                completed_at,
            ),
        )
        await db.execute(
            "DELETE FROM recommendation_session WHERE user_id = ? AND media_type = ?",
            (user_id, MEDIA_BOOK),
        )
        await db.commit()


async def save_movies_profile(
    user_id: int,
    *,
    tags_include: set[str],
    tags_exclude: set[str],
    duration_preference: str,
    favorite_movie_raw: str,
    favorite_movie_id: int | None,
    favorite_director: str | None,
    expectations_raw: str,
    taste_summary: str,
    completed_at: str,
) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO movies_profile (
                user_id, tags_include, tags_exclude, duration_preference,
                favorite_movie_raw, favorite_movie_id, favorite_director,
                expectations_raw, taste_summary, stage1_completed_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(user_id) DO UPDATE SET
                tags_include = excluded.tags_include,
                tags_exclude = excluded.tags_exclude,
                duration_preference = excluded.duration_preference,
                favorite_movie_raw = excluded.favorite_movie_raw,
                favorite_movie_id = excluded.favorite_movie_id,
                favorite_director = excluded.favorite_director,
                expectations_raw = excluded.expectations_raw,
                taste_summary = excluded.taste_summary,
                stage1_completed_at = excluded.stage1_completed_at
            """,
            (
                user_id,
                json.dumps(sorted(tags_include), ensure_ascii=False),
                json.dumps(sorted(tags_exclude), ensure_ascii=False),
                duration_preference,
                favorite_movie_raw,
                favorite_movie_id,
                favorite_director,
                expectations_raw,
                taste_summary,
                completed_at,
            ),
        )
        await db.execute(
            "DELETE FROM recommendation_session WHERE user_id = ? AND media_type = ?",
            (user_id, MEDIA_MOVIE),
        )
        await db.commit()


async def load_books_profile(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM books_profile WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        data = dict(row)
        data["tags_include"] = _loads_tags(data["tags_include"])
        data["tags_exclude"] = _loads_tags(data["tags_exclude"])
        return data


async def load_movies_profile(user_id: int) -> dict | None:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute("SELECT * FROM movies_profile WHERE user_id = ?", (user_id,))
        row = await cursor.fetchone()
        if row is None:
            return None
        data = dict(row)
        data["tags_include"] = _loads_tags(data["tags_include"])
        data["tags_exclude"] = _loads_tags(data["tags_exclude"])
        return data


async def get_shown_ids(user_id: int, media_type: str) -> set[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            "SELECT shown_ids FROM recommendation_session WHERE user_id = ? AND media_type = ?",
            (user_id, media_type),
        )
        row = await cursor.fetchone()
        if row is None:
            return set()
        return set(json.loads(row[0]))


async def add_shown_ids(user_id: int, media_type: str, item_ids: list[int]) -> None:
    current = await get_shown_ids(user_id, media_type)
    current.update(item_ids)
    payload = json.dumps(sorted(current))
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO recommendation_session (user_id, media_type, shown_ids)
            VALUES (?, ?, ?)
            ON CONFLICT(user_id, media_type) DO UPDATE SET shown_ids = excluded.shown_ids
            """,
            (user_id, media_type, payload),
        )
        await db.commit()


async def set_library_entry(
    user_id: int,
    media_type: str,
    item_id: int,
    status: str,
    *,
    schedule_rating: bool = False,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    planned_at = now if status == "planned" else None
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT status, planned_at FROM user_library
            WHERE user_id = ? AND media_type = ? AND item_id = ?
            """,
            (user_id, media_type, item_id),
        )
        existing = await cursor.fetchone()
        if existing and existing[1]:
            planned_at = existing[1]
        if status == "planned" and not planned_at:
            planned_at = now

        await db.execute(
            """
            INSERT INTO user_library (
                user_id, media_type, item_id, status, planned_at, updated_at, rating, rated_at
            ) VALUES (?, ?, ?, ?, ?, ?, NULL, NULL)
            ON CONFLICT(user_id, media_type, item_id) DO UPDATE SET
                status = excluded.status,
                planned_at = COALESCE(user_library.planned_at, excluded.planned_at),
                updated_at = excluded.updated_at
            """,
            (user_id, media_type, item_id, status, planned_at, now),
        )
        if schedule_rating and status == "planned":
            run_at = (
                datetime.now(timezone.utc) + timedelta(days=RATING_REMINDER_DAYS)
            ).isoformat()
            await db.execute(
                """
                INSERT INTO reminders (user_id, media_type, item_id, run_at, kind, sent)
                VALUES (?, ?, ?, ?, 'rating_check', 0)
                """,
                (user_id, media_type, item_id, run_at),
            )
        await db.commit()


async def set_rating(
    user_id: int,
    media_type: str,
    item_id: int,
    rating: int,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            UPDATE user_library
            SET rating = ?, rated_at = ?, status = 'finished', updated_at = ?
            WHERE user_id = ? AND media_type = ? AND item_id = ?
            """,
            (rating, now, now, user_id, media_type, item_id),
        )
        await db.commit()


async def list_library(user_id: int, media_type: str | None = None) -> list[dict]:
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        if media_type:
            cursor = await db.execute(
                """
                SELECT * FROM user_library
                WHERE user_id = ? AND media_type = ?
                ORDER BY updated_at DESC
                """,
                (user_id, media_type),
            )
        else:
            cursor = await db.execute(
                """
                SELECT * FROM user_library WHERE user_id = ?
                ORDER BY media_type, updated_at DESC
                """,
                (user_id,),
            )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def get_library_map(user_id: int, media_type: str) -> dict[int, dict]:
    items = await list_library(user_id, media_type)
    return {int(item["item_id"]): item for item in items}


async def get_high_rated_item_ids(user_id: int, media_type: str) -> list[tuple[int, int]]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT item_id, rating FROM user_library
            WHERE user_id = ? AND media_type = ? AND rating >= 4
            ORDER BY rating DESC, rated_at DESC
            """,
            (user_id, media_type),
        )
        rows = await cursor.fetchall()
        return [(int(row[0]), int(row[1])) for row in rows]


async def get_dnf_items(user_id: int, media_type: str) -> list[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT item_id FROM user_library
            WHERE user_id = ? AND media_type = ? AND status = 'dnf'
            """,
            (user_id, media_type),
        )
        rows = await cursor.fetchall()
        return [int(row[0]) for row in rows]


async def get_blocked_item_ids(user_id: int, media_type: str) -> set[int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT item_id FROM user_library
            WHERE user_id = ? AND media_type = ? AND status IN (
                'not_interested', 'finished', 'planned', 'reading'
            )
            """,
            (user_id, media_type),
        )
        rows = await cursor.fetchall()
        return {int(row[0]) for row in rows}


async def get_item_rating_stats(media_type: str, item_id: int) -> tuple[float | None, int]:
    async with aiosqlite.connect(DB_PATH) as db:
        cursor = await db.execute(
            """
            SELECT AVG(rating), COUNT(rating) FROM user_library
            WHERE media_type = ? AND item_id = ? AND rating IS NOT NULL
            """,
            (media_type, item_id),
        )
        row = await cursor.fetchone()
        if row is None or row[1] == 0:
            return None, 0
        return float(row[0]), int(row[1])


async def fetch_due_reminders(limit: int = 50) -> list[dict]:
    now = datetime.now(timezone.utc).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        db.row_factory = aiosqlite.Row
        cursor = await db.execute(
            """
            SELECT * FROM reminders
            WHERE sent = 0 AND run_at <= ?
            ORDER BY run_at ASC
            LIMIT ?
            """,
            (now, limit),
        )
        rows = await cursor.fetchall()
        return [dict(row) for row in rows]


async def mark_reminder_sent(reminder_id: int) -> None:
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute("UPDATE reminders SET sent = 1 WHERE id = ?", (reminder_id,))
        await db.commit()


async def reschedule_reminder(
    user_id: int,
    media_type: str,
    item_id: int,
    days: int = RATING_REMINDER_DAYS,
) -> None:
    run_at = (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()
    async with aiosqlite.connect(DB_PATH) as db:
        await db.execute(
            """
            INSERT INTO reminders (user_id, media_type, item_id, run_at, kind, sent)
            VALUES (?, ?, ?, ?, 'rating_check', 0)
            """,
            (user_id, media_type, item_id, run_at),
        )
        await db.commit()
