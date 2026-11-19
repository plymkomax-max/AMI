"""Роутер: Статистика рынка и аномалии."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.logger import get_logger
from app.services.statistics_service import (
    compare_products_in_category,
    find_market_anomalies,
    get_category_stats,
    get_listing_trend,
    get_product_stats,
)

log = get_logger("router.statistics")

router = APIRouter(prefix="/api/v1/statistics", tags=["statistics"])


@router.get("/market")
async def market_stats(
    db: AsyncSession = Depends(get_db),
    category_id: int | None = Query(None, gt=0),
) -> dict:
    """Общая статистика рынка (или категории)."""
    return await get_category_stats(db, category_id)


@router.get("/products/{product_id}")
async def product_stats(
    product_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Статистика по модели товара."""
    return await get_product_stats(db, product_id)


@router.get("/anomalies")
async def anomalies(
    db: AsyncSession = Depends(get_db),
    category_id: int | None = Query(None, gt=0),
    product_id: int | None = Query(None, gt=0),
    limit: int = Query(50, ge=1, le=200),
    min_sample: int | None = Query(None, ge=2, le=1000),
) -> dict:
    """Недооценённые предложения.

    Сравнение — только внутри одной модели; группы с маленькой выборкой
    пропускаются (см. ``min_sample``).
    """
    result = await find_market_anomalies(
        db,
        category_id=category_id,
        product_id=product_id,
        limit=limit,
        min_sample=min_sample if min_sample is not None else settings.min_sample,
    )
    return {
        "status": "ok",
        "count": len(result["anomalies"]),
        **result,
    }


@router.get("/compare/{category_id}")
async def compare_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Сравнение моделей внутри категории."""
    comparisons = await compare_products_in_category(db, category_id)
    return {"status": "ok", "comparisons": comparisons}


@router.get("/listings/{listing_id}/trend")
async def listing_trend(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
) -> dict:
    """Динамика цены конкретного объявления."""
    return await get_listing_trend(db, listing_id)
