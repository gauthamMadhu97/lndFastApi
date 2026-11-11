"""Section 1: employee records."""

from tests.conftest import assert_error


class TestCreate:
    def test_create_employee(self, client, admin):
        body = {"full_name": "Priya Nair", "email": "Priya.Nair@Example.com", "department": "Engineering"}
        resp = client.post("/employees", json=body, headers=admin)
        assert resp.status_code == 201
        data = resp.json()
        assert data["full_name"] == "Priya Nair"
        assert data["email"] == "priya.nair@example.com"  # stored lower case
        assert data["is_active"] is True
        assert set(data) == {"id", "full_name", "email", "department", "is_active"}

    def test_duplicate_email_refused_br8(self, client, admin, make_employee):
        make_employee(email="dup@example.com")
        body = {"full_name": "Someone Else", "email": "DUP@example.com", "department": "HR"}
        resp = client.post("/employees", json=body, headers=admin)
        assert_error(resp, 409, "DUPLICATE_EMAIL", "BR8")

    def test_invalid_email_refused(self, client, admin):
        body = {"full_name": "X", "email": "not-an-email", "department": "HR"}
        assert_error(client.post("/employees", json=body, headers=admin), 422, "VALIDATION_ERROR")

    def test_missing_and_blank_fields_refused(self, client, admin):
        resp = client.post("/employees", json={"full_name": "   ", "email": "a@example.com"}, headers=admin)
        error = assert_error(resp, 422)
        bad_fields = {tuple(d["loc"]) for d in error["details"]}
        assert ("body", "full_name") in bad_fields
        assert ("body", "department") in bad_fields

    def test_overlong_name_refused(self, client, admin):
        body = {"full_name": "x" * 121, "email": "long@example.com", "department": "HR"}
        assert_error(client.post("/employees", json=body, headers=admin), 422)

    def test_unknown_field_refused(self, client, admin):
        body = {"full_name": "A", "email": "a2@example.com", "department": "HR", "salary": 1}
        assert_error(client.post("/employees", json=body, headers=admin), 422)


class TestRetrieve:
    def test_get_one(self, client, staff, make_employee):
        emp = make_employee(full_name="Arjun Rao")
        resp = client.get(f"/employees/{emp['id']}", headers=staff)
        assert resp.status_code == 200
        assert resp.json() == emp

    def test_get_missing_is_404(self, client, staff):
        assert_error(client.get("/employees/9999", headers=staff), 404, "NOT_FOUND")

    def test_get_non_integer_id_is_422(self, client, staff):
        assert_error(client.get("/employees/abc", headers=staff), 422)


class TestList:
    def test_list_all_and_active_only(self, client, staff, make_employee):
        make_employee(is_active=True)
        make_employee(is_active=True)
        make_employee(is_active=False)

        everyone = client.get("/employees", headers=staff).json()
        assert everyone["total"] == 3

        active = client.get("/employees", params={"active": "true"}, headers=staff).json()
        assert active["total"] == 2
        assert all(e["is_active"] for e in active["items"])

        inactive = client.get("/employees", params={"active": "false"}, headers=staff).json()
        assert inactive["total"] == 1

    def test_list_rejects_bad_active_value(self, client, staff):
        assert_error(client.get("/employees", params={"active": "maybe"}, headers=staff), 422)


class TestUpdate:
    def test_patch_changes_only_given_fields(self, client, admin, make_employee):
        emp = make_employee(department="Sales")
        resp = client.patch(f"/employees/{emp['id']}", json={"is_active": False}, headers=admin)
        assert resp.status_code == 200
        assert resp.json()["is_active"] is False
        assert resp.json()["department"] == "Sales"

    def test_patch_to_existing_email_refused_br8(self, client, admin, make_employee):
        make_employee(email="taken@example.com")
        emp = make_employee()
        resp = client.patch(f"/employees/{emp['id']}", json={"email": "taken@example.com"}, headers=admin)
        assert_error(resp, 409, "DUPLICATE_EMAIL", "BR8")

    def test_patch_missing_employee_404(self, client, admin):
        assert_error(client.patch("/employees/9999", json={"department": "X"}, headers=admin), 404)


class TestDelete:
    def test_delete_employee(self, client, admin, make_employee):
        emp = make_employee()
        assert client.delete(f"/employees/{emp['id']}", headers=admin).status_code == 204
        assert client.get(f"/employees/{emp['id']}", headers=admin).status_code == 404

    def test_delete_employee_holding_asset_refused_br7(
        self, client, admin, make_employee, make_asset, assign
    ):
        emp = make_employee()
        asset = make_asset()
        assert assign(asset["id"], emp["id"]).status_code == 201

        error = assert_error(
            client.delete(f"/employees/{emp['id']}", headers=admin), 409, "EMPLOYEE_HOLDS_ASSETS", "BR7"
        )
        assert "1 asset" in error["message"]
        assert client.get(f"/employees/{emp['id']}", headers=admin).status_code == 200

    def test_delete_after_return_keeps_history(self, client, admin, staff, make_employee, make_asset, assign):
        emp = make_employee(full_name="Leaver Person")
        asset = make_asset()
        assign(asset["id"], emp["id"])
        client.post(f"/assets/{asset['id']}/return", json={}, headers=staff)

        assert client.delete(f"/employees/{emp['id']}", headers=admin).status_code == 204
        history = client.get(f"/assets/{asset['id']}/assignments", headers=staff).json()
        assert history["total"] == 1
        assert history["items"][0]["employee_id"] is None
        assert history["items"][0]["employee_name"] == "Leaver Person"

    def test_delete_missing_employee_404(self, client, admin):
        assert_error(client.delete("/employees/9999", headers=admin), 404)
