"""Pydantic-схемы для объявлений и источников данных."""
from __future__ import annotations

import datetime as dt
from typing import Any, Literal

from pydantic import BaseModel, Field

from app.models.listing import ListingCondition


# ========== Listings ==========

class ListingCreate(BaseModel):
    source: str = Field(..., max_length=32, description="Источник: avito, csv, manual...")
    external_id: str = Field(..., max_length=128, description="ID объявления у источника")
    url: str | None = Field(None, max_length=512)
    product_id: int | None = Field(
        None, description="ID модели товара (связь с products.id)"
    )
    title: str = Field(..., max_length=512)
    description: str | None = None
    price: float = Field(..., gt=0, description="Цена в рублях")
    currency: str = "RUB"
    condition: ListingCondition = ListingCondition.GOOD
    usage_time: str | None = Field(None, max_length=128)
    includes: list[str] = []
    defects: list[str] = []
    city: str | None = Field(None, max_length=64)
    region: str | None = Field(None, max_length=128)
    seller_type: str | None = Field(None, max_length=32)
    published_at: dt.datetime | None = None
    view_count: int | None = None
    fav_count: int | None = None
    attributes: dict[str, Any] = {}


class ListingUpdate(BaseModel):
    product_id: int | None = None
    title: str | None = Field(None, max_length=512)
    description: str | None = None
    price: float | None = Field(None, gt=0)
    condition: ListingCondition | None = None
    usage_time: str | None = None
    includes: list[str] | None = None
    defects: list[str] | None = None
    city: str | None = None
    region: str | None = None
    seller_type: str | None = None
    published_at: dt.datetime | None = None
    view_count: int | None = None
    fav_count: int | None = None
    attributes: dict[str, Any] | None = None


class ListingRead(BaseModel):
    id: str
    source: str
    external_id: str
    url: str | None = None
    product_id: int | None = None
    match_confidence: float | None = None
    match_method: str | None = None
    attributes: dict[str, Any] = {}
    title: str
    description: str | None = None
    price: float
    currency: str = "RUB"
    condition: ListingCondition
    usage_time: str | None = None
    includes: list[str] = []
    defects: list[str] = []
    city: str | None = None
    region: str | None = None
    seller_type: str | None = None
    published_at: dt.datetime | None = None
    view_count: int | None = None
    fav_count: int | None = None
    is_archived: bool = False
    archive_reason: str | None = None
    weight: float | None = None
    created_at: dt.datetime
    updated_at: dt.datetime


class ListingList(BaseModel):
    status: str = "ok"
    data: list[ListingRead]
    total: int
    page: int = 1
    per_page: int = 50


class ListingFilter(BaseModel):
    category_id: int | None = None
    product_id: int | None = None
    source: str | None = None
    condition: ListingCondition | None = None
    city: str | None = None
    min_price: float | None = None
    max_price: float | None = None
    is_archived: bool | None = False
    page: int = 1
    per_page: int = 50


class ImportResult(BaseModel):
    status: str = "ok"
    total_rows: int = 0
    imported: int = 0
    updated: int = 0
    skipped: int = 0
    errors: list[str] = []


# ========== Data Sources ==========

class DataSourceRead(BaseModel):
    id: int
    name: str
    slug: str
    base_url: str | None = None
    description: str | None = None
    enabled: bool = True
    created_at: dt.datetime


class DataSourceCreate(BaseModel):
    name: str = Field(..., max_length=128)
    slug: str = Field(..., max_length=32)
    base_url: str | None = Field(None, max_length=512)
    description: str | None = None
    enabled: bool = True
