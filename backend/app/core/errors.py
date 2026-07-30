from typing import Any

from fastapi import HTTPException


class AppError(Exception):
    def __init__(
        self,
        message: str,
        status_code: int = 400,
        code: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        self.message = message
        self.status_code = status_code
        self.code = code or default_error_code(status_code)
        self.details = details
        super().__init__(message)


def default_error_code(status_code: int) -> str:
    """Map HTTP status classes to the stable API error codes used by clients."""
    if status_code == 400:
        return "VALIDATION_ERROR"
    if status_code == 401:
        return "AUTH_INVALID"
    if status_code == 403:
        return "FORBIDDEN"
    if status_code == 404:
        return "NOT_FOUND"
    if status_code == 409:
        return "CONFLICT"
    if status_code == 422:
        return "VALIDATION_ERROR"
    if status_code == 429:
        return "RATE_LIMITED"
    if status_code >= 500:
        return "INTERNAL_ERROR"
    return "ERROR"


def to_http_exception(exc: AppError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={
            "code": exc.code,
            "message": exc.message,
            "details": exc.details,
        },
    )
