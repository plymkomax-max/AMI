"""Роутер: Base routes."""
from __future__ import annotations

import sys

from fastapi import APIRouter

from app.config import settings
from app.database import check_db
from app.schemas.common import HealthResponse, SystemInfo

router = APIRouter(prefix="/api/v1", tags=["base"])


@router.get("/health", response_model=HealthResponse)
async def health() -> HealthResponse:
    db_ok = await check_db()
    scheme = settings.database_url.split("://")[0].split("+")[0]
    return HealthResponse(
        status="ok" if db_ok else "degraded",
        detail="Service is running" if db_ok else "Database is unavailable",
        data={
            "python_version": f"{sys.version_info.major}.{sys.version_info.minor}",
            "database": scheme,
            "db_status": "ok" if db_ok else "error",
        },
    )


@router.get("/info", response_model=SystemInfo)
async def info() -> SystemInfo:
    return SystemInfo(
        app=settings.app_name,
        version=settings.app_version,
        debug=settings.debug,
        python_version=f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}",
    )
