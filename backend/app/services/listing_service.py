"""Бизнес-логика объявлений: нормализация, upsert, дедупликация, поиск.

Сервис не делает commit: одна транзакция на HTTP-запрос (см. get_db).
"""
from __future__ import annotations

import datetime as dt
import hashlib
import re
from typing import Any

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.logger import get_logger
from app.models.history import ListingHistory, PriceHistory
from app.models.listing import Listing, ListingCondition
from app.models.product import Product
from app.services.matcher import ProductMatcher, extract_attributes

log = get_logger("services.listings")

LOCAL_TZ = dt.datetime.now().astimezone().tzinfo


# ========== Нормализация ==========

def normalize_price(price: Any) -> float | None:
    """Нормализует цену: '12 500 ₽', '12500', '12,500', '1.234,56'."""
    if price is None:
        return None
    if isinstance(price, bool):
        return None
    if isinstance(price, (int, float)):
        return float(price) if price > 0 else None

    s = str(price).strip()
    if not s:
        return None

    s = re.sub(r"(?i)(руб\.?|rub|₽|р\.)", "", s)
    s = s.replace("\xa0", "").replace(" ", "")

    if "," in s and "." in s:
        # Десятичный разделитель — тот, что стоит правее
        if s.rfind(",") > s.rfind("."):
            s = s.replace(".", "").replace(",", ".")
        else:
            s = s.replace(",", "")
    elif "," in s:
        parts = s.split(",")
        # '12,500' — разделитель тысяч; '12500,50' — десятичная запятая
        if len(parts) == 2 and parts[-1].isdigit() and len(parts[-1]) == 3:
            s = s.replace(",", "")
        else:
            s = s.replace(",", ".")

    match = re.search(r"-?\d+(?:\.\d+)?", s)
    if not match:
        return None
    value = float(match.group())
    if value <= 0:
        return None
    return value


_CONDITION_MAP = {
    "новый": ListingCondition.NEW,
    "новое": ListingCondition.NEW,
    "new": ListingCondition.NEW,
    "запечатан": ListingCondition.NEW,
    "как новый": ListingCondition.LIKE_NEW,
    "как новое": ListingCondition.LIKE_NEW,
    "like new": ListingCondition.LIKE_NEW,
    "like_new": ListingCondition.LIKE_NEW,
    "отличное": ListingCondition.LIKE_NEW,
    "идеальное": ListingCondition.LIKE_NEW,
    "хорошее": ListingCondition.GOOD,
    "good": ListingCondition.GOOD,
    "рабочий": ListingCondition.GOOD,
    "рабочее": ListingCondition.GOOD,
    "б/у": ListingCondition.GOOD,
    "бу": ListingCondition.GOOD,
    "used": ListingCondition.GOOD,
    "нормальное": ListingCondition.FAIR,
    "fair": ListingCondition.FAIR,
    "удовлетворительное": ListingCondition.FAIR,
    "плохое": ListingCondition.POOR,
    "poor": ListingCondition.POOR,
    "убитое": ListingCondition.POOR,
    "неисправен": ListingCondition.BROKEN,
    "неисправно": ListingCondition.BROKEN,
    "нерабочий": ListingCondition.BROKEN,
    "сломан": ListingCondition.BROKEN,
    "не работает": ListingCondition.BROKEN,
    "требует ремонта": ListingCondition.BROKEN,
    "broken": ListingCondition.BROKEN,
    "на запчасти": ListingCondition.FOR_PARTS,
    "донор": ListingCondition.FOR_PARTS,
    "for_parts": ListingCondition.FOR_PARTS,
}


def normalize_condition(raw: Any) -> ListingCondition:
    """Определяет состояние из текста или enum. Неизвестное → GOOD."""
    if isinstance(raw, ListingCondition):
        return raw
    s = str(raw or "").strip().lower()
    return _CONDITION_MAP.get(s, ListingCondition.GOOD)


def normalize_condition_from_llm(text: str | None) -> ListingCondition:
    """Быстрая эвристика состояния из описания (без LLM)."""
    if not text:
        return ListingCondition.GOOD
    low = text.lower()
    if any(
        w in low
        for w in (
            "не работает",
            "неисправ",
            "не включается",
            "не заряжается",
            "не грузится",
            "разбит",
            "треснул",
        )
    ):
        return ListingCondition.BROKEN
    if any(w in low for w in ("на запчасти", "донор", "аварийное")):
        return ListingCondition.FOR_PARTS
    if any(w in low for w in ("новый", "новое", "запечатан", "заводской")):
        return ListingCondition.NEW
    if any(w in low for w in ("как новый", "отличное", "идеальное")):
        return ListingCondition.LIKE_NEW
    return ListingCondition.GOOD


