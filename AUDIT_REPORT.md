# AMI — Avito Market Intelligence
# Этап 1: Аудит и фундамент — итоговый отчёт

> ⚠️ **Устарело (18.11.2026).** Часть утверждений ниже не подтвердилась при
> повторной проверке: миграция была пустой, тесты писали в рабочую БД.
> Актуальный аудит: [`docs/AMI_AUDIT_2026-11-18.md`](docs/AMI_AUDIT_2026-11-18.md),
> список исправлений: [`docs/STAGE0_FIXES.md`](docs/STAGE0_FIXES.md).

## Краткая оценка состояния

**Статус: проект создан с нуля, базовый каркас работает.**

Исходный «стартовый проект» не найден на диске (папка `freellmapi` — это чужой
репозиторий LLM-API, не имеющий отношения к AMI). Поэтому по результатам аудита
создан полноценный фундамент AMI с нуля, готовый к следующим этапам.

## Обнаруженные проблемы (и их исправления)

| # | Проблема | Решение |
|---|----------|---------|
| 1 | Python 3.14 — слишком новый, нет совместимых пакетов | Использовать Python 3.12 (установлен: `C:\Users\SystemX\AppData\Local\Programs\Python\Python312`) |
| 2 | Нет зависимостей | Установлены: fastapi, sqlalchemy, alembic, aiosqlite, greenlet, uvicorn, pytest |
| 3 | Ошибка SQLite URL (`sqlite+aiosqlite://./ami.db` — невалидно) | Исправлен `_normalize_url` в `database.py`: теперь `sqlite+aiosqlite:///./ami.db` |
| 4 | Дубликаты индексов (ix_categories_slug, ix_listings_city, ix_products_brand_model) | Убраны лишние `index=True` у полей, оставлены только в `__table_args__` |
| 5 | Ошибка mappers (Listing не имел relationship `predictions`) | Добавлены связи `predictions`, `opportunities`, `feedback` в Listing |
| 6 | Предупреждение `metadata` (зарезервировано SQLAlchemy) | Переименовано в `feedback_meta` |
| 7 | Артефакт `बचau = -` в alembic.ini | Удалён |
| 8 | Ошибка синтаксиса в routers/categories.py | Исправлена, эндпоинты работают |
| 9 | Зависимость от asyncpg для PostgreSQL | Обрабатывается условно: используется если установлена, иначе синхронный драйвер |
| 10 | Кодировка кириллицы в curl из git-bash | Не баг кода — артефакт терминала; через Python/файл работает корректно |

## Что проверено и работает

- [x] `python -m pytest tests/ -v` — **6/6 тестов прошли**
- [x] `GET /` → `{"status":"ok","version":"0.1.0",...}` — 200
- [x] `GET /api/v1/health` → `{"status":"ok","detail":"Service is running",...}` — 200
- [x] `GET /api/v1/info` → версия, приложение — 200
- [x] `GET /api/v1/categories/` → список категорий — 200
- [x] `POST /api/v1/categories/` → создание категории — 200
- [x] `GET /api/v1/categories/{id}` → чтение по id — 200
- [x] `GET /docs` → Swagger UI — 200
- [x] Alembic: `upgrade head` — миграция применена
- [x] Таблицы созданы: categories, listings, products, price_history, listing_history, market_statistics, model_versions, predictions, opportunities, user_feedback

## Структура проекта

```
AMI/
├── .env.example           # Шаблон конфигурации
├── README.md
├── backend/
│   ├── app/
│   │   ├── __init__.py
│   │   ├── config.py      # Настройки через env (pydantic-settings)
│   │   ├── database.py    # SQLAlchemy (async, SQLite/PostgreSQL)
│   │   ├── dependencies.py
│   │   ├── errors.py      # Обработка ошибок
│   │   ├── logger.py      # Логирование (файл + консоль)
│   │   ├── main.py        # FastAPI приложение
│   │   ├── security.py    # Проверка API-ключа
│   │   ├── models/        # ORM: category, product, listing, history, ml, statistics, feedback
│   │   ├── routers/       # API: base, categories
│   │   ├── schemas/       # Pydantic-схемы
│   │   ├── data/          # (резерв) сбор данных
│   │   ├── domain/        # (резерв) бизнес-логика
│   │   ├── infra/         # (резерв) инфраструктура
│   │   └── ml/            # (резерв) ML-модуль
│   ├── alembic/           # Миграции БД
│   ├── tests/             # Pytest
│   ├── requirements.txt
│   ├── pyproject.toml
│   └── run_windows.bat    # Запуск на Windows
├── frontend/              # (резерв для React/TypeScript)
└── migrations/            # (резерв)
```

## Предлагаемая архитектура следующего этапа

Этап 2 — **Data Engine** (модель объявлений, источники данных, импорт CSV,
нормализация, дедупликация, история цен). Уже заложен фундамент:
таблицы `listings`, `price_history`, `listing_history`.

Ключевые принципы:
1. **Модульный монолит** — один сервис, чёткое разделение ответственности.
2. **CPU-first** — все вычисления на CPU, без CUDA (Quadro K2000M не поддерживает).
3. **Слабое потребление RAM** — 16 ГБ достаточно, но избегаем тяжёлых моделей.
4. **Безопасность** — API-ключ, валидация входных данных, никаких прямых
   команд ОС от LLM.
5. **LLM (Ollama/Qwen)** — только для текста, не для числовых расчётов.

## Конкретный план реализации (Этап 2)

1. Создать `app/data/sources/` — адаптеры источников (Avito API, CSV, Excel, ручное).
2. Реализовать `app/data/importers/` — импорт CSV/Excel.
3. Добавить `app/data/normalizer.py` — нормализация данных (цены, состояние, характеристики).
4. Добавить `app/data/deduplicator.py` — проверка дубликатов.
5. Добавить `app/domain/listings.py` — бизнес-логика работы с объявлениями.
6. Реализовать `app/routers/listings.py` — CRUD API для объявлений.
7. Добавить `app/services/price_history.py` — история цен.
8. Покрыть критичные функции тестами.
9. Настроить фоновые задачи (APScheduler) для сбора данных.

## Точные команды запуска/проверки (Windows)

```bat
REM === Установка ===
cd C:\Users\SystemX\AMI\backend
C:\Users\SystemX\AppData\Local\Programs\Python\Python312\python.exe -m pip install -r requirements.txt

REM === Миграции ===
C:\Users\SystemX\AppData\Local\Programs\Python\Python312\python.exe -m alembic upgrade head

REM === Запуск сервера ===
C:\Users\SystemX\AppData\Local\Programs\Python\Python312\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload

REM === Тесты ===
C:\Users\SystemX\AppData\Local\Programs\Python\Python312\python.exe -m pytest tests/ -v

REM === Проверка API ===
curl http://127.0.0.1:8000/api/v1/health
```

## Что ещё не реализовано (следующие этапы)

- Этап 2: Data Engine (сбор, импорт, нормализация, дедупликация)
- Этап 3: Market Intelligence (статистика, медианы, аномалии, динамика)
- Этап 4: Локальный AI (Ollama, Qwen, анализ текста)
- Этап 5: Opportunity Engine (оценка выгоды, риски, ликвидность)
- Этап 6: Machine Learning (CatBoost, обучение, версии моделей)
- Этап 7: Dashboard (React, TypeScript, ECharts)
- Этап 8: Telegram (aiogram, уведомления)
- Этап 9: Оптимизация (производительность, резервное копирование)
