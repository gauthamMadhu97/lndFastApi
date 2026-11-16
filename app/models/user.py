from sqlalchemy import Enum, String
from sqlalchemy.orm import Mapped, mapped_column

from app.db.base import Base
from app.models.enums import Role


class User(Base):
    """Someone who signs in to the API (not the same thing as an Employee)."""

    __tablename__ = "users"

    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String(64), unique=True)
    password_hash: Mapped[str] = mapped_column(String(128))
    role: Mapped[Role] = mapped_column(
        Enum(
            Role,
            native_enum=False,
            create_constraint=True,
            values_callable=lambda e: [m.value for m in e],
            name="user_role",
            length=10,
        )
    )
