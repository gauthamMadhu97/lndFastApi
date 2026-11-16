"""Bring the database up to date and create the default sign-in accounts.

    python -m app.init_db                       # migrate + seed users
    python -m app.init_db --demo                # also add a few sample employees and assets
    python -m app.init_db --new-migration "add notes to assets"
                                                # after changing a model: generate a migration

Safe to run more than once: migrations already applied are skipped,
and existing users/records are left alone.
"""

import argparse
import logging
from datetime import date
from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.core.config import get_settings
from app.db.session import SessionLocal
from app.models import Asset, Employee
from app.models.enums import AssetCategory, AssetStatus
from app.services.user_service import ensure_default_users

MIGRATIONS = Path(__file__).resolve().parent / "migrations"

DEMO_EMPLOYEES = [
    ("Priya Nair", "priya.nair@example.com", "Engineering", True),
    ("Arjun Rao", "arjun.rao@example.com", "Finance", True),
    ("Meera Iyer", "meera.iyer@example.com", "Sales", False),
]

DEMO_ASSETS = [
    (
        "LAP-0001",
        "Dell Latitude 5440",
        AssetCategory.LAPTOP,
        "DL5440-77A1",
        date(2024, 4, 1),
        date(2027, 4, 1),
    ),
    (
        "LAP-0002",
        "ThinkPad T14 Gen 4",
        AssetCategory.LAPTOP,
        "TP14G4-1180",
        date(2023, 9, 15),
        date(2026, 9, 15),
    ),
    (
        "MON-0001",
        "Dell U2723QE 27in",
        AssetCategory.MONITOR,
        "U27-55KX2",
        date(2024, 1, 10),
        date(2027, 1, 10),
    ),
    ("PHN-0001", "Pixel 8", AssetCategory.PHONE, "PX8-0091", date(2024, 2, 20), date(2026, 2, 20)),
    (
        "PER-0001",
        "Logitech MX Keys",
        AssetCategory.PERIPHERAL,
        "MXK-33019",
        date(2025, 6, 5),
        date(2026, 6, 5),
    ),
]


def alembic_config(database_url: str) -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(MIGRATIONS))
    cfg.attributes["database_url"] = database_url  # read by migrations/env.py
    return cfg


def migrate(database_url: str) -> None:
    command.upgrade(alembic_config(database_url), "head")


def add_demo_data(db: Session) -> None:
    for name, email, dept, active in DEMO_EMPLOYEES:
        if db.scalar(select(Employee.id).where(Employee.email == email)) is None:
            db.add(Employee(full_name=name, email=email, department=dept, is_active=active))
    for tag, name, category, serial, bought, expires in DEMO_ASSETS:
        if db.scalar(select(Asset.id).where(Asset.asset_tag == tag)) is None:
            db.add(
                Asset(
                    asset_tag=tag,
                    name=name,
                    category=category,
                    serial_number=serial,
                    purchase_date=bought,
                    warranty_expiry=expires,
                    status=AssetStatus.AVAILABLE,
                )
            )
    db.commit()


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--demo", action="store_true", help="add sample employees and assets")
    parser.add_argument("--new-migration", metavar="MESSAGE", help="autogenerate a migration and exit")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)-5s [%(name)s] %(message)s")
    settings = get_settings()

    if args.new_migration:
        command.revision(alembic_config(settings.database_url), message=args.new_migration, autogenerate=True)
        return

    print(f"Migrating {settings.database_url}")
    migrate(settings.database_url)

    with SessionLocal() as db:
        created = ensure_default_users(db, settings)
        print(f"Users created: {', '.join(created) or 'none (already there)'}")
        if args.demo:
            add_demo_data(db)
            print("Demo data added")


if __name__ == "__main__":
    main()
