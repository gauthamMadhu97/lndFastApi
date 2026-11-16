"""Section 7: sign-in, tokens and roles."""

import logging
from datetime import UTC, datetime, timedelta

import jwt
import pytest
from sqlalchemy import select

from app.core.security import verify_password
from app.models import User
from tests.conftest import ADMIN, STAFF, assert_error

PROTECTED = [
    ("GET", "/auth/me"),
    ("GET", "/employees"),
    ("POST", "/employees"),
    ("GET", "/employees/1"),
    ("PATCH", "/employees/1"),
    ("DELETE", "/employees/1"),
    ("GET", "/assets"),
    ("POST", "/assets"),
    ("GET", "/assets/1"),
    ("PATCH", "/assets/1"),
    ("DELETE", "/assets/1"),
    ("POST", "/assets/1/assignments"),
    ("GET", "/assets/1/assignments"),
    ("POST", "/assets/1/return"),
    ("POST", "/warranty-checks"),
]

ADMIN_ONLY = [
    ("POST", "/employees", {"full_name": "A", "email": "a@example.com", "department": "X"}),
    ("PATCH", "/employees/{employee}", {"department": "X"}),
    ("DELETE", "/employees/{employee}", None),
    (
        "POST",
        "/assets",
        {
            "asset_tag": "NEW-1",
            "name": "n",
            "category": "phone",
            "serial_number": "s",
            "purchase_date": "2024-01-01",
            "warranty_expiry": "2025-01-01",
        },
    ),
    ("PATCH", "/assets/{asset}", {"name": "X"}),
    ("DELETE", "/assets/{asset}", None),
]


class TestSignIn:
    def test_sign_in_issues_token(self, client, settings):
        resp = client.post("/auth/token", data={"username": ADMIN[0], "password": ADMIN[1]})
        assert resp.status_code == 200
        data = resp.json()
        assert data["token_type"] == "bearer"
        assert data["role"] == "admin"
        assert data["expires_in"] == settings.access_token_expire_minutes * 60
        claims = jwt.decode(data["access_token"], settings.secret_key, algorithms=["HS256"])
        assert claims["sub"] == ADMIN[0]

    def test_token_works_on_later_requests(self, client, staff):
        resp = client.get("/auth/me", headers=staff)
        assert resp.status_code == 200
        assert resp.json() == {"id": 2, "username": "staff", "role": "staff"}

    @pytest.mark.parametrize(
        "username,password",
        [
            (ADMIN[0], "wrong-password"),
            ("nobody", "whatever"),
            (ADMIN[0], ""),
            (ADMIN[0], "x" * 200),  # longer than bcrypt's 72 byte limit
        ],
    )
    def test_bad_credentials_refused(self, client, username, password):
        resp = client.post("/auth/token", data={"username": username, "password": password})
        assert resp.status_code in (401, 422)
        assert "access_token" not in resp.text

    def test_wrong_password_is_401(self, client):
        resp = client.post("/auth/token", data={"username": ADMIN[0], "password": "nope"})
        assert_error(resp, 401, "NOT_AUTHENTICATED")
        assert resp.headers["WWW-Authenticate"] == "Bearer"

    def test_json_body_instead_of_form_refused(self, client):
        assert_error(client.post("/auth/token", json={"username": ADMIN[0], "password": ADMIN[1]}), 422)


class TestNoValidCredential:
    @pytest.mark.parametrize("method,path", PROTECTED)
    def test_no_token_refused(self, client, method, path):
        resp = client.request(method, path)
        assert_error(resp, 401, "NOT_AUTHENTICATED")
        assert resp.headers["WWW-Authenticate"] == "Bearer"

    def test_garbage_token_refused(self, client):
        resp = client.get("/assets", headers={"Authorization": "Bearer not.a.jwt"})
        assert_error(resp, 401, "NOT_AUTHENTICATED")

    def test_wrong_scheme_refused(self, client):
        assert_error(client.get("/assets", headers={"Authorization": "Basic YWRtaW46eA=="}), 401)

    def test_expired_token_refused(self, client, settings):
        past = datetime.now(UTC) - timedelta(hours=2)
        token = jwt.encode(
            {"sub": "admin", "role": "admin", "iat": past, "exp": past + timedelta(minutes=30)},
            settings.secret_key,
            algorithm="HS256",
        )
        error = assert_error(client.get("/assets", headers={"Authorization": f"Bearer {token}"}), 401)
        assert error["message"] == "Token has expired"

    def test_token_signed_with_another_key_refused(self, client):
        now = datetime.now(UTC)
        forged = jwt.encode(
            {"sub": "admin", "role": "admin", "iat": now, "exp": now + timedelta(minutes=5)},
            "attacker-key-attacker-key-attacker-key",
            algorithm="HS256",
        )
        assert_error(client.get("/assets", headers={"Authorization": f"Bearer {forged}"}), 401)

    def test_unsigned_token_refused(self, client):
        now = datetime.now(UTC)
        unsigned = jwt.encode(
            {"sub": "admin", "iat": now, "exp": now + timedelta(minutes=5)}, key=None, algorithm="none"
        )
        assert_error(client.get("/assets", headers={"Authorization": f"Bearer {unsigned}"}), 401)

    def test_token_for_removed_user_refused(self, client, admin, session_factory):
        with session_factory() as db:
            db.delete(db.scalar(select(User).where(User.username == ADMIN[0])))
            db.commit()
        assert_error(client.get("/assets", headers=admin), 401)


