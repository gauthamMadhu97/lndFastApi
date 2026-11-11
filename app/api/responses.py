"""Shared `responses=` entries so the docs show the error shape for each status."""

from typing import Any

from app.schemas.common import ErrorResponse

_DESCRIPTIONS = {
    401: "Missing, invalid or expired token",
    403: "Signed in, but the role doesn't allow this",
    404: "Record not found",
    409: "Breaks a business rule (see error.rule) or a uniqueness rule",
    422: "Request failed validation",
}


def errors(*codes: int) -> dict[int | str, dict[str, Any]]:
    return {code: {"model": ErrorResponse, "description": _DESCRIPTIONS[code]} for code in codes}
