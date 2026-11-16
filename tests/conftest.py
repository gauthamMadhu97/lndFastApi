from collections.abc import Callable, Iterator
from datetime import date, timedelta
from itertools import count
from typing import Any

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session, sessionmaker

from app.core.config import Settings, get_settings
from app.db.base import Base
from app.db.session import build_engine, build_session_factory, get_db
from app.integrations.notifier import StubNotifier
from app.integrations.warranty_client import StubWarrantyClient
from app.main import create_app
from app.services.user_service import ensure_default_users

ADMIN = ("admin", "admin-test-pw")
STAFF = ("staff", "staff-test-pw")


@pytest.fixture
def settings(tmp_path: Any) -> Settings:
    # Each test gets its own throwaway database file
    return Settings(
        _env_file=None,
        app_env="test",
        database_url=f"sqlite:///{tmp_path / 'test.db'}",
        secret_key="test-secret-key-that-is-long-enough-for-hs256",
        bcrypt_rounds=4,  # fast hashing for tests only
        admin_username=ADMIN[0],
        admin_password=ADMIN[1],
        staff_username=STAFF[0],
        staff_password=STAFF[1],
        cors_origins=["http://localhost:5173"],
        notifier_delay_seconds=0.01,
        warranty_delay_seconds=0.5,
    )


@pytest.fixture
def session_factory(settings: Settings) -> Iterator[sessionmaker[Session]]:
    engine = build_engine(settings.database_url)
    Base.metadata.create_all(engine)
    factory = build_session_factory(engine)
    with factory() as db:
        ensure_default_users(db, settings)
    yield factory
    engine.dispose()


@pytest.fixture
def app(settings: Settings, session_factory: sessionmaker[Session]) -> FastAPI:
    application = create_app(settings)

    def test_db() -> Iterator[Session]:
        db = session_factory()
        try:
            yield db
        finally:
            db.close()

    application.dependency_overrides[get_db] = test_db
    application.dependency_overrides[get_settings] = lambda: settings
    application.state.notifier = StubNotifier(delay=settings.notifier_delay_seconds)
    application.state.warranty_client = StubWarrantyClient(delay=settings.warranty_delay_seconds)
    return application


@pytest.fixture
def client(app: FastAPI) -> Iterator[TestClient]:
    with TestClient(app) as test_client:
        yield test_client


def _login(client: TestClient, username: str, password: str) -> dict[str, str]:
    resp = client.post("/auth/token", data={"username": username, "password": password})
    assert resp.status_code == 200, resp.text
    return {"Authorization": f"Bearer {resp.json()['access_token']}"}


@pytest.fixture
def admin(client: TestClient) -> dict[str, str]:
    return _login(client, *ADMIN)


@pytest.fixture
def staff(client: TestClient) -> dict[str, str]:
    return _login(client, *STAFF)


_seq = count(1)


@pytest.fixture
def make_employee(client: TestClient, admin: dict[str, str]) -> Callable[..., dict[str, Any]]:
    def _make(**overrides: Any) -> dict[str, Any]:
        n = next(_seq)
        body = {
            "full_name": f"Employee {n}",
            "email": f"employee{n}@example.com",
            "department": "Engineering",
            "is_active": True,
        } | overrides
        resp = client.post("/employees", json=body, headers=admin)
        assert resp.status_code == 201, resp.text
        return resp.json()

    return _make


@pytest.fixture
def make_asset(client: TestClient, admin: dict[str, str]) -> Callable[..., dict[str, Any]]:
    def _make(**overrides: Any) -> dict[str, Any]:
        n = next(_seq)
        body = {
            "asset_tag": f"LAP-{n:04d}",
            "name": f"Laptop {n}",
            "category": "laptop",
            "serial_number": f"SN{n:06d}",
            "purchase_date": str(date.today() - timedelta(days=365)),
            "warranty_expiry": str(date.today() + timedelta(days=365)),
        } | overrides
        resp = client.post("/assets", json=body, headers=admin)
        assert resp.status_code == 201, resp.text
        return resp.json()

    return _make


@pytest.fixture
def assign(client: TestClient, staff: dict[str, str]) -> Callable[..., Any]:
    def _assign(asset_id: int, employee_id: int, **extra: Any) -> Any:
        return client.post(
            f"/assets/{asset_id}/assignments", json={"employee_id": employee_id, **extra}, headers=staff
        )

    return _assign


def assert_error(resp: Any, status: int, code: str | None = None, rule: str | None = None) -> dict[str, Any]:
    assert resp.status_code == status, resp.text
    error = resp.json()["error"]
    if code:
        assert error["code"] == code
    if rule:
        assert error["rule"] == rule
    assert error["request_id"] == resp.headers["X-Request-ID"]
    return error
