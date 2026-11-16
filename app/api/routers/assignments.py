from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, Query, status

from app.api.deps import DbSession, get_current_user, get_notifier
from app.api.responses import errors
from app.integrations.notifier import AssetEvent, Notifier, deliver
from app.schemas.assignment import AssignmentCreate, AssignmentRead, ReturnCreate
from app.schemas.common import Page, PageQuery
from app.services import assignment_service

router = APIRouter(
    prefix="/assets/{asset_id}",
    tags=["Assignments"],
    dependencies=[Depends(get_current_user)],
    responses=errors(401),
)

NotifierDep = Annotated[Notifier, Depends(get_notifier)]


@router.post(
    "/assignments",
    response_model=AssignmentRead,
    status_code=status.HTTP_201_CREATED,
    summary="Assign an asset to an employee",
    description="Staff or admin. The asset must be available (BR1, BR2) and the employee active (BR5). "
    "The external system is notified after the response is sent.",
    responses=errors(404, 409, 422),
)
def assign_asset(
    asset_id: int, body: AssignmentCreate, db: DbSession, background: BackgroundTasks, notifier: NotifierDep
) -> AssignmentRead:
    assignment = assignment_service.assign_asset(db, asset_id, body)
    background.add_task(
        deliver,
        notifier,
        AssetEvent(
            event="asset.assigned",
            asset_id=asset_id,
            asset_tag=assignment.asset.asset_tag,
            employee_id=assignment.employee_id,
            on=assignment.assigned_on,
        ),
    )
    return AssignmentRead.model_validate(assignment)


# A return closes the open assignment. It's modelled as an action on the asset because
# the caller knows the asset in their hand, not the assignment id.
@router.post(
    "/return",
    response_model=AssignmentRead,
    summary="Record the return of an asset",
    description="Staff or admin. Closes the open assignment and makes the asset available (BR4). "
    "Returns the closed assignment.",
    responses=errors(404, 409, 422),
)
def return_asset(
    asset_id: int, body: ReturnCreate, db: DbSession, background: BackgroundTasks, notifier: NotifierDep
) -> AssignmentRead:
    assignment = assignment_service.return_asset(db, asset_id, body)
    background.add_task(
        deliver,
        notifier,
        AssetEvent(
            event="asset.returned",
            asset_id=asset_id,
            asset_tag=assignment.asset.asset_tag,
            employee_id=assignment.employee_id,
            on=body.returned_on,
        ),
    )
    return AssignmentRead.model_validate(assignment)


@router.get(
    "/assignments",
    response_model=Page[AssignmentRead],
    summary="Assignment history",
    description="Every assignment of the asset, newest first.",
    responses=errors(404, 422),
)
def assignment_history(
    asset_id: int, query: Annotated[PageQuery, Query()], db: DbSession
) -> Page[AssignmentRead]:
    items, total = assignment_service.assignment_history(db, asset_id, query)
    return Page[AssignmentRead](
        items=[AssignmentRead.model_validate(a) for a in items], total=total, page=query.page, size=query.size
    )
