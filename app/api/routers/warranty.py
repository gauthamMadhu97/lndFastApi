from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends
from fastapi.concurrency import run_in_threadpool
from sqlalchemy.orm import Session

from app.api.deps import AppSettings, DbSession, get_current_user, get_warranty_client
from app.api.responses import errors
from app.integrations.warranty_client import WarrantyClient
from app.schemas.warranty import WarrantyCheckRequest, WarrantyCheckResponse
from app.services import asset_service, warranty_service

router = APIRouter(
    prefix="/warranty-checks",
    tags=["Warranty"],
    dependencies=[Depends(get_current_user)],
    responses=errors(401),
)


def _expiry_by_tag(db: Session, tags: list[str]) -> dict[str, date]:
    return {tag: asset.warranty_expiry for tag, asset in asset_service.get_assets_by_tags(db, tags).items()}


# async because the time goes on waiting for the warranty source, and those waits can
# overlap. The database lookup is sync, so it is pushed to the threadpool.
@router.post(
    "",
    response_model=WarrantyCheckResponse,
    summary="Check warranty for several assets",
    description="Up to 50 asset tags. Lookups run in parallel. A tag that can't be checked "
    "comes back with `ok: false` and an `error`; the rest are still returned.",
    responses=errors(422),
)
async def check_warranty(
    body: WarrantyCheckRequest,
    db: DbSession,
    settings: AppSettings,
    client: Annotated[WarrantyClient, Depends(get_warranty_client)],
) -> WarrantyCheckResponse:
    known = await run_in_threadpool(_expiry_by_tag, db, body.asset_tags)
    return await warranty_service.check_many(
        client, body.asset_tags, known, settings.warranty_timeout_seconds
    )
