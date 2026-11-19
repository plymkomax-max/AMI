"""Движок и сессии базы данных.

Поддерживается PostgreSQL (asyncpg) и SQLite (aiosqlite).
Относительные пути SQLite считаются от каталога backend/, а не от CWD.
"""
from __future__ import annotations

import re
from typing import AsyncGenerator, Optional

from sqlalchemy import event, text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import DeclarativeBase, sessionmaker

from .config import resolve_path, settings
from .logger import get_logger

log = get_logger(__name__)


class Base(DeclarativeBase):
    """Базовый класс для всех ORM-моделей."""


_SQLITE_RE = re.compile(r"^(sqlite(?:\+aiosqlite)?):///(.*)$")


def _normalize_sqlite(url: str) -> str:
    """Приводит sqlite-URL к ``sqlite+aiosqlite`` и абсолютному пути."""
    if url in ("sqlite://", "sqlite+aiosqlite://", "sqlite:///:memory:"):
        return "sqlite+aiosqlite:///:memory:"

    match = _SQLITE_RE.match(url)
    if not match:
        # sqlite://relative.db (две косые) — встречается в старых конфигах
        if url.startswith("sqlite://"):
            raw = url[len("sqlite://"):]
            return _normalize_sqlite(f"sqlite:///{raw}")
        raise ValueError(f"Неподдерживаемый SQLite URL: {url}")

    path = match.group(2)
    if path in ("", ":memory:"):
        return "sqlite+aiosqlite:///:memory:"

    # Уже абсолютный путь: C:/..., /home/..., \\server\share
    if re.match(r"^[A-Za-z]:[\\/]", path) or path.startswith(("/", "\\\\")):
        return f"sqlite+aiosqlite:///{path.replace(chr(92), '/')}"

    resolved = resolve_path(path)
    return f"sqlite+aiosqlite:///{resolved.as_posix()}"


def _normalize_url(url: str) -> str:
    """Приводит URL к формату, понятному async-движку SQLAlchemy."""
    if url.startswith("sqlite"):
        return _normalize_sqlite(url)

    if url.startswith(("postgres://", "postgresql://", "postgresql+asyncpg://")):
        try:
            import asyncpg  # noqa: F401
        except ImportError as exc:
            raise RuntimeError(
                "Для PostgreSQL нужен драйвер asyncpg. Установите:\n"
                "  python -m pip install -r requirements-postgres.txt"
            ) from exc
        if url.startswith("postgres://"):
            url = url.replace("postgres://", "postgresql://", 1)
        if url.startswith("postgresql://"):
            url = url.replace("postgresql://", "postgresql+asyncpg://", 1)
        return url

    raise ValueError(f"Неподдерживаемый URL базы данных: {url}")


def _build_engine():
    url = _normalize_url(settings.database_url)

    if url.startswith("sqlite+aiosqlite"):
        engine = create_async_engine(
            url,
            echo=settings.db_echo,
            connect_args={"check_same_thread": False, "timeout": 15},
        )

        @event.listens_for(engine.sync_engine, "connect")
        def _set_sqlite_pragma(dbapi_connection, _connection_record) -> None:
            """Включает внешние ключи и WAL — иначе каскады в SQLite не работают."""
            cursor = dbapi_connection.cursor()
            try:
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.execute("PRAGMA journal_mode=WAL")
                cursor.execute("PRAGMA synchronous=NORMAL")
                cursor.execute("PRAGMA busy_timeout=15000")
            finally:
                cursor.close()

        log.debug("SQLite: %s", url)
        return engine

    if url.startswith("postgresql+asyncpg"):
        engine = create_async_engine(
            url,
            echo=settings.db_echo,
            pool_size=5,
            max_overflow=10,
            pool_timeout=30,
            pool_pre_ping=True,
        )
        log.debug("PostgreSQL: %s", url)
        return engine

    raise ValueError(f"Неподдерживаемый драйвер БД: {url}")


engine = _build_engine()
AsyncSessionLocal = sessionmaker(
    bind=engine, class_=AsyncSession, expire_on_commit=False, autoflush=False
)


async def get_db() -> AsyncGenerator[Optional[AsyncSession], None]:
    """Зависимость FastAPI: одна сессия и один commit на запрос."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise


async def check_db() -> bool:
    """Проверка доступности БД для /health."""
    try:
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        return True
    except Exception:  # noqa: BLE001
        log.exception("Проверка БД не удалась")
        return False


async def init_db() -> None:
    """Создаёт таблицы напрямую.

    Только для тестов и одноразовой инициализации.
    В рабочем режиме схемой управляет Alembic (``alembic upgrade head``).
    """
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    log.info("БД инициализирована: %s", settings.database_url)
