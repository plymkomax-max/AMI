# AMI — Avito Market Intelligence

Локальная система анализа рынка объявлений: собирает данные, считает рыночные цены,
находит недооценённые предложения и объясняет, сколько потенциально можно заработать.

Работает на обычном ноутбуке: CPU-only, без CUDA, без облака и без внешних LLM по умолчанию.

## Что уже работает

- **Data Engine**: объявления, источники, импорт CSV (UTF-8/cp1251, `,`/`;`, даты),
  дедупликация, история цен и изменений.
- **Связь с моделью товара**: `product_id` у объявления, статистика по модели и категории.
- **Market Intelligence**: медиана, квантили, IQR, аномалии **внутри одной модели**,
  сравнение моделей, динамика цены.
- **API**: 18 эндпоинтов + Swagger, опциональный `X-API-Key`.
- **Alembic**: настоящая схема из 11 таблиц + справочник категорий и источников.

Ещё не сделано: LLM/Ollama, ML/CatBoost, Dashboard (React), Telegram, реальные адаптеры
источников (Avito API), Opportunity Engine.

## Требования

- Windows 10/11 x64
- Python **3.12** (проверено на 3.12.8)
- 8 ГБ RAM и больше (проверено на 16 ГБ)
- Свободное место: ~1 ГБ под окружение и данные

## Установка (Windows)

```bat
cd /d C:\Users\SystemX\AMI

REM 1. Виртуальное окружение
"C:\Users\SystemX\AppData\Local\Programs\Python\Python312\python.exe" -m venv .venv

REM 2. Зависимости
.venv\Scripts\python.exe -m pip install --upgrade pip
.venv\Scripts\python.exe -m pip install -r backend\requirements.txt

REM 3. Конфигурация (файл .env уже есть; шаблон — .env.example)
copy .env.example .env
```

> Важно: `python` в PATH на этой машине указывает на чужое окружение
> (`AI_KEYS\gigachat-proxy\venv`). Всегда используйте `.venv\Scripts\python.exe`.

## Запуск

Двойной клик по `backend\run_windows.bat` или вручную:

```bat
cd /d C:\Users\SystemX\AMI\backend
..\.venv\Scripts\python.exe -m alembic upgrade head
..\.venv\Scripts\python.exe -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

- API: http://127.0.0.1:8000
- Swagger: http://127.0.0.1:8000/docs
- Health: http://127.0.0.1:8000/api/v1/health

Проверка:

```bat
curl http://127.0.0.1:8000/api/v1/health
```

## Тесты

```bat
cd /d C:\Users\SystemX\AMI\backend
..\.venv\Scripts\python.exe -m pytest tests\ -v
```

Тесты используют временную БД в `backend\tests\.ami_tests_*` и **не трогают** `ami.db`.

## База данных

По умолчанию SQLite (`backend\ami.db`), путь не зависит от текущего каталога.
Внешние ключи и WAL включены.

PostgreSQL (опционально):

```bat
.venv\Scripts\python.exe -m pip install -r backend\requirements-postgres.txt
```

```ini
# .env
AMI_DATABASE_URL=postgresql+asyncpg://ami:password@127.0.0.1:5432/ami
```

Затем:

```bat
cd backend
..\.venv\Scripts\python.exe -m alembic upgrade head
```

## API-ключ

По умолчанию API открыт (локальный режим). Чтобы закрыть:

```ini
# .env
AMI_API_KEY=длинный-случайный-ключ
```

После этого все рабочие эндпоинты требуют заголовок `X-API-Key`.
`/api/v1/health` и `/api/v1/info` остаются публичными.

## Структура

```
AMI/
├── backend/
│   ├── app/
│   │   ├── config.py        # настройки из .env
│   │   ├── database.py      # async SQLite/PostgreSQL, PRAGMA
│   │   ├── logger.py        # единый логгер
│   │   ├── security.py      # API-ключ
│   │   ├── domain/          # математика рынка (без БД и LLM)
│   │   ├── models/          # ORM
│   │   ├── routers/         # API
│   │   ├── schemas/         # Pydantic
│   │   └── services/        # бизнес-логика
│   ├── alembic/             # миграции
│   ├── tests/               # pytest
│   └── run_windows.bat
├── docs/                    # аудит и журнал изменений
├── frontend/                # (этап 7)
├── .env.example
└── README.md
```

## Этапы

| Этап | Статус |
|---|---|
| 1. Аудит и фундамент | готово |
| 2. Data Engine | готово (кроме Excel и адаптеров источников) |
| 3. Market Intelligence | базово готово (оценка стоимости — следующий шаг) |
| 4. Локальный AI | не начато |
| 5. Opportunity Engine | не начато |
| 6. ML | не начато |
| 7. Dashboard | не начато |
| 8. Telegram | не начато |

## Документация

- [`docs/AMI_AUDIT_2026-11-18.md`](docs/AMI_AUDIT_2026-11-18.md) — технический аудит
- [`docs/STAGE0_FIXES.md`](docs/STAGE0_FIXES.md) — что исправлено и как проверено

## Решение проблем

**`ModuleNotFoundError: No module named 'sqlalchemy'`** — запущен не тот Python.
Используйте `.venv\Scripts\python.exe` или `backend\run_windows.bat`.

**Кракозябры в консоли** — выполните `chcp 65001` или запускайте через `.bat`.

**Порт 8000 занят** — закройте старый процесс или укажите другой порт:
`--port 8001`.

**`alembic upgrade head` падает** — проверьте `AMI_DATABASE_URL` в `.env`;
для PostgreSQL нужен `asyncpg`.
