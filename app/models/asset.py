from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, Enum, String
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base
from app.models.enums import AssetCategory, AssetStatus

if TYPE_CHECKING:
    from app.models.assignment import Assignment


def _enum_values(enum_cls: type) -> list[str]:
    return [member.value for member in enum_cls]


class Asset(Base):
    __tablename__ = "assets"
    __table_args__ = (
        # BR6, also checked in the schemas; this is the last line of defence
        CheckConstraint("warranty_expiry > purchase_date", name="warranty_after_purchase"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_tag: Mapped[str] = mapped_column(String(32), unique=True)  # BR8
    name: Mapped[str] = mapped_column(String(120), index=True)
    category: Mapped[AssetCategory] = mapped_column(
        Enum(
            AssetCategory,
            native_enum=False,
            create_constraint=True,
            values_callable=_enum_values,
            name="asset_category",
            length=20,
        )
    )
    serial_number: Mapped[str] = mapped_column(String(64))
    purchase_date: Mapped[date] = mapped_column(Date)
    warranty_expiry: Mapped[date] = mapped_column(Date)
    status: Mapped[AssetStatus] = mapped_column(
        Enum(
            AssetStatus,
            native_enum=False,
            create_constraint=True,
            values_callable=_enum_values,
            name="asset_status",
            length=20,
        ),
        default=AssetStatus.AVAILABLE,
    )

    # History goes with the asset when it is deleted
    assignments: Mapped[list["Assignment"]] = relationship(
        back_populates="asset", cascade="all, delete-orphan", passive_deletes=True
    )
