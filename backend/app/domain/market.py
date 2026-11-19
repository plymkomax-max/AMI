"""Market Intelligence Engine: статистика рынка, аномалии, динамика.

Вся математика здесь — только на numpy/pandas, без LLM.
LLM никогда не вычисляет цены и статистику.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable

import numpy as np


@dataclass
class PriceStats:
    """Статистика цен по выборке."""
    count: int = 0
    mean: float | None = None
    median: float | None = None
    std: float | None = None
    min: float | None = None
    max: float | None = None
    q1: float | None = None
    q3: float | None = None
    iqr: float | None = None
    # Нижняя/верхняя границы для выбросов (Tukey)
    lower_fence: float | None = None
    upper_fence: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "count": self.count,
            "mean": self.mean,
            "median": self.median,
            "std": self.std,
            "min": self.min,
            "max": self.max,
            "q1": self.q1,
            "q3": self.q3,
            "iqr": self.iqr,
            "lower_fence": self.lower_fence,
            "upper_fence": self.upper_fence,
        }


def compute_stats(prices: Iterable[float]) -> PriceStats:
    """Считает базовую статистику цен (медиана, квантили, std, fences)."""
    arr = np.asarray(list(prices), dtype=float)
    arr = arr[~np.isnan(arr) & (arr > 0)]
    if arr.size == 0:
        return PriceStats(count=0)

    q1 = float(np.percentile(arr, 25))
    q3 = float(np.percentile(arr, 75))
    iqr = q3 - q1

    return PriceStats(
        count=int(arr.size),
        mean=float(np.mean(arr)),
        median=float(np.median(arr)),
        std=float(np.std(arr, ddof=1)) if arr.size > 1 else 0.0,
        min=float(np.min(arr)),
        max=float(np.max(arr)),
        q1=q1,
        q3=q3,
        iqr=iqr,
        lower_fence=q1 - 1.5 * iqr,
        upper_fence=q3 + 1.5 * iqr,
    )


@dataclass
class Anomaly:
    """Ценовая аномалия."""
    listing_id: str
    price: float
    market_median: float
    deviation_pct: float  # (price - median) / median * 100
    is_underpriced: bool  # дешевле рынка
    severity: str  # low, medium, high

    def to_dict(self) -> dict[str, Any]:
        return {
            "listing_id": self.listing_id,
            "price": self.price,
            "market_median": self.market_median,
            "deviation_pct": round(self.deviation_pct, 2),
            "is_underpriced": self.is_underpriced,
            "severity": self.severity,
        }


def find_anomalies(
    listings: list[dict[str, Any]],
    price_key: str = "price",
    median_mult: float = 1.0,
) -> list[Anomaly]:
    """Находит ценовые аномалии относительно медианы выборки.

    Аргументы:
        listings: список {id, price, ...}
        price_key: ключ цены
        median_mult: множитель порога (1.0 = классический Tukey)
    """
    if not listings:
        return []

    prices = [l.get(price_key) for l in listings]
    prices = [float(p) for p in prices if p and float(p) > 0]
    if not prices:
        return []

    stats = compute_stats(prices)
    if stats.median is None:
        return []

    anomalies: list[Anomaly] = []
    for listing in listings:
        price = float(listing.get(price_key) or 0)
        if price <= 0:
            continue
        deviation = (price - stats.median) / stats.median * 100.0

        # Определяем порог: либо по IQR, либо по проценту от медианы
        threshold_pct = 30.0 * median_mult
        if abs(deviation) < threshold_pct:
            continue

        is_underpriced = deviation < 0
        severity = "medium"
        if abs(deviation) > 60.0 * median_mult:
            severity = "high"
        elif abs(deviation) > 40.0 * median_mult:
            severity = "medium"
        else:
            severity = "low"

        anomalies.append(
            Anomaly(
                listing_id=str(listing.get("id") or ""),
                price=price,
                market_median=stats.median,
                deviation_pct=deviation,
                is_underpriced=is_underpriced,
                severity=severity,
            )
        )

    # Сортируем: самые недооценённые первыми
    anomalies.sort(key=lambda a: a.deviation_pct)
    return anomalies


@dataclass
class ModelComparison:
    """Сравнение моделей (товаров) в категории."""
    product_slug: str
    product_name: str
    count: int
    median_price: float | None
    mean_price: float | None
    min_price: float | None
    max_price: float | None
    price_volatility: float | None  # std / median * 100

    def to_dict(self) -> dict[str, Any]:
        return {
            "product_slug": self.product_slug,
            "product_name": self.product_name,
            "count": self.count,
            "median_price": self.median_price,
            "mean_price": self.mean_price,
            "min_price": self.min_price,
            "max_price": self.max_price,
            "price_volatility": round(self.price_volatility, 2) if self.price_volatility is not None else None,
        }


def compare_models(
    products: list[dict[str, Any]],
    price_key: str = "price",
) -> list[ModelComparison]:
    """Сравнивает модели по ценам. products: [{slug, name, prices:[...]}]."""
    results: list[ModelComparison] = []
    for prod in products:
        prices = [float(p) for p in prod.get("prices", []) if p and float(p) > 0]
        if not prices:
            continue
        stats = compute_stats(prices)
        vol = (stats.std / stats.median * 100.0) if stats.median else None
        results.append(
            ModelComparison(
                product_slug=prod.get("slug", ""),
                product_name=prod.get("name", ""),
                count=stats.count,
                median_price=stats.median,
                mean_price=stats.mean,
                min_price=stats.min,
                max_price=stats.max,
                price_volatility=vol,
            )
        )
    results.sort(key=lambda c: (c.median_price or 0))
    return results


def price_trend(
    price_history: list[dict[str, Any]],
) -> dict[str, Any]:
    """Анализ динамики цен. price_history: [{date, price}]."""
    if len(price_history) < 2:
        return {
            "count": len(price_history),
            "change_pct": None,
            "trend": "insufficient_data",
        }
    prices = [float(p["price"]) for p in price_history]
    first = prices[0]
    last = prices[-1]
    change_pct = (last - first) / first * 100.0 if first else None
    if change_pct is None:
        trend = "insufficient_data"
    elif change_pct < -3:
        trend = "falling"
    elif change_pct > 3:
        trend = "rising"
    else:
        trend = "stable"
    return {
        "count": len(price_history),
        "first_price": first,
        "last_price": last,
        "change_pct": round(change_pct, 2) if change_pct is not None else None,
        "trend": trend,
    }


def liquidity_score(
    count: int,
    median_price: float | None,
    max_price: float | None,
) -> float:
    """Оценка ликвидности товара: 0..1.

    Учитывает количество предложений и разброс цен.
    Много объявлений + стабильные цены = выше ликвидность.
    """
    if count == 0 or not median_price or not max_price:
        return 0.0
    # Объём: логарифмическая шкала, 10+ объявлений -> хорошо
    volume_score = min(1.0, np.log1p(count) / np.log1p(30))
    # Разброс цен: чем меньше волатильность, тем выше ликвидность
    if max_price > 0:
        spread = (max_price - median_price) / median_price
        price_score = max(0.0, 1.0 - spread)
    else:
        price_score = 0.5
    return round(0.6 * volume_score + 0.4 * price_score, 3)