def make_listing_id(source: str, external_id: str) -> str:
    """Генерирует стабильный id объявления из (source, external_id)."""
    raw = f"{(source or 'manual').strip().lower()}:{external_id}"
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:32]


_DATETIME_FORMATS = (
    "%d.%m.%Y %H:%M:%S",
    "%d.%m.%Y %H:%M",
    "%d.%m.%Y",
    "%Y-%m-%d %H:%M:%S",
    "%Y-%m-%d %H:%M",
    "%Y-%m-%d",
    "%d/%m/%Y",
    "%d/%m/%Y %H:%M",
)


def parse_datetime(value: Any, field: str = "datetime") -> dt.datetime | None:
    """Парсит дату из CSV/Excel и приводит к UTC.

    Дата без времени (``15.01.2026``) трактуется как календарная дата и
    сохраняется как полночь UTC — иначе при пересчёте из местного времени
    она «съезжала» бы на предыдущий день.

    Некорректная дата не роняет импорт: поле пропускается с предупреждением.
    """
    if value is None or value == "":
        return None

    date_only = False
    if isinstance(value, dt.datetime):
        moment = value
        # Excel отдаёт дату как datetime(год, месяц, день, 0:00) —
        # это календарная дата, а не полночь по местному времени.
        if moment.tzinfo is None and moment.time() == dt.time(0, 0):
            date_only = True
    elif isinstance(value, dt.date):
        moment = dt.datetime(value.year, value.month, value.day)
        date_only = True
    else:
        text = str(value).strip()
        if not text:
            return None
        # Дата без времени: 2026-01-15, 15.01.2026, 15/01/2026
        date_only = len(text) <= 10 and ":" not in text and "T" not in text
        try:
            moment = dt.datetime.fromisoformat(text.replace("Z", "+00:00"))
        except ValueError:
            moment = None
            for fmt in _DATETIME_FORMATS:
                try:
                    moment = dt.datetime.strptime(text, fmt)
                    break
                except ValueError:
                    continue
            if moment is None:
                log.warning("Не удалось разобрать %s: %r", field, value)
                return None

    if date_only:
        return moment.replace(tzinfo=dt.timezone.utc)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=LOCAL_TZ)
    return moment.astimezone(dt.timezone.utc)


def as_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        sep = ";" if ";" in value else ","
        return [item.strip() for item in value.split(sep) if item.strip()]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()]


def as_int(value: Any) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(str(value).replace(" ", "").replace("\xa0", ""))
    except (TypeError, ValueError):
        return None


async def _validated_product_id(db: AsyncSession, raw: Any) -> int | None:
    if raw in (None, ""):
        return None
    try:
        product_id = int(float(raw))
    except (TypeError, ValueError) as exc:
        raise ValueError(f"Некорректный product_id: {raw!r}") from exc
    if product_id <= 0:
        raise ValueError(f"Некорректный product_id: {product_id}")
    exists = await db.scalar(select(Product.id).where(Product.id == product_id))
    if not exists:
        raise ValueError(f"Товар с id={product_id} не найден")
    return product_id


# ========== CRUD ==========

