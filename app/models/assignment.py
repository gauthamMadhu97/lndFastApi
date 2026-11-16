from datetime import date
from typing import TYPE_CHECKING

from sqlalchemy import CheckConstraint, Date, ForeignKey, Index, String, text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.db.base import Base

if TYPE_CHECKING:
    from app.models.asset import Asset
    from app.models.employee import Employee


class Assignment(Base):
    __tablename__ = "assignments"
    __table_args__ = (
        # BR1 at database level: at most one open assignment per asset.
        # Covers two requests racing each other, which an "if" in Python can't.
        Index(
            "uq_assignments_one_open_per_asset",
            "asset_id",
            unique=True,
            sqlite_where=text("returned_on IS NULL"),
            postgresql_where=text("returned_on IS NULL"),
        ),
        CheckConstraint("returned_on IS NULL OR returned_on >= assigned_on", name="return_after_assign"),
    )

    id: Mapped[int] = mapped_column(primary_key=True)
    asset_id: Mapped[int] = mapped_column(ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    # SET NULL so deleting a former holder keeps the asset's history (BR7 blocks current holders)
    employee_id: Mapped[int | None] = mapped_column(
        ForeignKey("employees.id", ondelete="SET NULL"), index=True
    )
    # Copied at assignment time so the history still reads properly after an employee is removed
    employee_name: Mapped[str] = mapped_column(String(120))
    employee_email: Mapped[str] = mapped_column(String(254))
    assigned_on: Mapped[date] = mapped_column(Date)
    returned_on: Mapped[date | None] = mapped_column(Date)

    asset: Mapped["Asset"] = relationship(back_populates="assignments")
    employee: Mapped["Employee | None"] = relationship()
