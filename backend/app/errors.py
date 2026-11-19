"""Ошибки и исключения приложения.

Пока используется точечно; базовый класс нужен для будущих обработчиков.
"""

from typing import Any, Optional

from pydantic import BaseModel


class AMIError(Exception):
    """Базовое исключение AMI."""

    detail: str

    def __init__(self, detail: str = "", **extras: Any):
        self.detail = detail
        self.extras = extras
        super().__init__(detail)


class ConfigError(AMIError):
    pass


class DatabaseError(AMIError):
    pass


class DataSourceError(AMIError):
    pass


class ValidationError(AMIError):
    pass


class RateLimitError(AMIError):
    pass


class ExternalServiceError(AMIError):
    pass


class NotFoundError(AMIError):
    pass


class ForbiddenError(AMIError):
    pass


class ErrorDetail(BaseModel):
    """Стандартный формат ошибки для API."""

    type: str
    detail: str
    code: Optional[str] = None
    trace_id: Optional[str] = None


def http_400(detail: str, **ex: Any):
    from fastapi import HTTPException, status

    return HTTPException(
        status.HTTP_400_BAD_REQUEST,
        detail=ErrorDetail(type="validation_error", detail=detail, **ex).model_dump(
            exclude_unset=True
        ),
    )


def http_401(detail: str = "Authentication required", **ex: Any):
    from fastapi import HTTPException, status

    return HTTPException(
        status.HTTP_401_UNAUTHORIZED,
        detail=ErrorDetail(type="authentication_error", detail=detail, **ex).model_dump(),
    )


def http_403(detail: str = "Access denied", **ex: Any):
    from fastapi import HTTPException, status

    return HTTPException(
        status.HTTP_403_FORBIDDEN,
        detail=ErrorDetail(type="forbidden_error", detail=detail, **ex).model_dump(),
    )


def http_404(detail: str = "Not found", **ex: Any):
    from fastapi import HTTPException, status

    return HTTPException(
        status.HTTP_404_NOT_FOUND,
        detail=ErrorDetail(type="not_found", detail=detail, **ex).model_dump(),
    )


def http_429(detail: str = "Too many requests", **ex: Any):
    from fastapi import HTTPException, status

    return HTTPException(
        status.HTTP_429_TOO_MANY_REQUESTS,
        detail=ErrorDetail(type="rate_limit", detail=detail, **ex).model_dump(),
    )


def http_500(detail: str = "Internal server error", **ex: Any):
    from fastapi import HTTPException, status

    return HTTPException(
        status.HTTP_500_INTERNAL_SERVER_ERROR,
        detail=ErrorDetail(type="server_error", detail=detail, **ex).model_dump(),
    )
