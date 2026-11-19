"""Main FastAPI приложение."""
from __future__ import annotations

from contextlib import asynccontextmanager
from typing import AsyncGenerator

from fastapi import Depends, FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware

from .config import settings
from .database import engine
from .logger import get_logger, setup_logging
from .security import require_api_key

from .routers import base as base_router
from .routers import categories as categories_router
from .routers import listings as listings_router
from .routers import products as products_router
from .routers import sources as sources_router
from .routers import statistics as statistics_router

log = get_logger("main")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None, None]:
    """Старт и остановка приложения. Схемой управляет Alembic, не create_all."""
    log_dir = setup_logging()
    log.info("AMI backend запущен. Логи: %s", log_dir)
    log.info(
        "БД: %s, API: %s:%s",
        settings.database_url.split("://")[0],
        settings.api_host,
        settings.api_port,
    )
    yield
    await engine.dispose()
    log.info("AMI backend остановлен")


app = FastAPI(
    title=settings.app_name,
    version=settings.app_version,
    debug=settings.debug,
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["*"],
)


@app.middleware("http")
async def log_request(request: Request, call_next):
    log.info("Request: %s %s", request.method, request.url.path)
    response = await call_next(request)
    log.info("Response: %s %s -> %s", request.method, request.url.path, response.status_code)
    return response


@app.get("/")
async def health():
    return {"status": "ok", "version": settings.app_version, "app": settings.app_name}


# Публичные эндпоинты: base (health/info) — без ключа.
app.include_router(base_router.router)

# Рабочие эндпоинты: при заданном AMI_API_KEY требуют X-API-Key.
protected = [Depends(require_api_key)]
app.include_router(categories_router.router, dependencies=protected)
app.include_router(listings_router.router, dependencies=protected)
app.include_router(sources_router.router, dependencies=protected)
app.include_router(statistics_router.router, dependencies=protected)
app.include_router(products_router.router, dependencies=protected)
