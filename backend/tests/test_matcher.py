"""Тесты сопоставления объявлений с моделями и извлечения атрибутов."""
import uuid

from app.services.matcher import extract_attributes, normalize_text


def test_extract_storage_and_ram_phone():
    attributes = extract_attributes("iPhone 13 128GB 8GB RAM", None)
    assert attributes["storage"] == "128GB"
    assert attributes["ram"] == "8GB"


def test_extract_storage_and_ram_laptop():
    attributes = extract_attributes("Ноутбук 16 ГБ ОЗУ, SSD 512 ГБ", None)
    assert attributes["ram"] == "16GB"
    assert attributes["storage"] == "512GB"


def test_extract_terabyte():
    assert extract_attributes("MacBook Pro 1 ТБ", None)["storage"] == "1TB"


def test_extract_color_and_defects():
    attributes = extract_attributes("iPhone 13 черный, разбит экран", None)
    assert attributes["color"] == "black"
    assert "разбит" in attributes["defect_mentions"]


def test_normalize_text():
    assert normalize_text("  iPhone 13, 128 ГБ! ") == "iphone 13 128 гб"


def _create_product(client, model: str, brand: str, storage: str, category_id: int | None = None) -> int:
    if category_id is None:
        response = client.post(
            "/api/v1/categories/",
            json={
                "name": "Смартфоны",
                "slug": f"cat-{uuid.uuid4().hex[:8]}",
                "device_type": "smartphone",
            },
        )
        category_id = response.json()["id"]

    response = client.post(
        "/api/v1/products/",
        params={
            "category_id": category_id,
            "name": f"{model} {storage}",
            "slug": f"p-{uuid.uuid4().hex[:8]}",
            "brand": brand,
            "model": model,
            "storage_capacity": storage,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _create_listing(client, title: str, price: float = 50000) -> dict:
    response = client.post(
        "/api/v1/listings/",
        json={
            "source": "manual",
            "external_id": uuid.uuid4().hex,
            "title": title,
            "price": price,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_auto_match_by_brand_model_and_storage(client):
    product_id = _create_product(client, "Pixel 9 Pro", "Google", "256GB")

    listing = _create_listing(client, "Google Pixel 9 Pro 256GB")

    assert listing["product_id"] == product_id
    assert listing["match_method"] == "auto"
    assert listing["match_confidence"] >= 0.55
    assert listing["attributes"]["storage"] == "256GB"


def test_model_only_match_for_distinctive_name(client):
    product_id = _create_product(client, "Pixel 8", "Google", "128GB")

    listing = _create_listing(client, "Pixel 8 128GB")

    assert listing["product_id"] == product_id
    assert listing["match_method"] == "auto"


def test_storage_mismatch_does_not_match(client):
    _create_product(client, "Pixel 7", "Google", "256GB")

    listing = _create_listing(client, "Google Pixel 7 128GB")

    assert listing["product_id"] is None
    assert listing["match_method"] in ("none", "ambiguous")


def test_unknown_model_stays_unmatched(client):
    listing = _create_listing(client, "Samsung Galaxy S99 Ultra 512GB")

    assert listing["product_id"] is None
    assert listing["attributes"]["storage"] == "512GB"


def test_unmatched_endpoint_and_manual_patch(client):
    matched_product = _create_product(client, "Pixel 6", "Google", "128GB")
    matched = _create_listing(client, "Google Pixel 6 128GB")
    assert matched["product_id"] == matched_product

    unmatched = _create_listing(client, "Загадочный девайс 777")

    response = client.get("/api/v1/listings/unmatched?per_page=200").json()
    ids = {item["id"] for item in response["data"]}
    assert unmatched["id"] in ids
    assert matched["id"] not in ids

    product = client.post(
        "/api/v1/products/",
        params={
            "category_id": client.get("/api/v1/categories/").json()["data"][0]["id"],
            "name": "Загадочный девайс",
            "slug": f"p-{uuid.uuid4().hex[:8]}",
            "brand": "NoName",
            "model": "Загадочный девайс",
        },
    ).json()

    patched = client.patch(
        f"/api/v1/listings/{unmatched['id']}",
        json={"product_id": product["id"]},
    )
    assert patched.status_code == 200, patched.text
    body = patched.json()
    assert body["product_id"] == product["id"]
    assert body["match_method"] == "manual"
    assert body["match_confidence"] == 1.0

    response = client.get("/api/v1/listings/unmatched?per_page=200").json()
    assert all(item["id"] != unmatched["id"] for item in response["data"])


def test_patch_price_writes_history(client):
    listing = _create_listing(client, "Загадочный девайс 888", price=10_000)

    response = client.patch(
        f"/api/v1/listings/{listing['id']}",
        json={"price": 9000},
    )
    assert response.status_code == 200
    assert response.json()["price"] == 9000

    trend = client.get(f"/api/v1/statistics/listings/{listing['id']}/trend").json()
    assert trend["count"] == 2
    assert trend["trend"] == "falling"
