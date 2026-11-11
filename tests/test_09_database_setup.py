"""Section 9 (continued): the migrations and the database setup script."""

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from sqlalchemy import inspect, select, text
from sqlalchemy.exc import IntegrityError

from app import init_db
from app.db.base import Base
from app.db.session import build_engine, build_session_factory
from app.models import Asset, Employee, User


@pytest.fixture
def migrated(tmp_path):
    url = f"sqlite:///{tmp_path / 'migrated.db'}"
    init_db.migrate(url)
    engine = build_engine(url)
    yield url, engine
    engine.dispose()


def test_migrations_create_every_table(migrated):
    _, engine = migrated
    tables = set(inspect(engine).get_table_names())
    assert {"employees", "assets", "assignments", "users", "alembic_version"} <= tables


def test_migrations_match_the_models(migrated):
    """If a model changes without a new migration, this fails."""
    _, engine = migrated
    with engine.connect() as conn:
        diff = compare_metadata(MigrationContext.configure(conn), Base.metadata)
    assert diff == []


def test_migrated_database_enforces_constraints(migrated):
    _, engine = migrated
    with engine.begin() as conn, pytest.raises(IntegrityError):
        # foreign key to an asset that doesn't exist
        conn.execute(
            text(
                "INSERT INTO assignments (asset_id, employee_name, employee_email, assigned_on) "
                "VALUES (999, 'x', 'x@example.com', '2025-01-01')"
            )
        )


def test_migrating_twice_is_harmless(migrated):
    url, engine = migrated
    init_db.migrate(url)
    assert "assets" in inspect(engine).get_table_names()


def test_setup_script_seeds_users_and_demo_data(tmp_path, monkeypatch, settings, capsys):
    url = f"sqlite:///{tmp_path / 'setup.db'}"
    settings.database_url = url
    engine = build_engine(url)
    monkeypatch.setattr(init_db, "get_settings", lambda: settings)
    monkeypatch.setattr(init_db, "SessionLocal", build_session_factory(engine))

    init_db.main(["--demo"])
    init_db.main(["--demo"])  # second run must not duplicate anything

    out = capsys.readouterr().out
    assert "Users created: admin, staff" in out
    assert "Users created: none (already there)" in out
    with build_session_factory(engine)() as db:
        assert len(db.scalars(select(User)).all()) == 2
        assert len(db.scalars(select(Employee)).all()) == len(init_db.DEMO_EMPLOYEES)
        assert len(db.scalars(select(Asset)).all()) == len(init_db.DEMO_ASSETS)
    engine.dispose()
