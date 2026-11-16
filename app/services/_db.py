from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session


@contextmanager
def atomic(db: Session) -> Iterator[None]:
    """Commit if the block finishes, otherwise roll back so nothing half-done is left (4.6)."""
    try:
        yield
        db.commit()
    except BaseException:
        db.rollback()
        raise


def paginate(db: Session, stmt: Select[Any], page: int, size: int) -> tuple[Sequence[Any], int]:
    total = db.scalar(select(func.count()).select_from(stmt.order_by(None).subquery())) or 0
    items = db.scalars(stmt.limit(size).offset((page - 1) * size)).all()
    return items, total
