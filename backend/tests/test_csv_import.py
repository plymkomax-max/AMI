"""Тесты импорта CSV через API: кодировки, разделители, ошибки строк."""
import uuid


def _import(client, content: bytes | str, source: str = "csv") -> dict:
    if isinstance(content, str):
        content = content.encode("utf-8")
    response = client.post(
        "/api/v1/listings/import/csv",
        files={"file": ("listings.csv", content, "text/csv")},
        params={"source": source},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_import_semicolon_cp1251_with_date(client):
    content = (
        "external_id;title;price;city;published_at\n"
        "x-1;Телефон Samsung;15 000;Москва;15.01.2026\n"
    ).encode("cp1251")
    result = _import(client, content, source=f"csv-{uuid.uuid4().hex[:6]}")
    assert result["imported"] == 1
    assert result["skipped"] == 0


def test_bad_row_does_not_break_request(client):
    content = (
        "external_id,title,price\n"
        "bad-1,Без цены,не число\n"
        f"good-{uuid.uuid4().hex[:6]},Нормальная цена,1000\n"
    )
    result = _import(client, content, source=f"csv-{uuid.uuid4().hex[:6]}")
    assert result["imported"] == 1
    assert result["skipped"] == 1
    assert result["errors"]


def test_reimport_updates_instead_of_duplicating(client):
    source = f"csv-{uuid.uuid4().hex[:6]}"
    external_id = f"same-{uuid.uuid4().hex[:6]}"

    first = _import(
        client,
        f"external_id,title,price\n{external_id},Товар,30000\n",
        source=source,
    )
    assert first["imported"] == 1

    second = _import(
        client,
        f"external_id,title,price\n{external_id},Товар,27000\n",
        source=source,
    )
    assert second["updated"] == 1
    assert second["imported"] == 0

    listing_id = client.get(f"/api/v1/listings/?source={source}").json()["data"][0]["id"]
    trend = client.get(f"/api/v1/statistics/listings/{listing_id}/trend").json()
    assert trend["count"] == 2


def test_import_with_product_id_column(client):
    slug = f"cat-{uuid.uuid4().hex[:8]}"
    category_id = client.post(
        "/api/v1/categories/",
        json={"name": "Смартфоны", "slug": slug, "device_type": "smartphone"},
    ).json()["id"]
    product_id = client.post(
        "/api/v1/products/",
        params={
            "category_id": category_id,
            "name": "iPhone 13 128GB",
            "slug": f"p-{uuid.uuid4().hex[:8]}",
            "brand": "Apple",
            "model": "iPhone 13",
        },
    ).json()["id"]

    source = f"csv-{uuid.uuid4().hex[:6]}"
    result = _import(
        client,
        f"external_id,title,price,product_id\n"
        f"p-{uuid.uuid4().hex[:6]},iPhone 13,50000,{product_id}\n",
        source=source,
    )
    assert result["imported"] == 1

    listing = client.get(f"/api/v1/listings/?source={source}").json()["data"][0]
    assert listing["product_id"] == product_id


def test_empty_file_is_rejected_gracefully(client):
    response = client.post(
        "/api/v1/listings/import/csv",
        files={"file": ("empty.csv", b"", "text/csv")},
        params={"source": "csv"},
    )
    assert response.status_code == 200
    assert response.json()["total_rows"] == 0