async def upsert_listing(
    db: AsyncSession,
    data: dict[str, Any],
    source: str = "manual",
    matcher: ProductMatcher | None = None,
) -> tuple[Listing, bool]:
    """Создаёт или обновляет объявление. Возвращает (listing, created).

    Дедупликация по (source, external_id). Если product_id не задан явно,
    модель определяется матчером. Commit не выполняется.
    """
    source = (source or data.get("source") or "manual").strip().lower()[:32]
    external_id = str(data.get("external_id") or "").strip()
    if not external_id:
        raise ValueError("external_id обязателен")

    price = normalize_price(data.get("price"))
    if price is None:
        raise ValueError(f"Цена невалидна: {data.get('price')!r}")

    explicit_product = data.get("product_id")
    product_id = await _validated_product_id(db, explicit_product)
    listing_id = make_listing_id(source, external_id)

    existing = await db.scalar(select(Listing).where(Listing.id == listing_id))
    title = str(data.get("title") or "").strip()[:512]
    description = data.get("description")
    published_at = parse_datetime(data.get("published_at"), "published_at")
    expired_at = parse_datetime(data.get("expired_at"), "expired_at")

    explicit_attributes = data.get("attributes") or {}
    if not isinstance(explicit_attributes, dict):
        explicit_attributes = {}

    confidence = 1.0 if product_id is not None else 0.0
    method = "manual" if product_id is not None else "none"
    extracted: dict[str, Any] = {}

    if matcher is not None:
        match_result = matcher.match(title, description)
        extracted = dict(match_result.attributes)
        if product_id is None and match_result.product_id is not None:
            product_id = match_result.product_id
            confidence = match_result.confidence
            method = "auto"
        elif product_id is None:
            confidence = float(match_result.confidence or 0.0)
            method = (
                match_result.method
                if match_result.method in ("ambiguous", "disabled", "none")
                else "none"
            )
    else:
        extracted = extract_attributes(title, description)

    attributes = {**extracted, **explicit_attributes}

    if existing is None:
        listing = Listing(
            id=listing_id,
            source=source,
            external_id=external_id,
            url=data.get("url"),
            product_id=product_id,
            match_confidence=confidence,
            match_method=method,
            attributes=attributes,
            title=title,
            description=description,
            price=price,
            currency=(str(data.get("currency") or "RUB").strip().upper()[:4] or "RUB"),
            condition=normalize_condition(data.get("condition")),
            usage_time=data.get("usage_time"),
            includes=as_list(data.get("includes")),
            defects=as_list(data.get("defects")),
            city=data.get("city"),
            region=data.get("region"),
            seller_type=data.get("seller_type"),
            published_at=published_at,
            expired_at=expired_at,
            view_count=as_int(data.get("view_count")),
            fav_count=as_int(data.get("fav_count")),
        )
        db.add(listing)
        await db.flush()

        db.add(PriceHistory(listing_id=listing_id, price=price, currency=listing.currency))
        db.add(
            ListingHistory(
                listing_id=listing_id,
                event_type="created",
                data={"price": price, "source": source, "match": method},
            )
        )
        await db.flush()
        log.info(
            "Создано объявление %s: %s (match=%s, %.2f)",
            listing_id,
            listing.title[:60],
            method,
            confidence,
        )
        return listing, True

    # --- Обновление ---
    changed: list[str] = []

    if existing.price != price:
        old_price = existing.price
        existing.price = price
        db.add(PriceHistory(listing_id=listing_id, price=price, currency=existing.currency))
        changed.append("price")
        log.debug("Цена %s: %s -> %s", listing_id, old_price, price)

    def update(field: str, value: Any) -> None:
        if value is None:
            return
        if getattr(existing, field) != value:
            setattr(existing, field, value)
            changed.append(field)

    explicit_product_set = explicit_product not in (None, "")
    if explicit_product_set:
        if existing.product_id != product_id:
            existing.product_id = product_id
            changed.append("product_id")
        existing.match_confidence = 1.0
        existing.match_method = "manual"
    elif existing.product_id is None and product_id is not None:
        existing.product_id = product_id
        existing.match_confidence = confidence
        existing.match_method = "auto"
        changed.append("product_id")
    elif existing.product_id is None:
        existing.match_confidence = confidence
        existing.match_method = method

    update("url", data.get("url"))
    update("title", title or None)
    update("description", description)
    update(
        "currency",
        (str(data["currency"]).strip().upper()[:4] if data.get("currency") else None),
    )
    update(
        "condition",
        (normalize_condition(data["condition"]) if data.get("condition") is not None else None),
    )
    update("usage_time", data.get("usage_time"))
    update("city", data.get("city"))
    update("region", data.get("region"))
    update("seller_type", data.get("seller_type"))
    update("published_at", published_at)
    update("expired_at", expired_at)
    update("view_count", as_int(data.get("view_count")))
    update("fav_count", as_int(data.get("fav_count")))

    merged_attributes = {**(existing.attributes or {}), **extracted, **explicit_attributes}
    if merged_attributes != (existing.attributes or {}):
        existing.attributes = merged_attributes
        changed.append("attributes")

    if data.get("includes") is not None:
        includes = as_list(data["includes"])
        if existing.includes != includes:
            existing.includes = includes
            changed.append("includes")

    if data.get("defects") is not None:
        defects = as_list(data["defects"])
        if existing.defects != defects:
            existing.defects = defects
            changed.append("defects")

    if changed:
        db.add(
            ListingHistory(
                listing_id=listing_id,
                event_type="updated",
                data={"fields": sorted(set(changed)), "price": price},
            )
        )
        await db.flush()
        log.debug("Обновлено объявление %s: %s", listing_id, sorted(set(changed)))

    return existing, False


