"""seed reference data: категории и источники

Revision ID: a1b2c3d4e5f6
Revises: 649ff3276cb1
Create Date: 2026-11-18 13:20:00

Начальный справочник: 6 категорий из ТЗ и базовые источники данных.
Миграция идемпотентна: повторный запуск не создаёт дубликатов.
"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "a1b2c3d4e5f6"
down_revision: Union[str, Sequence[str], None] = "649ff3276cb1"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


CATEGORIES = [
    ("Смартфоны", "smartphones", "SMARTPHONE", "Телефоны и смартфоны"),
    ("Ноутбуки", "notebooks", "NOTEBOOK", "Ноутбуки и ультрабуки"),
    ("Компьютеры и комплектующие", "computers", "DESKTOP", "ПК, комплектующие, периферия"),
    ("Планшеты", "tablets", "TABLET", "Планшеты и электронные книги"),
    ("Бытовая электроника", "electronics", "APPLIANCE", "Аудио, ТВ, мелкая техника"),
    ("Игровые консоли", "consoles", "CONSOLE", "PlayStation, Xbox, Nintendo"),
]

SOURCES = [
    ("Ручное добавление", "manual", None, "Объявления, добавленные через API вручную", True),
    ("CSV / Excel", "csv", None, "Импорт выгрузок из файлов", True),
    (
        "Avito API",
        "avito_api",
        "https://api.avito.ru",
        "Официальный API; адаптер будет добавлен на этапе Data Foundation",
        False,
    ),
]


def upgrade() -> None:
    bind = op.get_bind()

    existing_categories = set(
        bind.execute(sa.text("SELECT slug FROM categories")).scalars().all()
    )
    for name, slug, device_type, description in CATEGORIES:
        if slug in existing_categories:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO categories "
                "(name, slug, description, device_type, market_weight, created_at, updated_at) "
                "VALUES (:name, :slug, :description, :device_type, 1.0, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {
                "name": name,
                "slug": slug,
                "description": description,
                "device_type": device_type,
            },
        )

    existing_sources = set(
        bind.execute(sa.text("SELECT slug FROM data_sources")).scalars().all()
    )
    for name, slug, base_url, description, enabled in SOURCES:
        if slug in existing_sources:
            continue
        bind.execute(
            sa.text(
                "INSERT INTO data_sources "
                "(name, slug, base_url, description, enabled, created_at, updated_at) "
                "VALUES (:name, :slug, :base_url, :description, :enabled, "
                "CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {
                "name": name,
                "slug": slug,
                "base_url": base_url,
                "description": description,
                "enabled": enabled,
            },
        )


def downgrade() -> None:
    bind = op.get_bind()
    for _, slug, _, _ in CATEGORIES:
        bind.execute(
            sa.text(
                "DELETE FROM categories "
                "WHERE slug = :slug "
                "AND NOT EXISTS (SELECT 1 FROM products WHERE products.category_id = categories.id)"
            ),
            {"slug": slug},
        )
    for _, slug, _, _, _ in SOURCES:
        bind.execute(
            sa.text(
                "DELETE FROM data_sources "
                "WHERE slug = :slug "
                "AND NOT EXISTS (SELECT 1 FROM listings WHERE listings.source_obj_id = data_sources.id)"
            ),
            {"slug": slug},
        )
