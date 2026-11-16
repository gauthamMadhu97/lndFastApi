from collections.abc import Iterator
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import get_settings


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _record: Any) -> None:
    # SQLite ignores foreign keys unless this is switched on for every connection
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def build_engine(database_url: str) -> Engine:
    if database_url.startswith("sqlite"):
        engine = create_engine(database_url, connect_args={"check_same_thread": False})
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
        return engine
    return create_engine(database_url, pool_pre_ping=True)


def build_session_factory(engine: Engine) -> sessionmaker[Session]:
    return sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


engine = build_engine(get_settings().database_url)
SessionLocal = build_session_factory(engine)


def get_db() -> Iterator[Session]:
    """A new session per request, closed once the request finishes (even if it failed)."""
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
