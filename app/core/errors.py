import logging
from typing import Any

from fastapi import FastAPI, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.core.context import current_request_id

logger = logging.getLogger("assetdesk.errors")

# For rule breaks that are really about bad input values (e.g. a return date before the assignment)
UNPROCESSABLE = status.HTTP_422_UNPROCESSABLE_CONTENT


class AppError(Exception):
    """Base for errors the service raises on purpose. Services raise these, never HTTPException."""

    status_code: int = status.HTTP_400_BAD_REQUEST
    code: str = "BAD_REQUEST"

    def __init__(
        self,
        message: str,
        *,
        code: str | None = None,
        rule: str | None = None,
        status_code: int | None = None,
        headers: dict[str, str] | None = None,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.rule = rule
        self.headers = headers
        if code:
            self.code = code
        if status_code:
            self.status_code = status_code


class NotFoundError(AppError):
    status_code = status.HTTP_404_NOT_FOUND
    code = "NOT_FOUND"


class ConflictError(AppError):
    status_code = status.HTTP_409_CONFLICT
    code = "CONFLICT"


class BusinessRuleError(AppError):
    """A request that is well formed but breaks one of BR1-BR8."""

    status_code = status.HTTP_409_CONFLICT

    def __init__(self, rule: str, code: str, message: str, *, status_code: int | None = None) -> None:
        super().__init__(message, code=code, rule=rule, status_code=status_code)


class AuthenticationError(AppError):
    status_code = status.HTTP_401_UNAUTHORIZED
    code = "NOT_AUTHENTICATED"

    def __init__(self, message: str = "Not authenticated") -> None:
        super().__init__(message, headers={"WWW-Authenticate": "Bearer"})


class PermissionDeniedError(AppError):
    status_code = status.HTTP_403_FORBIDDEN
    code = "FORBIDDEN"


def error_body(code: str, message: str, rule: str | None = None, details: Any = None) -> dict[str, Any]:
    error: dict[str, Any] = {"code": code, "message": message, "request_id": current_request_id()}
    if rule:
        error["rule"] = rule
    if details is not None:
        error["details"] = details
    return {"error": error}


_HTTP_CODES = {
    400: "BAD_REQUEST",
    401: "NOT_AUTHENTICATED",
    403: "FORBIDDEN",
    404: "NOT_FOUND",
    405: "METHOD_NOT_ALLOWED",
    409: "CONFLICT",
}


async def _app_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, AppError)
    return JSONResponse(
        error_body(exc.code, exc.message, exc.rule),
        status_code=exc.status_code,
        headers=exc.headers,
    )


async def _validation_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, RequestValidationError)
    # Only copy loc/msg/type. The raw errors can hold exception objects in ctx,
    # and "input" could echo back a password.
    details = [
        {"loc": list(err.get("loc", ())), "msg": err.get("msg"), "type": err.get("type")}
        for err in exc.errors()
    ]
    return JSONResponse(
        error_body("VALIDATION_ERROR", "Request failed validation", details=details),
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
    )


async def _http_error_handler(_: Request, exc: Exception) -> JSONResponse:
    assert isinstance(exc, StarletteHTTPException)
    code = _HTTP_CODES.get(exc.status_code, "HTTP_ERROR")
    return JSONResponse(
        error_body(code, str(exc.detail)),
        status_code=exc.status_code,
        headers=getattr(exc, "headers", None),
    )


def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(AppError, _app_error_handler)
    app.add_exception_handler(RequestValidationError, _validation_handler)
    app.add_exception_handler(StarletteHTTPException, _http_error_handler)
