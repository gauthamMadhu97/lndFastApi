from datetime import date
from typing import Annotated

from pydantic import Field, StringConstraints, field_validator, model_validator

from app.models.enums import AssetCategory, AssetStatus
from app.schemas.common import PageQuery, RequestModel, ResponseModel
from app.schemas.employee import EmployeeSummary

AssetTag = Annotated[str, StringConstraints(min_length=3, max_length=32, pattern=r"^[A-Za-z0-9-]+$")]
AssetName = Annotated[str, StringConstraints(min_length=1, max_length=120)]
SerialNumber = Annotated[str, StringConstraints(min_length=1, max_length=64)]


def _check_settable_status(value: AssetStatus | None) -> AssetStatus | None:
    # "assigned" only ever comes from POST /assets/{id}/assignments (BR3)
    if value == AssetStatus.ASSIGNED:
        raise ValueError("status 'assigned' can only be set by assigning the asset (BR3)")
    return value


def _upper(value: str | None) -> str | None:
    return value.upper() if value else value


class AssetCreate(RequestModel):
    asset_tag: AssetTag
    name: AssetName
    category: AssetCategory
    serial_number: SerialNumber
    purchase_date: date
    warranty_expiry: date
    status: AssetStatus = AssetStatus.AVAILABLE

    _tag_upper = field_validator("asset_tag")(_upper)
    _status_ok = field_validator("status")(_check_settable_status)

    @field_validator("purchase_date")
    @classmethod
    def purchase_not_in_future(cls, value: date) -> date:
        if value > date.today():
            raise ValueError("purchase_date cannot be in the future")
        return value

    @model_validator(mode="after")
    def warranty_after_purchase(self) -> "AssetCreate":
        if self.warranty_expiry <= self.purchase_date:
            raise ValueError("warranty_expiry must be after purchase_date (BR6)")
        return self


class AssetUpdate(RequestModel):
    """Partial update. BR6 is re-checked in the service against the stored dates."""

    asset_tag: AssetTag | None = None
    name: AssetName | None = None
    category: AssetCategory | None = None
    serial_number: SerialNumber | None = None
    purchase_date: date | None = None
    warranty_expiry: date | None = None
    status: AssetStatus | None = None

    _tag_upper = field_validator("asset_tag")(_upper)
    _status_ok = field_validator("status")(_check_settable_status)

    @model_validator(mode="after")
    def warranty_after_purchase(self) -> "AssetUpdate":
        if self.purchase_date and self.warranty_expiry and self.warranty_expiry <= self.purchase_date:
            raise ValueError("warranty_expiry must be after purchase_date (BR6)")
        return self


class AssetListQuery(PageQuery):
    status: AssetStatus | None = None
    category: AssetCategory | None = None
    q: str | None = Field(
        default=None,
        min_length=1,
        max_length=100,
        description="Matches part of the name or asset tag, case-insensitive",
    )


class AssetRead(ResponseModel):
    id: int
    asset_tag: str
    name: str
    category: AssetCategory
    serial_number: str
    purchase_date: date
    warranty_expiry: date
    status: AssetStatus


class CurrentHolder(EmployeeSummary):
    assigned_on: date


class AssetDetail(AssetRead):
    current_holder: CurrentHolder | None = None
