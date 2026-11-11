from collections.abc import Sequence

from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.core.errors import UNPROCESSABLE, BusinessRuleError, NotFoundError
from app.models import Asset, Assignment
from app.models.enums import AssetStatus
from app.schemas.asset import AssetCreate, AssetDetail, AssetListQuery, AssetRead, AssetUpdate, CurrentHolder
from app.services._db import atomic, paginate


def _duplicate_tag(tag: str) -> BusinessRuleError:
    return BusinessRuleError("BR8", "DUPLICATE_ASSET_TAG", f"Asset tag {tag} is already in use")


def _tag_taken(db: Session, tag: str, exclude_id: int | None = None) -> bool:
    stmt = select(Asset.id).where(Asset.asset_tag == tag)
    if exclude_id is not None:
        stmt = stmt.where(Asset.id != exclude_id)
    return db.scalar(stmt) is not None


def get_asset(db: Session, asset_id: int) -> Asset:
    asset = db.get(Asset, asset_id)
    if asset is None:
        raise NotFoundError(f"Asset {asset_id} not found")
    return asset


def get_open_assignment(db: Session, asset_id: int) -> Assignment | None:
    return db.scalar(
        select(Assignment).where(Assignment.asset_id == asset_id, Assignment.returned_on.is_(None))
    )


def get_asset_detail(db: Session, asset_id: int) -> AssetDetail:
    asset = get_asset(db, asset_id)
    holder = None
    current = get_open_assignment(db, asset_id)
    if current is not None and current.employee is not None:
        holder = CurrentHolder(
            id=current.employee.id,
            full_name=current.employee.full_name,
            email=current.employee.email,
            assigned_on=current.assigned_on,
        )
    return AssetDetail(**AssetRead.model_validate(asset).model_dump(), current_holder=holder)


def list_assets(db: Session, query: AssetListQuery) -> tuple[Sequence[Asset], int]:
    stmt = select(Asset).order_by(Asset.asset_tag)
    if query.status is not None:
        stmt = stmt.where(Asset.status == query.status)
    if query.category is not None:
        stmt = stmt.where(Asset.category == query.category)
    if query.q:
        # autoescape so a search for "50%" doesn't act as a wildcard
        stmt = stmt.where(
            or_(
                Asset.name.icontains(query.q, autoescape=True),
                Asset.asset_tag.icontains(query.q, autoescape=True),
            )
        )
    return paginate(db, stmt, query.page, query.size)


def get_assets_by_tags(db: Session, tags: Sequence[str]) -> dict[str, Asset]:
    assets = db.scalars(select(Asset).where(Asset.asset_tag.in_(tags))).all()
    return {asset.asset_tag: asset for asset in assets}


def create_asset(db: Session, data: AssetCreate) -> Asset:
    if _tag_taken(db, data.asset_tag):
        raise _duplicate_tag(data.asset_tag)
    asset = Asset(**data.model_dump())
    try:
        with atomic(db):
            db.add(asset)
    except IntegrityError as exc:
        raise _duplicate_tag(data.asset_tag) from exc
    return asset


def update_asset(db: Session, asset_id: int, data: AssetUpdate) -> Asset:
    asset = get_asset(db, asset_id)
    changes = {k: v for k, v in data.model_dump(exclude_unset=True).items() if v is not None}

    if "status" in changes and asset.status == AssetStatus.ASSIGNED:
        raise BusinessRuleError(
            "BR4",
            "ASSET_IS_ASSIGNED",
            "Asset is assigned; record its return before changing the status",
        )

    # BR6 on the combined record: the request may only carry one of the two dates
    purchase = changes.get("purchase_date", asset.purchase_date)
    expiry = changes.get("warranty_expiry", asset.warranty_expiry)
    if expiry <= purchase:
        raise BusinessRuleError(
            "BR6",
            "WARRANTY_BEFORE_PURCHASE",
            "warranty_expiry must be after purchase_date",
            status_code=UNPROCESSABLE,
        )

    if "asset_tag" in changes and _tag_taken(db, changes["asset_tag"], exclude_id=asset_id):
        raise _duplicate_tag(changes["asset_tag"])

    try:
        with atomic(db):
            for field, value in changes.items():
                setattr(asset, field, value)
    except IntegrityError as exc:
        raise _duplicate_tag(changes.get("asset_tag", asset.asset_tag)) from exc
    return asset


def delete_asset(db: Session, asset_id: int) -> None:
    asset = get_asset(db, asset_id)
    if asset.status == AssetStatus.ASSIGNED:
        raise BusinessRuleError(
            "BR4", "ASSET_IS_ASSIGNED", "Asset is assigned; record its return before removing it"
        )
    with atomic(db):
        db.delete(asset)
