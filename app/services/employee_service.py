from collections.abc import Sequence

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import BusinessRuleError, NotFoundError
from app.models import Assignment, Employee
from app.schemas.employee import EmployeeCreate, EmployeeListQuery, EmployeeUpdate
from app.services._db import atomic, paginate


def _duplicate_email(email: str) -> BusinessRuleError:
    return BusinessRuleError("BR8", "DUPLICATE_EMAIL", f"An employee with email {email} already exists")


def _email_taken(db: Session, email: str, exclude_id: int | None = None) -> bool:
    stmt = select(Employee.id).where(Employee.email == email)
    if exclude_id is not None:
        stmt = stmt.where(Employee.id != exclude_id)
    return db.scalar(stmt) is not None


def get_employee(db: Session, employee_id: int) -> Employee:
    employee = db.get(Employee, employee_id)
    if employee is None:
        raise NotFoundError(f"Employee {employee_id} not found")
    return employee


def list_employees(db: Session, query: EmployeeListQuery) -> tuple[Sequence[Employee], int]:
    stmt = select(Employee).order_by(Employee.full_name, Employee.id)
    if query.active is not None:
        stmt = stmt.where(Employee.is_active.is_(query.active))
    return paginate(db, stmt, query.page, query.size)


def create_employee(db: Session, data: EmployeeCreate) -> Employee:
    if _email_taken(db, data.email):
        raise _duplicate_email(data.email)
    employee = Employee(**data.model_dump())
    try:
        with atomic(db):
            db.add(employee)
    except IntegrityError as exc:  # someone else inserted the same email in the meantime
        raise _duplicate_email(data.email) from exc
    return employee


def update_employee(db: Session, employee_id: int, data: EmployeeUpdate) -> Employee:
    employee = get_employee(db, employee_id)
    changes = data.model_dump(exclude_unset=True)
    if changes.get("email") and _email_taken(db, changes["email"], exclude_id=employee_id):
        raise _duplicate_email(changes["email"])
    # A field explicitly sent as null is ignored rather than wiping a required column
    changes = {k: v for k, v in changes.items() if v is not None}
    try:
        with atomic(db):
            for field, value in changes.items():
                setattr(employee, field, value)
    except IntegrityError as exc:
        raise _duplicate_email(changes.get("email", "")) from exc
    return employee


def count_assets_held(db: Session, employee_id: int) -> int:
    stmt = select(func.count()).where(Assignment.employee_id == employee_id, Assignment.returned_on.is_(None))
    return db.scalar(stmt) or 0


def delete_employee(db: Session, employee_id: int) -> None:
    employee = get_employee(db, employee_id)
    held = count_assets_held(db, employee_id)
    if held:
        raise BusinessRuleError(
            "BR7",
            "EMPLOYEE_HOLDS_ASSETS",
            f"Employee {employee_id} still holds {held} asset(s); record the returns first",
        )
    # Past assignments keep their row; the database sets employee_id to NULL
    with atomic(db):
        db.delete(employee)
