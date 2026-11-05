# Book & Movie Pick Bot

Telegram-бот для подбора **книг** и **фильмов** по анкете, истории просмотров/чтения и персональным рекомендациям.

## Возможности

- Приветствие → **Книги** / **Фильмы**
- Анкета из **5 шагов**: теги (кнопки) → что зацепило (текст) → «не хочу» (кнопки) → объём/длительность (кнопки) → чего ждёте (текст)
- **Нейросеть** (OpenRouter, опционально): резюме вкуса и подбор с объяснением по вашим текстам; без ключа работает как раньше, только по тегам
- Подбор с **пересечением тегов**, ослаблением фильтров без «ничего не найдено»
- Книги **того же автора** / фильмы **того же режиссёра** (если любимое найдено в каталоге)
- Карточки с **обложкой/постером** (если указан URL в JSON) и кнопками **👍 В планы** / **👎 Не моё**
- **`/history`** (и **`/histiry`**) — история со статусами
- **`/plans`** и кнопка **«Мои планы»** в меню — всё с 👍 «В планы» (книги и фильмы отдельными списками)
- **`/recommend`** — персональный подбор с текстом «почему советую»
- Напоминание после «В планы»: **книги — 10 дней**, **фильмы — 1 сутки** (в `config.py`), затем оценка **1–5**

## Быстрый старт

1. Создай бота у [@BotFather](https://t.me/BotFather), скопируй токен.
2. В папке проекта:

```powershell
cd C:\Users\user\Projects\book-movie-bot
copy .env.example .env
```

3. Вставь токен в `.env`:

```env
BOT_TOKEN=ваш_токен
OPENROUTER_API_KEY=ваш_ключ
# OPENROUTER_MODEL=openai/gpt-4o-mini
```

4. Установка и запуск:

```powershell
C:\Users\user\AppData\Local\Programs\Python\Python313\python.exe -m venv venv
.\venv\Scripts\pip install -r requirements.txt
.\venv\Scripts\python.exe main.py
```

5. В Telegram открой бота → **Start**.

## Команды бота (для BotFather)

```
start - Начать и выбрать книги или фильмы
recommend - Персональные рекомендации
history - Моя история и статусы
plans - Мои планы (книги и фильмы)
```

## Каталоги

| Файл | Содержимое |
|------|------------|
| `data/books.json` | **100+** книг: `title`, `author`, `pages`, `tags`, `series`, `cover_url` |
| `data/movies.json` | **100+** фильмов/сериалов: `kind` (`film`/`series`), `director`, `minutes`, `tags`, `poster_url`, `franchise` |

Пересобрать каталог из seed-файлов: `python scripts/make_catalog.py` (см. `scripts/books_part1.py`, `books_part2.py`, `movies_extra.py`).

Сериалы помечаются в чате строкой **📺 Сериал**.

## Дальнейшие действия (чеклист)

### 1. Запуск и проверка

- [ ] Пройти анкету **Книги** и **Фильмы**
- [ ] Нажать 👍/👎 под карточками
- [ ] Команды `/history` и `/recommend`
- [ ] Если была старая `bot_data.db` без новых таблиц — удалить файл и перезапустить бота

### 2. Наполнение каталога

- [ ] Добавить книги и фильмы в JSON (теги только из списков в `config.py`)
- [ ] Прописать **`cover_url` / `poster_url`** (HTTPS-ссылки на обложки/постеры)
- [ ] Для циклов: `series` + `series_part` (книги), `franchise` + `franchise_part` (фильмы)
- [ ] Перепроверить спорные прокатные названия в `movies.json` (Kinopoisk)

### 3. Публикация 24/7

- [ ] VPS или Railway/Render — бот должен работать постоянно, иначе напоминания придут с задержкой
- [ ] Переменная окружения `BOT_TOKEN` на сервере
- [ ] (Опционально) webhook вместо polling

### 4. Улучшения продукта

- [x] Отдельный жанр **комедия** для фильмов (`comedy` в `MOVIE_TAGS` и в `movies.json`)
- [ ] Короткий **отзыв текстом** после оценки
- [ ] Админ-команда для загрузки JSON без деплоя
- [ ] Резервная копия `bot_data.db`

### 5. Git и удалённый репозиторий

```powershell
cd C:\Users\user\Projects\book-movie-bot
git init
git add .
git commit -m "Initial release: book and movie recommendation bot"
```

Создай пустой репозиторий на GitHub/GitLab и:

```powershell
git remote add origin https://github.com/ВАШ_ЛОГИН/book-movie-bot.git
git branch -M main
git push -u origin main
```

**Не публикуй** файл `.env` и `bot_data.db` — они в `.gitignore`.

## Структура проекта

```
main.py                 — запуск
config.py               — теги и настройки
catalog.py              — загрузка JSON и поиск названий
llm_client.py           — запросы к OpenRouter
recommendation_ai.py    — подбор с учётом текстов анкеты
recommendation.py       — подбор книг после анкеты
recommendation_movies.py — подбор фильмов после анкеты
personal_recommend.py   — логика /recommend
database.py             — SQLite
media_cards.py          — карточки и кнопки
scheduler.py            — напоминания
handlers/               — сценарии Telegram
data/                   — каталоги
```

## Лицензия

Учебный/личный проект. Обложки и постеры — права правообладателей; используй легальные URL или свои материалы.
