"""Сервис статистики рынка: агрегация данных из БД.

Важно: сравнение цен имеет смысл только внутри одной модели товара.
Поэтому аномалии считаются по группам ``product_id``, а не по всей категории.
"""
from __future__ import annotations

from collections import defaultdict
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.domain.market import (
    compare_models,
    compute_stats,
    find_anomalies,
    liquidity_score,
    price_trend,
)
from app.logger import get_logger
from app.models.history import PriceHistory
from app.models.listing import Listing
from app.models.product import Product
from app.models.statistics import MarketStatistics

log = get_logger("services.statistics")


async def get_listings_prices(
    db: AsyncSession,
    category_id: int | None = None,
    product_id: int | None = None,
    exclude_archived: bool = True,
    require_product: bool = False,
) -> list[float]:
    """Цены активных объявлений с фильтрами."""
    stmt = select(Listing.price).where(Listing.price > 0)
    if exclude_archived:
        stmt = stmt.where(Listing.is_archived == False)  # noqa: E712
    if require_product:
        stmt = stmt.where(Listing.product_id.isnot(None))
    if category_id:
        stmt = stmt.join(Product, Listing.product_id == Product.id).where(
            Product.category_id == category_id
        )
    if product_id:
        stmt = stmt.where(Listing.product_id == product_id)
    result = await db.execute(stmt)
    return [float(row[0]) for row in result.all()]


async def get_category_stats(
    db: AsyncSession,
    category_id: int | None = None,
) -> dict[str, Any]:
    """Статистика по категории (или по всему рынку)."""
    prices = await get_listings_prices(db, category_id=category_id)
    stats = compute_stats(prices)

    count_stmt = select(func.count(Listing.id)).where(
        Listing.is_archived == False  # noqa: E712
    )
    if category_id:
        count_stmt = count_stmt.join(Product, Listing.product_id == Product.id).where(
            Product.category_id == category_id
        )
    total = int((await db.scalar(count_stmt)) or 0)

    unlinked_stmt = select(func.count(Listing.id)).where(
        Listing.is_archived == False,  # noqa: E712
        Listing.product_id.is_(None),
    )
    unlinked = int((await db.scalar(unlinked_stmt)) or 0)

    return {
        "category_id": category_id,
        "stats": stats.to_dict(),
        "total_listings": total,
        "unlinked_listings": unlinked,
        "min_sample": settings.min_sample,
        "sample_sufficient": stats.count >= settings.min_sample,
    }


async def get_product_stats(
    db: AsyncSession,
    product_id: int,
) -> dict[str, Any]:
    """Статистика по конкретной модели товара."""
    prices = await get_listings_prices(db, product_id=product_id)
    stats = compute_stats(prices)
    return {
        "product_id": product_id,
        "stats": stats.to_dict(),
        "liquidity": liquidity_score(stats.count, stats.median, stats.max),
        "min_sample": settings.min_sample,
        "sample_sufficient": stats.count >= settings.min_sample,
    }


async def _load_listings_for_anomalies(
    db: AsyncSession,
    category_id: int | None,
    product_id: int | None,
) -> list[Listing]:
    stmt = select(Listing).where(
        Listing.is_archived == False,  # noqa: E712
        Listing.price > 0,
        Listing.product_id.isnot(None),
    )
    if category_id:
        stmt = stmt.join(Product, Listing.product_id == Product.id).where(
            Product.category_id == category_id
        )
    if product_id:
        stmt = stmt.where(Listing.product_id == product_id)
    return list((await db.scalars(stmt)).all())


async def find_market_anomalies(
    db: AsyncSession,
    category_id: int | None = None,
    product_id: int | None = None,
    threshold_mult: float = 1.0,
    limit: int = 50,
    min_sample: int | None = None,
    only_underpriced: bool = True,
) -> dict[str, Any]:
    """Находит недооценённые объявления.

    Сравнение идёт только внутри одной модели (``product_id``), иначе
    дешёвый телефон выглядел бы «аномалией» на фоне ноутбуков.
    Группы с выборкой меньше ``min_sample`` пропускаются.
    """
    min_sample = settings.min_sample if min_sample is None else max(2, min_sample)
    listings = await _load_listings_for_anomalies(db, category_id, product_id)

    groups: dict[int, list[Listing]] = defaultdict(list)
    for listing in listings:
        if listing.product_id is not None:
            groups[listing.product_id].append(listing)

    by_id = {listing.id: listing for listing in listings}
    enriched: list[dict[str, Any]] = []
    checked = 0
    skipped_small = 0

    for group_product_id, items in groups.items():
        if len(items) < min_sample:
            skipped_small += 1
            continue
        checked += 1
        records = [
            {
                "id": item.id,
                "price": item.price,
                "title": item.title,
                "condition": item.condition,
            }
            for item in items
        ]
        for anomaly in find_anomalies(records, median_mult=threshold_mult):
            if only_underpriced and not anomaly.is_underpriced:
                continue
            listing = by_id.get(anomaly.listing_id)
            enriched.append(
                {
                    **anomaly.to_dict(),
                    "product_id": group_product_id,
                    "title": listing.title if listing else "",
                    "url": listing.url if listing else None,
                    "condition": listing.condition.value if listing else None,
                    "sample_size": len(items),
                }
            )

    enriched.sort(key=lambda item: item["deviation_pct"])
    return {
        "anomalies": enriched[: max(0, limit)],
        "listings_scanned": len(listings),
        "products_checked": checked,
        "products_skipped_small_sample": skipped_small,
        "min_sample": min_sample,
        "only_underpriced": only_underpriced,
    }


async def compare_products_in_category(
    db: AsyncSession,
    category_id: int,
) -> list[dict[str, Any]]:
    """Сравнение моделей внутри категории."""
    products = list(
        (await db.scalars(select(Product).where(Product.category_id == category_id))).all()
    )

    products_data = []
    for product in products:
        prices = await get_listings_prices(db, product_id=product.id)
        products_data.append(
            {
                "slug": product.slug,
                "name": product.name,
                "prices": prices,
            }
        )

    return [comparison.to_dict() for comparison in compare_models(products_data)]


async def get_listing_trend(
    db: AsyncSession,
    listing_id: str,
) -> dict[str, Any]:
    """Динамика цен конкретного объявления."""
    history = list(
        (
            await db.scalars(
                select(PriceHistory)
                .where(PriceHistory.listing_id == listing_id)
                .order_by(PriceHistory.created_at, PriceHistory.id)
            )
        ).all()
    )
    return price_trend([{"date": row.created_at, "price": row.price} for row in history])


async def save_market_statistics(
    db: AsyncSession,
    category_id: int | None,
    product_id: int | None,
    period: str = "week",
) -> MarketStatistics:
    """Сохраняет снимок статистики в MarketStatistics (для истории)."""
    import datetime as dt

    prices = await get_listings_prices(db, category_id=category_id, product_id=product_id)
    stats = compute_stats(prices)

    now = dt.datetime.now(dt.timezone.utc)
    stat = MarketStatistics(
        category_id=category_id,
        product_id=product_id,
        period=period,
        date_start=now - dt.timedelta(days=7),
        date_end=now,
        listing_count=stats.count,
        total_volume=float(sum(prices)),
        avg_price=stats.mean,
        median_price=stats.median,
        min_price=stats.min,
        max_price=stats.max,
        std_price=stats.std,
        q1_price=stats.q1,
        q3_price=stats.q3,
        extra_metrics={},
    )
    db.add(stat)
    await db.flush()
    log.debug("Сохранена статистика: category=%s, count=%s", category_id, stats.count)
    return stat
