from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DbSession, get_current_user, require_admin
from app.api.responses import errors
from app.schemas.common import Page
from app.schemas.employee import EmployeeCreate, EmployeeListQuery, EmployeeRead, EmployeeUpdate
from app.services import employee_service

router = APIRouter(
    prefix="/employees",
    tags=["Employees"],
    dependencies=[Depends(get_current_user)],
    responses=errors(401),
)

AdminOnly = [Depends(require_admin)]


@router.post(
    "",
    response_model=EmployeeRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=AdminOnly,
    summary="Add an employee",
    description="Admin only. Email must be unique (BR8); it is stored in lower case.",
    responses=errors(403, 409, 422),
)
def create_employee(body: EmployeeCreate, db: DbSession) -> EmployeeRead:
    return EmployeeRead.model_validate(employee_service.create_employee(db, body))


@router.get(
    "",
    response_model=Page[EmployeeRead],
    summary="List employees",
    description="Paged, ordered by name. Use `active=true` to show only active employees.",
    responses=errors(422),
)
def list_employees(query: Annotated[EmployeeListQuery, Query()], db: DbSession) -> Page[EmployeeRead]:
    items, total = employee_service.list_employees(db, query)
    return Page[EmployeeRead](
        items=[EmployeeRead.model_validate(e) for e in items], total=total, page=query.page, size=query.size
    )


@router.get(
    "/{employee_id}",
    response_model=EmployeeRead,
    summary="Get one employee",
    responses=errors(404, 422),
)
def get_employee(employee_id: int, db: DbSession) -> EmployeeRead:
    return EmployeeRead.model_validate(employee_service.get_employee(db, employee_id))


@router.patch(
    "/{employee_id}",
    response_model=EmployeeRead,
    dependencies=AdminOnly,
    summary="Change an employee",
    description="Admin only. Send only the fields to change.",
    responses=errors(403, 404, 409, 422),
)
def update_employee(employee_id: int, body: EmployeeUpdate, db: DbSession) -> EmployeeRead:
    return EmployeeRead.model_validate(employee_service.update_employee(db, employee_id, body))


@router.delete(
    "/{employee_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=AdminOnly,
    summary="Remove an employee",
    description="Admin only. Refused while the employee holds any asset (BR7). "
    "Their past assignments stay in the asset history.",
    responses=errors(403, 404, 409),
)
def delete_employee(employee_id: int, db: DbSession) -> None:
    employee_service.delete_employee(db, employee_id)
