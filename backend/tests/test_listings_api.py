"""Тесты API объявлений и связи с моделью товара."""
import uuid


def _create_category(client) -> int:
    slug = f"cat-{uuid.uuid4().hex[:8]}"
    response = client.post(
        "/api/v1/categories/",
        json={"name": "Смартфоны", "slug": slug, "device_type": "smartphone"},
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _create_product(client, category_id: int, model: str = "iPhone 13") -> int:
    slug = f"product-{uuid.uuid4().hex[:8]}"
    response = client.post(
        "/api/v1/products/",
        params={
            "category_id": category_id,
            "name": f"{model} 128GB",
            "slug": slug,
            "brand": "Apple",
            "model": model,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()["id"]


def _create_listing(
    client,
    price: float,
    product_id: int | None = None,
    source: str = "manual",
    title: str = "iPhone 13 128GB",
) -> dict:
    payload = {
        "source": source,
        "external_id": uuid.uuid4().hex,
        "title": title,
        "price": price,
        "condition": "good",
    }
    if product_id is not None:
        payload["product_id"] = product_id
    response = client.post("/api/v1/listings/", json=payload)
    assert response.status_code == 200, response.text
    return response.json()


def test_create_listing_with_product_link(client):
    category_id = _create_category(client)
    product_id = _create_product(client, category_id)

    listing = _create_listing(client, 50_000, product_id)
    assert listing["product_id"] == product_id

    stats = client.get(f"/api/v1/statistics/market?category_id={category_id}").json()
    assert stats["stats"]["count"] == 1
    assert stats["total_listings"] == 1


def test_listing_without_product_is_counted_separately(client):
    category_id = _create_category(client)
    _create_listing(client, 10_000, None, title="Неизвестный гаджет 4242")

    stats = client.get(f"/api/v1/statistics/market?category_id={category_id}").json()
    assert stats["stats"]["count"] == 0
    assert stats["unlinked_listings"] >= 1


def test_listing_with_unknown_product_is_rejected(client):
    response = client.post(
        "/api/v1/listings/",
        json={
            "source": "manual",
            "external_id": uuid.uuid4().hex,
            "title": "x",
            "price": 100,
            "product_id": 999_999,
        },
    )
    assert response.status_code == 400
    assert "не найден" in response.json()["detail"]


def test_listing_requires_price(client):
    response = client.post(
        "/api/v1/listings/",
        json={"source": "manual", "external_id": uuid.uuid4().hex, "title": "x"},
    )
    assert response.status_code == 422


def test_pagination_total_and_limit(client):
    category_id = _create_category(client)
    product_id = _create_product(client, category_id)
    for price in (10_000, 20_000, 30_000):
        _create_listing(client, price, product_id)

    response = client.get(
        f"/api/v1/listings/?product_id={product_id}&per_page=2&page=1"
    ).json()
    assert response["total"] == 3
    assert len(response["data"]) == 2

    too_large = client.get("/api/v1/listings/?per_page=100000")
    assert too_large.status_code == 422


def test_anomalies_need_minimum_sample(client):
    category_id = _create_category(client)
    product_id = _create_product(client, category_id)
    for price in (5_000, 48_000, 49_000, 50_000):
        _create_listing(client, price, product_id)

    response = client.get(
        f"/api/v1/statistics/anomalies?product_id={product_id}&min_sample=5"
    ).json()
    assert response["count"] == 0
    assert response["products_skipped_small_sample"] == 1

    _create_listing(client, 51_000, product_id)
    response = client.get(
        f"/api/v1/statistics/anomalies?product_id={product_id}&min_sample=5"
    ).json()
    assert response["count"] == 1
    assert response["anomalies"][0]["is_underpriced"] is True
    assert response["anomalies"][0]["price"] == 5_000


def test_anomalies_return_only_underpriced(client):
    category_id = _create_category(client)
    product_id = _create_product(client, category_id)
    for price in (5_000, 48_000, 49_000, 50_000, 51_000, 200_000):
        _create_listing(client, price, product_id)

    response = client.get(
        f"/api/v1/statistics/anomalies?product_id={product_id}&min_sample=5"
    ).json()
    assert all(item["is_underpriced"] for item in response["anomalies"])
    assert all(item["price"] != 200_000 for item in response["anomalies"])


def test_anomalies_do_not_mix_products(client):
    category_id = _create_category(client)
    cheap_product = _create_product(client, category_id, model="iPhone 13")
    expensive_product = _create_product(client, category_id, model="MacBook Pro")

    for price in (5_000, 48_000, 49_000, 50_000, 51_000):
        _create_listing(client, price, cheap_product)
    # Дорогая модель с маленькой выборкой не должна участвовать в сравнении
    for price in (150_000, 160_000):
        _create_listing(client, price, expensive_product)

    response = client.get(
        f"/api/v1/statistics/anomalies?category_id={category_id}&min_sample=5"
    ).json()
    # Дешёвая модель не должна «просвечивать» в выборку дорогой
    assert response["products_skipped_small_sample"] >= 1
    assert all(item["product_id"] == cheap_product for item in response["anomalies"])


def test_listing_history_written_on_price_change(client):
    category_id = _create_category(client)
    product_id = _create_product(client, category_id)
    external_id = uuid.uuid4().hex
    payload = {
        "source": "manual",
        "external_id": external_id,
        "title": "iPhone 13",
        "price": 50_000,
        "product_id": product_id,
    }
    first = client.post("/api/v1/listings/", json=payload).json()
    payload["price"] = 45_000
    client.post("/api/v1/listings/", json=payload)

    listing = client.get(f"/api/v1/listings/{first['id']}").json()
    assert listing["price"] == 45_000
    trend = client.get(f"/api/v1/statistics/listings/{first['id']}/trend").json()
    assert trend["count"] == 2
    assert trend["trend"] == "falling"
