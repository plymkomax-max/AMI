"""Роутер: Товары (модели устройств)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.product import Product
from app.models.category import Category
from app.logger import get_logger

log = get_logger("router.products")

router = APIRouter(prefix="/api/v1/products", tags=["products"])


@router.get("/")
async def list_products(
    db: AsyncSession = Depends(get_db),
    category_id: int | None = None,
    brand: str | None = None,
    search: str | None = None,
    page: int = 1,
    per_page: int = 50,
) -> dict:
    page = max(1, page)
    per_page = min(max(1, per_page), 200)

    conditions = []
    if category_id:
        conditions.append(Product.category_id == category_id)
    if brand:
        conditions.append(Product.brand.ilike(f"%{brand}%"))
    if search:
        conditions.append(
            Product.name.ilike(f"%{search}%") | Product.model.ilike(f"%{search}%")
        )

    stmt = (
        select(Product)
        .where(*conditions)
        .order_by(Product.name)
        .offset((page - 1) * per_page)
        .limit(per_page)
    )
    count_stmt = select(func.count(Product.id)).where(*conditions)

    result = await db.execute(stmt)
    products = result.scalars().all()
    total = int((await db.scalar(count_stmt)) or 0)
    return {
        "status": "ok",
        "total": total,
        "page": page,
        "per_page": per_page,
        "data": [
            {
                "id": p.id,
                "category_id": p.category_id,
                "name": p.name,
                "slug": p.slug,
                "brand": p.brand,
                "model": p.model,
                "generation": p.generation,
                "model_year": p.model_year,
                "storage_capacity": p.storage_capacity,
                "ram_capacity": p.ram_capacity,
                "cpu": p.cpu,
                "gpu": p.gpu,
                "avg_price": p.avg_price,
                "listing_count": p.listing_count,
            }
            for p in products
        ],
    }


@router.post("/")
async def create_product(
    db: AsyncSession = Depends(get_db),
    category_id: int = None,
    name: str = None,
    slug: str = None,
    brand: str = None,
    model: str = None,
    generation: str | None = None,
    model_year: int | None = None,
    storage_capacity: str | None = None,
    ram_capacity: str | None = None,
    cpu: str | None = None,
    gpu: str | None = None,
) -> dict:
    # Валидация
    if not category_id or not name or not slug or not brand or not model:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail="Required: category_id, name, slug, brand, model",
        )

    # Проверка категории
    cat = (await db.execute(select(Category).where(Category.id == category_id))).scalar_one_or_none()
    if not cat:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Category not found")

    # Дубликат slug
    dup = (await db.execute(select(Product).where(Product.slug == slug))).scalar_one_or_none()
    if dup:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Product slug exists")

    product = Product(
        category_id=category_id,
        name=name,
        slug=slug,
        brand=brand,
        model=model,
        generation=generation,
        model_year=model_year,
        storage_capacity=storage_capacity,
        ram_capacity=ram_capacity,
        cpu=cpu,
        gpu=gpu,
    )
    db.add(product)
    await db.commit()
    await db.refresh(product)
    log.info("Создан товар: %s", product.slug)
    return {
        "id": product.id,
        "category_id": product.category_id,
        "name": product.name,
        "slug": product.slug,
        "brand": product.brand,
        "model": product.model,
    }


@router.get("/{product_id}")
async def get_product(
    product_id: int,
    db: AsyncSession = Depends(get_db),
) -> dict:
    result = await db.execute(select(Product).where(Product.id == product_id))
    p = result.scalar_one_or_none()
    if not p:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Product not found")
    return {
        "id": p.id,
        "category_id": p.category_id,
        "name": p.name,
        "slug": p.slug,
        "brand": p.brand,
        "model": p.model,
        "generation": p.generation,
        "model_year": p.model_year,
        "storage_capacity": p.storage_capacity,
        "ram_capacity": p.ram_capacity,
        "cpu": p.cpu,
        "gpu": p.gpu,
        "avg_price": p.avg_price,
        "listing_count": p.listing_count,
    }
