from datetime import date
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints, field_validator

from app.schemas.common import RequestModel

Tag = Annotated[str, StringConstraints(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9-]+$")]


class WarrantyCheckRequest(RequestModel):
    asset_tags: list[Tag] = Field(min_length=1, max_length=50)

    @field_validator("asset_tags")
    @classmethod
    def unique_tags(cls, tags: list[str]) -> list[str]:
        upper = [t.upper() for t in tags]
        if len(set(upper)) != len(upper):
            raise ValueError("asset_tags contains duplicates")
        return upper


class WarrantyResult(BaseModel):
    asset_tag: str
    ok: bool
    in_warranty: bool | None = None
    warranty_expiry: date | None = None
    days_remaining: int | None = None
    error: str | None = None


class WarrantyCheckResponse(BaseModel):
    results: list[WarrantyResult]
    succeeded: int
    failed: int
