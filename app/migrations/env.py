"""Alembic environment. Configured from code in app/init_db.py, so there is no alembic.ini."""

from alembic import context

import app.models  # noqa: F401  (registers the tables on Base.metadata)
from app.core.config import get_settings
from app.db.base import Base
from app.db.session import build_engine

config = context.config
target_metadata = Base.metadata

# The URL comes from the app settings (env / .env)
database_url = config.attributes.get("database_url") or get_settings().database_url


def run_migrations_offline() -> None:
    context.configure(
        url=database_url,
        target_metadata=target_metadata,
        literal_binds=True,
        render_as_batch=database_url.startswith("sqlite"),
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    # build_engine also turns on SQLite foreign keys, same as the app
    engine = build_engine(database_url)
    try:
        with engine.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=connection.dialect.name == "sqlite",
            )
            with context.begin_transaction():
                context.run_migrations()
    finally:
        engine.dispose()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
