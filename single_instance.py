"""Не даёт запустить два экземпляра бота с одним токеном (Conflict в Telegram)."""
from __future__ import annotations

import sys
from pathlib import Path

_LOCK_FILE: object | None = None


def ensure_single_instance() -> None:
    global _LOCK_FILE
    lock_path = Path(__file__).resolve().parent / ".bot.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)

    handle = open(lock_path, "a+b")

    if sys.platform == "win32":
        import msvcrt

        try:
            handle.seek(0)
            msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
        except OSError:
            handle.close()
            print(
                "Бот уже запущен в другом окне.\n"
                "Закрой лишний терминал с main.py или заверши процесс python в диспетчере задач."
            )
            raise SystemExit(1)
    else:
        import fcntl

        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            handle.close()
            print("Бот уже запущен. Останови другой экземпляр main.py.")
            raise SystemExit(1)

    handle.seek(0)
    handle.truncate()
    handle.write(str(Path(__file__).resolve().parent).encode("utf-8"))
    handle.flush()
    _LOCK_FILE = handle