async def update_listing(
    db: AsyncSession,
    listing_id: str,
    data: dict[str, Any],
) -> Listing | None:
    """Точечное обновление (PATCH): ручная привязка к модели, цена, атрибуты."""
    listing = await get_listing(db, listing_id)
    if listing is None:
        return None

    changed: list[str] = []

    if "product_id" in data:
        product_id = await _validated_product_id(db, data.get("product_id"))
        if listing.product_id != product_id:
            listing.product_id = product_id
            changed.append("product_id")
        listing.match_confidence = 1.0 if product_id is not None else 0.0
        listing.match_method = "manual" if product_id is not None else "none"

    if data.get("price") is not None:
        price = normalize_price(data["price"])
        if price is None:
            raise ValueError(f"Цена невалидна: {data['price']!r}")
        if listing.price != price:
            old_price = listing.price
            listing.price = price
            db.add(PriceHistory(listing_id=listing_id, price=price, currency=listing.currency))
            changed.append("price")
            log.debug("Цена %s: %s -> %s", listing_id, old_price, price)

    for field in ("title", "description", "url", "usage_time", "city", "region", "seller_type"):
        value = data.get(field)
        if value is not None and getattr(listing, field) != value:
            setattr(listing, field, value)
            changed.append(field)

    if data.get("currency") is not None:
        currency = str(data["currency"]).strip().upper()[:4]
        if listing.currency != currency:
            listing.currency = currency
            changed.append("currency")

    if data.get("condition") is not None:
        condition = normalize_condition(data["condition"])
        if listing.condition != condition:
            listing.condition = condition
            changed.append("condition")

    if data.get("published_at") is not None:
        published_at = parse_datetime(data["published_at"], "published_at")
        if listing.published_at != published_at:
            listing.published_at = published_at
            changed.append("published_at")

    if data.get("attributes") is not None:
        attributes = data["attributes"]
        if not isinstance(attributes, dict):
            raise ValueError("attributes должен быть объектом")
        merged = {**(listing.attributes or {}), **attributes}
        if merged != (listing.attributes or {}):
            listing.attributes = merged
            changed.append("attributes")

    if data.get("includes") is not None:
        includes = as_list(data["includes"])
        if listing.includes != includes:
            listing.includes = includes
            changed.append("includes")

    if data.get("defects") is not None:
        defects = as_list(data["defects"])
        if listing.defects != defects:
            listing.defects = defects
            changed.append("defects")

    if data.get("view_count") is not None:
        listing.view_count = as_int(data["view_count"])
        changed.append("view_count")

    if data.get("fav_count") is not None:
        listing.fav_count = as_int(data["fav_count"])
        changed.append("fav_count")

    if changed:
        db.add(
            ListingHistory(
                listing_id=listing_id,
                event_type="updated",
                data={"fields": sorted(set(changed))},
            )
        )
        await db.flush()

    return listing

async def get_listing(db: AsyncSession, listing_id: str) -> Listing | None:
    return await db.scalar(select(Listing).where(Listing.id == listing_id))


async def archive_listing(db: AsyncSession, listing_id: str, reason: str = "deleted") -> bool:
    """Помечает объявление архивным (не удаляет — это история рынка)."""
    listing = await get_listing(db, listing_id)
    if not listing:
        return False
    if listing.is_archived:
        return True
    listing.is_archived = True
    listing.archive_reason = reason
    db.add(
        ListingHistory(
            listing_id=listing_id,
            event_type="archived",
            data={"reason": reason},
        )
    )
    await db.flush()
    return True


async def search_listings(
    db: AsyncSession,
    filters: dict[str, Any],
    page: int = 1,
    per_page: int = 50,
) -> tuple[list[Listing], int]:
    """Поиск объявлений с фильтрами и пагинацией."""
    page = max(1, int(page))
    per_page = min(max(1, int(per_page)), 200)

    conditions = []
    if filters.get("source"):
        conditions.append(Listing.source == filters["source"])
    if filters.get("condition"):
        conditions.append(Listing.condition == filters["condition"])
    if filters.get("city"):
        conditions.append(Listing.city == filters["city"])
    if filters.get("min_price") is not None:
        conditions.append(Listing.price >= filters["min_price"])
    if filters.get("max_price") is not None:
        conditions.append(Listing.price <= filters["max_price"])
    if filters.get("product_id"):
        conditions.append(Listing.product_id == filters["product_id"])
    if filters.get("is_archived") is not None:
        conditions.append(Listing.is_archived == filters["is_archived"])

    stmt = (
        select(Listing)
        .where(*conditions)
        .order_by(Listing.created_at.desc())
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    count_stmt = select(func.count(Listing.id)).where(*conditions)

    listings = list((await db.scalars(stmt)).all())
    total = int((await db.scalar(count_stmt)) or 0)
    return listings, total