class TestRoles:
    def test_staff_can_view_assign_and_return(self, client, staff, make_asset, make_employee):
        asset, emp = make_asset(), make_employee()
        assert client.get("/employees", headers=staff).status_code == 200
        assert client.get(f"/employees/{emp['id']}", headers=staff).status_code == 200
        assert client.get("/assets", headers=staff).status_code == 200
        assert client.get(f"/assets/{asset['id']}", headers=staff).status_code == 200
        assert (
            client.post(
                f"/assets/{asset['id']}/assignments", json={"employee_id": emp["id"]}, headers=staff
            ).status_code
            == 201
        )
        assert client.post(f"/assets/{asset['id']}/return", json={}, headers=staff).status_code == 200
        assert client.get(f"/assets/{asset['id']}/assignments", headers=staff).status_code == 200
        assert (
            client.post(
                "/warranty-checks", json={"asset_tags": [asset["asset_tag"]]}, headers=staff
            ).status_code
            == 200
        )

    @pytest.mark.parametrize("method,path,body", ADMIN_ONLY)
    def test_staff_cannot_change_records(self, client, staff, make_asset, make_employee, method, path, body):
        path = path.format(employee=make_employee()["id"], asset=make_asset()["id"])
        resp = client.request(method, path, json=body, headers=staff)
        error = assert_error(resp, 403, "FORBIDDEN")
        assert "admin" in error["message"]

    def test_staff_refused_change_leaves_record_alone(self, client, staff, make_asset):
        asset = make_asset()
        client.delete(f"/assets/{asset['id']}", headers=staff)
        assert client.get(f"/assets/{asset['id']}", headers=staff).status_code == 200

    @pytest.mark.parametrize("method,path,body", ADMIN_ONLY)
    def test_admin_can_change_records(self, client, admin, make_asset, make_employee, method, path, body):
        path = path.format(employee=make_employee()["id"], asset=make_asset()["id"])
        resp = client.request(method, path, json=body, headers=admin)
        assert resp.status_code in (200, 201, 204), resp.text

    def test_admin_can_also_assign(self, admin, client, make_asset, make_employee):
        asset, emp = make_asset(), make_employee()
        resp = client.post(
            f"/assets/{asset['id']}/assignments", json={"employee_id": emp["id"]}, headers=admin
        )
        assert resp.status_code == 201


class TestPasswordsNotReadable:
    def test_passwords_stored_as_bcrypt_hashes(self, session_factory):
        with session_factory() as db:
            users = {u.username: u for u in db.scalars(select(User))}
        for username, password in (ADMIN, STAFF):
            stored = users[username].password_hash
            assert password not in stored
            assert stored.startswith("$2b$")
            assert verify_password(password, stored)

    def test_password_never_logged(self, client, caplog):
        with caplog.at_level(logging.DEBUG):
            client.post("/auth/token", data={"username": ADMIN[0], "password": ADMIN[1]})
            client.post("/auth/token", data={"username": ADMIN[0], "password": "Wr0ng-Secret!"})
        assert caplog.records, "expected access log lines"
        assert ADMIN[1] not in caplog.text
        assert "Wr0ng-Secret!" not in caplog.text

    def test_validation_error_does_not_echo_password(self, client):
        resp = client.post("/auth/token", data={"password": "Echo-Me-Not"})
        assert resp.status_code == 422
        assert "Echo-Me-Not" not in resp.text

    def test_user_response_has_no_hash(self, client, admin):
        assert "password" not in client.get("/auth/me", headers=admin).text
