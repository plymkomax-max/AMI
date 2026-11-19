"""Тесты импорта Excel (.xlsx)."""
from __future__ import annotations

import datetime as dt
import io
import uuid

import pytest

openpyxl = pytest.importorskip("openpyxl")


def _workbook_bytes(rows: list[list[object]]) -> bytes:
    workbook = openpyxl.Workbook()
    sheet = workbook.active
    for row in rows:
        sheet.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def test_import_xlsx_with_date_and_numbers(client):
    content = _workbook_bytes(
        [
            ["external_id", "title", "price", "city", "published_at"],
            ["xlsx-1", "iPhone 13 128GB", 45000, "Москва", dt.datetime(2026, 1, 15)],
        ]
    )
    source = f"excel-{uuid.uuid4().hex[:6]}"
    response = client.post(
        "/api/v1/listings/import/excel",
        files={
            "file": (
                "listings.xlsx",
                content,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            )
        },
        params={"source": source},
    )
    assert response.status_code == 200, response.text
    result = response.json()
    assert result["imported"] == 1
    assert result["skipped"] == 0

    listing = client.get(f"/api/v1/listings/?source={source}").json()["data"][0]
    assert listing["price"] == 45000.0
    assert listing["attributes"]["storage"] == "128GB"
    assert listing["published_at"].startswith("2026-01-15")


def test_import_xlsx_russian_headers(client):
    content = _workbook_bytes(
        [
            ["Название", "Цена", "Город"],
            ["Samsung Galaxy S21 256GB", "30 000", "СПб"],
        ]
    )
    source = f"excel-{uuid.uuid4().hex[:6]}"
    result = client.post(
        "/api/v1/listings/import/excel",
        files={"file": ("listings.xlsx", content, "application/octet-stream")},
        params={"source": source},
    ).json()
    assert result["imported"] == 1

    listing = client.get(f"/api/v1/listings/?source={source}").json()["data"][0]
    assert listing["title"] == "Samsung Galaxy S21 256GB"
    assert listing["price"] == 30000.0
    assert listing["city"] == "СПб"
