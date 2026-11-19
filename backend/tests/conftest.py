"""Pytest-фикстуры AMI.

КРИТИЧНО: переменные окружения выставляются ДО импорта app,
иначе настройки прочитают боевую .env и тесты пойдут в рабочую БД.
"""
from __future__ import annotations

import asyncio
import os
import shutil
import uuid
from pathlib import Path

# Временная БД — рядом с тестами (не в системном TEMP: на некоторых
# конфигурациях Windows он недоступен для записи из процесса).
_TESTS_DIR = Path(__file__).resolve().parent
_TMP_DIR = _TESTS_DIR / f".ami_tests_{uuid.uuid4().hex[:8]}"
_TMP_DIR.mkdir(parents=True, exist_ok=True)
os.environ["AMI_DATABASE_URL"] = f"sqlite:///{_TMP_DIR}/test.db"
os.environ["AMI_LOG_DIR"] = str(_TMP_DIR)
os.environ["AMI_DATA_DIR"] = str(_TMP_DIR)
os.environ["AMI_DEBUG"] = "false"
os.environ["AMI_API_KEY"] = ""

import pytest  # noqa: E402
from fastapi.testclient import TestClient  # noqa: E402

from app.database import Base, engine  # noqa: E402
from app.main import app  # noqa: E402


@pytest.fixture(scope="session", autouse=True)
def _test_database():
    """Создаёт схему во временной БД и удаляет её после тестов."""

    async def create_schema() -> None:
        async with engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        # Соединения привязаны к event loop — закрываем перед TestClient
        await engine.dispose()

    asyncio.run(create_schema())
    yield
    shutil.rmtree(_TMP_DIR, ignore_errors=True)


@pytest.fixture(scope="session")
def client():
    """HTTP-клиент с поднятым приложением (одна временная БД на сессию)."""
    with TestClient(app) as test_client:
        yield test_client
