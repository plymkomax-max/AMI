"""Роутер: Объявления."""
from __future__ import annotations

from fastapi import APIRouter, Depends, File, HTTPException, Query, UploadFile, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app.logger import get_logger
from app.models.listing import Listing, ListingCondition
from app.schemas.listing import (
    ImportResult,
    ListingCreate,
    ListingList,
    ListingRead,
    ListingUpdate,
)
from app.services.importer import import_records, parse_csv_content, parse_xlsx_content
from app.services.listing_service import (
    archive_listing,
    get_listing,
    search_listings,
    update_listing,
    upsert_listing,
)
from app.services.matcher import ProductMatcher

log = get_logger("router.listings")

router = APIRouter(prefix="/api/v1/listings", tags=["listings"])


def _to_read(listing: Listing) -> ListingRead:
    return ListingRead(
        id=listing.id,
        source=listing.source,
        external_id=listing.external_id,
        url=listing.url,
        product_id=listing.product_id,
        match_confidence=listing.match_confidence,
        match_method=listing.match_method,
        attributes=listing.attributes or {},
        title=listing.title,
        description=listing.description,
        price=listing.price,
        currency=listing.currency,
        condition=listing.condition,
        usage_time=listing.usage_time,
        includes=listing.includes or [],
        defects=listing.defects or [],
        city=listing.city,
        region=listing.region,
        seller_type=listing.seller_type,
        published_at=listing.published_at,
        view_count=listing.view_count,
        fav_count=listing.fav_count,
        is_archived=listing.is_archived,
        archive_reason=listing.archive_reason,
        weight=listing.weight,
        created_at=listing.created_at,
        updated_at=listing.updated_at,
    )


@router.post("/", response_model=ListingRead)
async def create_listing(
    payload: ListingCreate,
    db: AsyncSession = Depends(get_db),
) -> ListingRead:
    matcher = await ProductMatcher.load(db)
    try:
        listing, _ = await upsert_listing(
            db, payload.model_dump(), source=payload.source, matcher=matcher
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    return _to_read(listing)


@router.get("/", response_model=ListingList)
async def list_listings(
    db: AsyncSession = Depends(get_db),
    source: str | None = None,
    condition: ListingCondition | None = None,
    city: str | None = None,
    min_price: float | None = Query(None, ge=0),
    max_price: float | None = Query(None, ge=0),
    product_id: int | None = Query(None, gt=0),
    is_archived: bool | None = False,
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
) -> ListingList:
    filters = {
        "source": source,
        "condition": condition,
        "city": city,
        "min_price": min_price,
        "max_price": max_price,
        "product_id": product_id,
        "is_archived": is_archived,
    }
    listings, total = await search_listings(db, filters, page, per_page)
    return ListingList(
        data=[_to_read(listing) for listing in listings],
        total=total,
        page=page,
        per_page=per_page,
    )


@router.get("/unmatched")
async def list_unmatched(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    per_page: int = Query(50, ge=1, le=200),
) -> dict:
    """Объявления без модели — их нужно разобрать вручную."""
    conditions = [Listing.product_id.is_(None), Listing.is_archived == False]  # noqa: E712
    total = int(
        (await db.scalar(select(func.count(Listing.id)).where(*conditions))) or 0
    )
    listings = list(
        (
            await db.scalars(
                select(Listing)
                .where(*conditions)
                .order_by(Listing.created_at.desc())
                .offset((page - 1) * per_page)
                .limit(per_page)
            )
        ).all()
    )
    return {
        "status": "ok",
        "total": total,
        "page": page,
        "per_page": per_page,
        "data": [_to_read(listing) for listing in listings],
    }


@router.get("/{listing_id}", response_model=ListingRead)
async def get_listing_by_id(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
) -> ListingRead:
    listing = await get_listing(db, listing_id)
    if not listing:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Listing not found")
    return _to_read(listing)


@router.patch("/{listing_id}", response_model=ListingRead)
async def patch_listing(
    listing_id: str,
    payload: ListingUpdate,
    db: AsyncSession = Depends(get_db),
) -> ListingRead:
    """Ручная правка: привязать модель, изменить цену или атрибуты."""
    try:
        listing = await update_listing(
            db, listing_id, payload.model_dump(exclude_unset=True)
        )
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    if listing is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Listing not found")
    return _to_read(listing)


@router.post("/{listing_id}/archive", response_model=ListingRead)
async def archive_listing_by_id(
    listing_id: str,
    db: AsyncSession = Depends(get_db),
    reason: str = Query("user_archived", max_length=64),
) -> ListingRead:
    ok = await archive_listing(db, listing_id, reason)
    if not ok:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Listing not found")
    listing = await get_listing(db, listing_id)
    if listing is None:  # pragma: no cover - защита от гонки удаления
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Listing not found")
    return _to_read(listing)


async def _read_upload(file: UploadFile) -> bytes:
    content = await file.read(settings.max_csv_bytes + 1)
    if len(content) > settings.max_csv_bytes:
        raise HTTPException(
            status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            detail=f"Файл больше {settings.max_csv_bytes // (1024 * 1024)} МБ",
        )
    return content


@router.post("/import/csv", response_model=ImportResult)
async def import_csv(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    source: str = Query("csv", min_length=1, max_length=32),
) -> ImportResult:
    """Импорт CSV: UTF-8/cp1251, ``,`` и ``;``, даты, русские заголовки."""
    content = await _read_upload(file)
    try:
        records = parse_csv_content(content, source=source)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc

    result = await import_records(db, records, source=source)
    log.info(
        "Импорт CSV (%s): строк=%s, новых=%s, обновлено=%s, ошибок=%s",
        source,
        result["total_rows"],
        result["imported"],
        result["updated"],
        result["skipped"],
    )
    return ImportResult(**result)


@router.post("/import/excel", response_model=ImportResult)
async def import_excel(
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    source: str = Query("excel", min_length=1, max_length=32),
) -> ImportResult:
    """Импорт первого листа .xlsx."""
    content = await _read_upload(file)
    try:
        records = parse_xlsx_content(content, source=source)
    except ValueError as exc:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc

    result = await import_records(db, records, source=source)
    log.info(
        "Импорт Excel (%s): строк=%s, новых=%s, обновлено=%s, ошибок=%s",
        source,
        result["total_rows"],
        result["imported"],
        result["updated"],
        result["skipped"],
    )
    return ImportResult(**result)
