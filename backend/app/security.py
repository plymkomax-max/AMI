"""Безопасность: проверка API-ключа.

Ключ задаётся переменной AMI_API_KEY. Если она пуста, API открыт
(локальный режим). Если задана — все рабочие эндпоинты требуют заголовок
``X-API-Key``.
"""
from __future__ import annotations

import secrets

from fastapi import Depends, HTTPException, status
from fastapi.security import APIKeyHeader

from .config import settings

api_key_header = APIKeyHeader(name="X-API-Key", auto_error=False)


def verify_api_key(provided: str | None) -> None:
    """Сверяет ключ. Бросает 401, если ключ задан и не совпал."""
    expected = (settings.api_key or "").strip()
    if not expected:
        return
    if not provided or not secrets.compare_digest(provided, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Неверный или отсутствующий API-ключ",
            headers={"WWW-Authenticate": "ApiKey"},
        )


async def require_api_key(
    x_api_key: str | None = Depends(api_key_header),
) -> None:
    """FastAPI-зависимость для защиты роутеров."""
    verify_api_key(x_api_key)
