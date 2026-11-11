from collections.abc import Sequence

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import UNPROCESSABLE, BusinessRuleError
from app.models import Assignment
from app.models.enums import AssetStatus
from app.schemas.assignment import AssignmentCreate, ReturnCreate
from app.schemas.common import PageQuery
from app.services._db import atomic, paginate
from app.services.asset_service import get_asset, get_open_assignment
from app.services.employee_service import get_employee


def assign_asset(db: Session, asset_id: int, data: AssignmentCreate) -> Assignment:
    asset = get_asset(db, asset_id)
    employee = get_employee(db, data.employee_id)

    if asset.status == AssetStatus.ASSIGNED:
        raise BusinessRuleError("BR1", "ASSET_ALREADY_ASSIGNED", "Asset is already held by another employee")
    if asset.status != AssetStatus.AVAILABLE:
        raise BusinessRuleError(
            "BR2", "ASSET_NOT_AVAILABLE", f"Only available assets can be assigned (status is {asset.status})"
        )
    if not employee.is_active:
        raise BusinessRuleError("BR5", "EMPLOYEE_INACTIVE", f"Employee {employee.id} is not active")
    if data.assigned_on < asset.purchase_date:
        raise BusinessRuleError(
            "BR3",
            "ASSIGNED_BEFORE_PURCHASE",
            "assigned_on cannot be before the purchase date",
            status_code=UNPROCESSABLE,
        )
    last_return = db.scalar(
        select(Assignment.returned_on)
        .where(Assignment.asset_id == asset_id)
        .order_by(Assignment.returned_on.desc())
        .limit(1)
    )
    if last_return and data.assigned_on < last_return:
        # would overlap the previous holder in the history (BR1)
        raise BusinessRuleError(
            "BR1",
            "OVERLAPS_PREVIOUS_ASSIGNMENT",
            f"assigned_on cannot be before the last return ({last_return})",
            status_code=UNPROCESSABLE,
        )

    assignment = Assignment(
        asset_id=asset.id,
        employee_id=employee.id,
        employee_name=employee.full_name,
        employee_email=employee.email,
        assigned_on=data.assigned_on,
    )
    try:
        with atomic(db):
            db.add(assignment)
            asset.status = AssetStatus.ASSIGNED
    except IntegrityError as exc:
        # The partial unique index caught a second open assignment (e.g. two requests at once)
        raise BusinessRuleError(
            "BR1", "ASSET_ALREADY_ASSIGNED", "Asset is already held by another employee"
        ) from exc
    return assignment


def return_asset(db: Session, asset_id: int, data: ReturnCreate) -> Assignment:
    asset = get_asset(db, asset_id)
    current = get_open_assignment(db, asset_id)
    if current is None:
        raise BusinessRuleError("BR4", "ASSET_NOT_ASSIGNED", "Asset is not currently assigned")
    if data.returned_on < current.assigned_on:
        raise BusinessRuleError(
            "BR4",
            "RETURN_BEFORE_ASSIGNMENT",
            f"returned_on cannot be before assigned_on ({current.assigned_on})",
            status_code=UNPROCESSABLE,
        )
    with atomic(db):
        current.returned_on = data.returned_on
        asset.status = AssetStatus.AVAILABLE
    return current


def assignment_history(db: Session, asset_id: int, query: PageQuery) -> tuple[Sequence[Assignment], int]:
    get_asset(db, asset_id)  # 404 if it doesn't exist
    stmt = (
        select(Assignment)
        .where(Assignment.asset_id == asset_id)
        .order_by(Assignment.assigned_on.desc(), Assignment.id.desc())
    )
    return paginate(db, stmt, query.page, query.size)
