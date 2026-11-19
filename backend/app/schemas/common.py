"""Pydantic-схемы для API."""
from __future__ import annotations

import datetime as dt
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from app.models.category import ProductDeviceType
from app.models.listing import ListingCondition
from app.models.feedback import FeedbackType
from app.config import settings


# ========== Base ==========

class AMIResponse(BaseModel):
    """Базовый ответ API."""
    model_config = ConfigDict(json_schema_extra={"examples": [{"status": "ok"}]})
    status: str = "ok"
    detail: str | None = None


# ========== Categories ==========

class CategoryRead(BaseModel):
    id: int
    name: str
    slug: str
    description: str | None = None
    device_type: ProductDeviceType
    market_weight: float
    created_at: dt.datetime


class CategoryCreate(BaseModel):
    name: str = Field(..., max_length=128)
    slug: str = Field(..., max_length=64)
    description: str | None = None
    device_type: ProductDeviceType
    market_weight: float = 1.0


class CategoryList(AMIResponse):
    data: list[CategoryRead]
    total: int


# ========== Products ==========

class ProductRead(BaseModel):
    id: int
    category_id: int
    name: str
    slug: str
    brand: str
    model: str
    generation: str | None = None
    model_year: int | None = None
    storage_capacity: str | None = None
    ram_capacity: str | None = None
    display_size: str | None = None
    cpu: str | None = None
    gpu: str | None = None
    display_tech: str | None = None
    avg_price: float | None = None
    listing_count: int = 0
    specs: dict[str, Any] = {}
    attributes: dict[str, str] = {}


class ProductCreate(BaseModel):
    category_id: int
    name: str = Field(..., max_length=256)
    slug: str = Field(..., max_length=128)
    brand: str = Field(..., max_length=64)
    model: str = Field(..., max_length=128)
    generation: str | None = Field(None, max_length=64)
    model_year: int | None = None
    storage_capacity: str | None = Field(None, max_length=16)
    ram_capacity: str | None = Field(None, max_length=16)
    display_size: str | None = Field(None, max_length=8)
    cpu: str | None = Field(None, max_length=128)
    gpu: str | None = Field(None, max_length=128)
    display_tech: str | None = Field(None, max_length=32)
    specs: dict[str, Any] = {}
    attributes: dict[str, str] = {}


# ========== Listings ==========

class ListingRead(BaseModel):
    id: str
    source: str
    external_id: str
    url: str | None = None
    product_id: int | None = None
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
    expired_at: dt.datetime | None = None
    view_count: int | None = None
    fav_count: int | None = None
    is_archived: bool = False
    archive_reason: str | None = None
    weight: float | None = None
    created_at: dt.datetime
    updated_at: dt.datetime


class ListingCreate(BaseModel):
    source: str = Field(..., max_length=32)
    external_id: str = Field(..., max_length=128)
    url: str | None = Field(None, max_length=512)
    product_id: int | None = None
    title: str = Field(..., max_length=512)
    description: str | None = None
    price: float
    currency: str = "RUB"
    condition: ListingCondition = ListingCondition.GOOD
    usage_time: str | None = Field(None, max_length=128)
    includes: list[str] = []
    defects: list[str] = []
    city: str | None = Field(None, max_length=64)
    region: str | None = Field(None, max_length=128)
    seller_type: str | None = Field(None, max_length=32)
    published_at: dt.datetime | None = None
    expired_at: dt.datetime | None = None
    view_count: int | None = None
    fav_count: int | None = None


# ========== Health / Info ==========

class HealthResponse(AMIResponse):
    data: dict[str, Any] = {}


class SystemInfo(AMIResponse):
    app: str = settings.app_name
    version: str = settings.app_version
    debug: bool = settings.debug
    database_url: str = "***"  # hidden
    python_version: str = ""
