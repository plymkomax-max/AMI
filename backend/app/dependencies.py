"""Общие зависимости FastAPI.

Собраны в одном месте, чтобы роутеры импортировали их отсюда.
"""
from __future__ import annotations

from .database import get_db
from .security import require_api_key

__all__ = ["get_db", "require_api_key"]
