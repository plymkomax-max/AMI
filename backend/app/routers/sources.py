"""Роутер: Источники данных."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.source import DataSource
from app.schemas.listing import DataSourceRead, DataSourceCreate
from app.logger import get_logger

log = get_logger("router.sources")

router = APIRouter(prefix="/api/v1/sources", tags=["sources"])


def _to_read(s: DataSource) -> DataSourceRead:
    return DataSourceRead(
        id=s.id,
        name=s.name,
        slug=s.slug,
        base_url=s.base_url,
        description=s.description,
        enabled=s.enabled,
        created_at=s.created_at,
    )


@router.get("/", response_model=list[DataSourceRead])
async def list_sources(db: AsyncSession = Depends(get_db)) -> list[DataSourceRead]:
    result = await db.execute(select(DataSource).order_by(DataSource.name))
    return [_to_read(s) for s in result.scalars().all()]


@router.post("/", response_model=DataSourceRead)
async def create_source(
    payload: DataSourceCreate,
    db: AsyncSession = Depends(get_db),
) -> DataSourceRead:
    # Check duplicate slug
    exists = await db.execute(select(DataSource).where(DataSource.slug == payload.slug))
    if exists.scalar_one_or_none():
        raise HTTPException(status.HTTP_400_BAD_REQUEST, detail="Source with this slug exists")

    source = DataSource(
        name=payload.name,
        slug=payload.slug,
        base_url=payload.base_url,
        description=payload.description,
        enabled=payload.enabled,
    )
    db.add(source)
    await db.commit()
    await db.refresh(source)
    log.info("Создан источник: %s", source.slug)
    return _to_read(source)


@router.get("/{source_id}", response_model=DataSourceRead)
async def get_source(
    source_id: int,
    db: AsyncSession = Depends(get_db),
) -> DataSourceRead:
    result = await db.execute(select(DataSource).where(DataSource.id == source_id))
    source = result.scalar_one_or_none()
    if not source:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Source not found")
    return _to_read(source)
