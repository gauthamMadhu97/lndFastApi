from typing import Any, Generic, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class RequestModel(BaseModel):
    """Base for anything a client sends: trims strings and rejects unknown fields."""

    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class ResponseModel(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class PageQuery(RequestModel):
    page: int = Field(default=1, ge=1, description="Page number, starting at 1")
    size: int = Field(default=20, ge=1, le=100, description="Items per page (max 100)")


class Page(BaseModel, Generic[T]):
    items: list[T]
    total: int = Field(description="Number of records matching the query, across all pages")
    page: int
    size: int


class ErrorDetail(BaseModel):
    code: str = Field(examples=["ASSET_NOT_AVAILABLE"])
    message: str
    rule: str | None = Field(default=None, description="Business rule that was broken, e.g. BR2")
    request_id: str | None = None
    details: list[dict[str, Any]] | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
