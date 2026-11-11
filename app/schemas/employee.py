from typing import Annotated

from pydantic import EmailStr, Field, StringConstraints, field_validator

from app.schemas.common import PageQuery, RequestModel, ResponseModel

FullName = Annotated[str, StringConstraints(min_length=1, max_length=120)]
Department = Annotated[str, StringConstraints(min_length=1, max_length=80)]


def _lower(value: str | None) -> str | None:
    return value.lower() if value else value


class EmployeeCreate(RequestModel):
    full_name: FullName
    email: EmailStr = Field(max_length=254)
    department: Department
    is_active: bool = True

    _normalise_email = field_validator("email")(_lower)


class EmployeeUpdate(RequestModel):
    full_name: FullName | None = None
    email: EmailStr | None = Field(default=None, max_length=254)
    department: Department | None = None
    is_active: bool | None = None

    _normalise_email = field_validator("email")(_lower)


class EmployeeListQuery(PageQuery):
    active: bool | None = Field(default=None, description="true = only active employees")


class EmployeeRead(ResponseModel):
    id: int
    full_name: str
    email: str
    department: str
    is_active: bool


class EmployeeSummary(ResponseModel):
    id: int
    full_name: str
    email: str
