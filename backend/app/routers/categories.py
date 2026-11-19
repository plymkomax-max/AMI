"""Роутер: Категории."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.category import Category, ProductDeviceType
from app.schemas.common import CategoryRead, CategoryCreate, CategoryList
from app.logger import get_logger

log = get_logger("router.categories")

router = APIRouter(prefix="/api/v1/categories", tags=["categories"])


@router.get("/", response_model=CategoryList)
async def list_categories(db: AsyncSession = Depends(get_db)) -> CategoryList:
    stmt = select(Category).order_by(Category.name)
    result = await db.execute(stmt)
    categories = result.scalars().all()
    data = [
        CategoryRead(
            id=c.id,
            name=c.name,
            slug=c.slug,
            description=c.description,
            device_type=c.device_type,
            market_weight=c.market_weight,
            created_at=c.created_at,
        )
        for c in categories
    ]
    return CategoryList(data=data, total=len(data))


@router.post("/", response_model=CategoryRead)
async def create_category(
    payload: CategoryCreate,
    db: AsyncSession = Depends(get_db),
) -> CategoryRead:
    category = Category(
        name=payload.name,
        slug=payload.slug,
        description=payload.description,
        device_type=payload.device_type,
        market_weight=payload.market_weight,
    )
    db.add(category)
    await db.commit()
    await db.refresh(category)
    log.info("Created category: %s (%s)", category.name, category.slug)
    return CategoryRead(
        id=category.id,
        name=category.name,
        slug=category.slug,
        description=category.description,
        device_type=category.device_type,
        market_weight=category.market_weight,
        created_at=category.created_at,
    )


@router.get("/{category_id}", response_model=CategoryRead)
async def get_category(
    category_id: int,
    db: AsyncSession = Depends(get_db),
) -> CategoryRead:
    stmt = select(Category).where(Category.id == category_id)
    result = await db.execute(stmt)
    category = result.scalar_one_or_none()
    if not category:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Category not found")
    return CategoryRead(
        id=category.id,
        name=category.name,
        slug=category.slug,
        description=category.description,
        device_type=category.device_type,
        market_weight=category.market_weight,
        created_at=category.created_at,
    )
