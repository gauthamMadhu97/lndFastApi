from typing import Annotated

from fastapi import APIRouter, Depends, Query, status

from app.api.deps import DbSession, get_current_user, require_admin
from app.api.responses import errors
from app.schemas.asset import AssetCreate, AssetDetail, AssetListQuery, AssetRead, AssetUpdate
from app.schemas.common import Page
from app.services import asset_service

router = APIRouter(
    prefix="/assets",
    tags=["Assets"],
    dependencies=[Depends(get_current_user)],
    responses=errors(401),
)

AdminOnly = [Depends(require_admin)]


@router.post(
    "",
    response_model=AssetRead,
    status_code=status.HTTP_201_CREATED,
    dependencies=AdminOnly,
    summary="Add an asset",
    description="Admin only. The tag must be unique (BR8) and the warranty must end after "
    "the purchase date (BR6). Status can't be `assigned` here; use the assignments endpoint.",
    responses=errors(403, 409, 422),
)
def create_asset(body: AssetCreate, db: DbSession) -> AssetRead:
    return AssetRead.model_validate(asset_service.create_asset(db, body))


@router.get(
    "",
    response_model=Page[AssetRead],
    summary="List and search assets",
    description="Filter by `status` and `category`, search name or tag with `q`. "
    "Unknown values or unknown parameters are refused with 422.",
    responses=errors(422),
)
def list_assets(query: Annotated[AssetListQuery, Query()], db: DbSession) -> Page[AssetRead]:
    items, total = asset_service.list_assets(db, query)
    return Page[AssetRead](
        items=[AssetRead.model_validate(a) for a in items], total=total, page=query.page, size=query.size
    )


@router.get(
    "/{asset_id}",
    response_model=AssetDetail,
    summary="Get one asset",
    description="Includes `current_holder` when the asset is assigned.",
    responses=errors(404, 422),
)
def get_asset(asset_id: int, db: DbSession) -> AssetDetail:
    return asset_service.get_asset_detail(db, asset_id)


@router.patch(
    "/{asset_id}",
    response_model=AssetRead,
    dependencies=AdminOnly,
    summary="Change an asset",
    description="Admin only. Send only the fields to change. Status can't be changed while the "
    "asset is assigned.",
    responses=errors(403, 404, 409, 422),
)
def update_asset(asset_id: int, body: AssetUpdate, db: DbSession) -> AssetRead:
    return AssetRead.model_validate(asset_service.update_asset(db, asset_id, body))


@router.delete(
    "/{asset_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=AdminOnly,
    summary="Remove an asset",
    description="Admin only. Refused while assigned. Removes its assignment history too.",
    responses=errors(403, 404, 409),
)
def delete_asset(asset_id: int, db: DbSession) -> None:
    asset_service.delete_asset(db, asset_id)
