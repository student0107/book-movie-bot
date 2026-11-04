from handlers.books import router as books_router
from handlers.history import router as history_router
from handlers.movies import router as movies_router
from handlers.reactions import router as reactions_router
from handlers.recommend_cmd import router as recommend_router
from handlers.start import router as start_router

__all__ = [
    "start_router",
    "books_router",
    "movies_router",
    "history_router",
    "reactions_router",
    "recommend_router",
]
