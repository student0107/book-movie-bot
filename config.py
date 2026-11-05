TAGS = {
    "school_life": "Школьная жизнь",
    "wilderness": "Выживание в дикой природе",
    "court_intrigue": "Интриги при дворе",
    "time_travel": "Путешествия во времени",
    "magic_rituals": "Магия и ритуалы",
    "first_love": "Первая любовь и взросление",
    "investigation": "Расследование и улики",
    "family_secrets": "Семейные тайны и старые письма",
    "rebellion": "Бунт против правил",
    "friendship_team": "Дружба и команда",
    "psych_tension": "Психологическое напряжение",
    "dystopia": "Антиутопия и контроль системы",
}

MOVIE_TAGS = {
    "drama_melodrama": "Драма / мелодрама",
    "scifi_fantasy": "Фантастика / фэнтези",
    "thriller_horror": "Триллер / ужасы / хоррор",
    "detective": "Детектив",
    "historical": "Исторический фильм",
    "comedy": "Комедия",
}

VOLUME_OPTIONS = {
    "short": "До 300 страниц",
    "medium": "От 300 до 600 страниц",
    "long": "600+ страниц",
    "any": "Без разницы",
}

DURATION_OPTIONS = {
    "short": "До 90 минут",
    "medium": "90–150 минут",
    "long": "150+ минут",
    "any": "Без разницы",
}

MEDIA_BOOK = "book"
MEDIA_MOVIE = "movie"

STATUS_LABELS = {
    "planned": "В планах",
    "reading": "Читаю / смотрю",
    "finished": "Прочитал(а) / досмотрел(а)",
    "dnf": "Забросил(а)",
    "not_interested": "Не интересно",
}

FAVORITE_MATCH_THRESHOLD = 82
RECOMMENDATION_BATCH_SIZE = 5
MAX_SAME_AUTHOR_IN_BATCH = 2
RATING_REMINDER_DAYS_BOOK = 10
RATING_REMINDER_DAYS_MOVIE = 1
MIN_RATINGS_FOR_PUBLIC_SCORE = 3


def rating_reminder_days(media_type: str) -> int:
    """Через сколько дней напомнить после «В планы» (книги / фильмы)."""
    if media_type == MEDIA_MOVIE:
        return RATING_REMINDER_DAYS_MOVIE
    return RATING_REMINDER_DAYS_BOOK
