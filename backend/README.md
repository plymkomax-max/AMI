# AMI Backend

FastAPI + SQLAlchemy (async) + Alembic. Подробная инструкция — в корневом `README.md`.

## Быстрый старт

```bat
cd /d C:\Users\SystemX\AMI\backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Или `run_windows.bat` (сам поднимает миграции и сервер).

## Тесты

```bat
..\.venv\Scripts\python.exe -m pytest tests\ -v
```

## Структура

| Каталог | Ответственность |
|---|---|
| `app/domain/` | чистая математика рынка (numpy, без БД) |
| `app/models/` | ORM-модели |
| `app/schemas/` | Pydantic-схемы API |
| `app/services/` | бизнес-логика: импорт, статистика, объявления |
| `app/routers/` | HTTP-слой |
| `alembic/` | миграции |

## Правила

- Сервисы не делают `commit` — одна транзакция на HTTP-запрос.
- Числа считает только `domain/`, LLM к расчётам не допускается.
- Новые поля моделей — только через миграции (`alembic revision --autogenerate`).
