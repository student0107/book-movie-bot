# -*- coding: utf-8 -*-
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

from books_part1 import ROWS as BOOKS_1  # noqa: E402
from books_part2 import ROWS as BOOKS_2  # noqa: E402
from movies_extra import ROWS as MOVIES_EXTRA  # noqa: E402


def book_row(i, row):
    title, author, pages, tags, series, part, aliases = row
    return {
        "id": i,
        "title": title,
        "author": author,
        "aliases": list(aliases or []),
        "pages": int(pages),
        "tags": list(tags),
        "series": series or None,
        "series_part": int(part) if part else None,
        "cover_url": "",
    }


def movie_row(i, row):
    title, director, year, minutes, tags, kind, franchise, part, aliases = row
    return {
        "id": i,
        "kind": kind or "film",
        "title": title,
        "year": int(year),
        "minutes": int(minutes),
        "director": director,
        "aliases": list(aliases or []),
        "tags": list(tags),
        "poster_url": "",
        "franchise": franchise or None,
        "franchise_part": int(part) if part else None,
    }


def main():
    all_books = BOOKS_1 + BOOKS_2
    if len(all_books) < 100:
        raise SystemExit(f"Нужно >=100 книг, сейчас {len(all_books)}")
    if len(all_books) < 100:
        raise SystemExit(f"Нужно >=100 книг в seed, сейчас {len(all_books)}")
    books = [book_row(i + 1, row) for i, row in enumerate(all_books[:100])]

    books_path = ROOT / "data" / "books.json"
    books_path.write_text(json.dumps(books, ensure_ascii=False, indent=2), encoding="utf-8")

    movies_path = ROOT / "data" / "movies.json"
    existing = json.loads(movies_path.read_text(encoding="utf-8"))
    by_title = {m["title"]: m for m in existing}
    start_id = max(int(m["id"]) for m in existing) + 1 if existing else 1
    for row in MOVIES_EXTRA:
        title = row[0]
        if title in by_title:
            continue
        by_title[title] = movie_row(start_id, row)
        start_id += 1
    merged = sorted(by_title.values(), key=lambda x: int(x["id"]))
    for i, m in enumerate(merged, 1):
        m["id"] = i
    if len(merged) < 100:
        raise SystemExit(f"Нужно >=100 фильмов, сейчас {len(merged)}")
    movies_path.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"books={len(books)} movies={len(merged)}")


if __name__ == "__main__":
    main()
