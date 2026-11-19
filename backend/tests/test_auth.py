"""Тесты проверки API-ключа."""
from fastapi import HTTPException
import pytest

from app.config import settings
from app.security import verify_api_key


def test_open_when_key_not_configured(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "")
    verify_api_key(None)  # не должно бросить


def test_rejects_missing_key(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret")
    with pytest.raises(HTTPException) as exc:
        verify_api_key(None)
    assert exc.value.status_code == 401


def test_rejects_wrong_key(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret")
    with pytest.raises(HTTPException):
        verify_api_key("wrong")


def test_accepts_correct_key(monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret")
    verify_api_key("secret")


def test_endpoint_protected_when_key_configured(client, monkeypatch):
    monkeypatch.setattr(settings, "api_key", "secret")

    assert client.get("/api/v1/categories/").status_code == 401
    assert (
        client.get("/api/v1/categories/", headers={"X-API-Key": "wrong"}).status_code == 401
    )
    assert (
        client.get("/api/v1/categories/", headers={"X-API-Key": "secret"}).status_code == 200
    )
    # Публичные эндпоинты остаются доступны
    assert client.get("/api/v1/health").status_code == 200
