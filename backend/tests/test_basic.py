"""Базовые тесты AMI."""
import uuid

from app.config import settings


def test_health(client):
    """Тест базового health endpoint."""
    resp = client.get("/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert "version" in data


def test_api_health(client):
    """Тест /api/v1/health."""
    resp = client.get("/api/v1/health")
    assert resp.status_code == 200
    data = resp.json()
    assert data["status"] == "ok"
    assert data["detail"] == "Service is running"
    assert data["data"]["database"] in ("sqlite", "postgresql")
    assert data["data"]["db_status"] == "ok"


def test_info(client):
    """Тест /api/v1/info."""
    resp = client.get("/api/v1/info")
    assert resp.status_code == 200
    data = resp.json()
    assert data["app"] == settings.app_name
    assert "version" in data


def test_list_categories_empty(client):
    """Список категорий возвращает структуру даже при пустой БД."""
    resp = client.get("/api/v1/categories/")
    assert resp.status_code == 200
    data = resp.json()
    assert data["total"] >= 0
    assert isinstance(data["data"], list)


def test_create_and_get_category(client):
    """Создание и чтение категории."""
    slug = f"test-cat-{uuid.uuid4().hex[:8]}"
    payload = {
        "name": "TestCat",
        "slug": slug,
        "device_type": "smartphone",
    }
    resp = client.post("/api/v1/categories/", json=payload)
    assert resp.status_code == 200
    created = resp.json()
    assert created["name"] == "TestCat"
    assert created["slug"] == slug

    cat_id = created["id"]
    resp = client.get(f"/api/v1/categories/{cat_id}")
    assert resp.status_code == 200
    got = resp.json()
    assert got["name"] == "TestCat"


def test_create_category_missing_slug(client):
    """Невалидный запрос без slug."""
    payload = {"name": "NoSlug", "device_type": "smartphone"}
    resp = client.post("/api/v1/categories/", json=payload)
    assert resp.status_code == 422
