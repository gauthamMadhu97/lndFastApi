from datetime import date

from pydantic import Field, field_validator

from app.schemas.common import RequestModel, ResponseModel


def _not_future(value: date) -> date:
    if value > date.today():
        raise ValueError("date cannot be in the future")
    return value


class AssignmentCreate(RequestModel):
    employee_id: int = Field(ge=1)
    assigned_on: date = Field(default_factory=date.today)

    _check_date = field_validator("assigned_on")(_not_future)


class ReturnCreate(RequestModel):
    returned_on: date = Field(default_factory=date.today)

    _check_date = field_validator("returned_on")(_not_future)


class AssignmentRead(ResponseModel):
    id: int
    asset_id: int
    employee_id: int | None = Field(description="null if the employee has since been removed")
    employee_name: str
    employee_email: str
    assigned_on: date
    returned_on: date | None
