from typing import Any

from fastapi import HTTPException


# Defines the app error project abstraction; the application layers use it as shared infrastructure.
class AppError(Exception):
    # Initializes a app error; the application layers use it as shared infrastructure.
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


# Implements the default error code operation; the application layers use it as shared infrastructure.
def default_error_code(status_code: int) -> str:
    # Return early when `status_code == 400` because the remaining work is not applicable.
    if status_code == 400:
        return "VALIDATION_ERROR"
    # Return early when `status_code == 401` because the remaining work is not applicable.
    if status_code == 401:
        return "AUTH_INVALID"
    # Return early when `status_code == 403` because the remaining work is not applicable.
    if status_code == 403:
        return "FORBIDDEN"
    # Return early when `status_code == 404` because the remaining work is not applicable.
    if status_code == 404:
        return "NOT_FOUND"
    # Return early when `status_code == 409` because the remaining work is not applicable.
    if status_code == 409:
        return "CONFLICT"
    # Return early when `status_code == 422` because the remaining work is not applicable.
    if status_code == 422:
        return "VALIDATION_ERROR"
    # Return early when `status_code == 429` because the remaining work is not applicable.
    if status_code == 429:
        return "RATE_LIMITED"
    # Return early when `status_code >= 500` because the remaining work is not applicable.
    if status_code >= 500:
        return "INTERNAL_ERROR"
    return "ERROR"


# Converts http exception; the application layers use it as shared infrastructure.
def to_http_exception(exc: AppError) -> HTTPException:
    return HTTPException(
        status_code=exc.status_code,
        detail={
            "code": exc.code,
            "message": exc.message,
            "details": exc.details,
        },
    )
