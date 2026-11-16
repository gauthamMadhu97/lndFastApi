"""Section 4: assignment and return, with the business rules."""

from datetime import date, timedelta

import pytest
from sqlalchemy import func, select
from sqlalchemy.orm.attributes import set_committed_value

from app.models import Assignment
from app.models.enums import AssetStatus
from app.services import assignment_service
from tests.conftest import assert_error

TODAY = date.today()


def assignment_rows(session_factory, asset_id):
    with session_factory() as db:
        return db.scalar(select(func.count()).where(Assignment.asset_id == asset_id))


def asset_status(client, headers, asset_id):
    return client.get(f"/assets/{asset_id}", headers=headers).json()["status"]


class TestAssign:
    def test_assign_records_date_and_sets_status_br3(self, client, staff, make_asset, make_employee, assign):
        asset, emp = make_asset(), make_employee()
        resp = assign(asset["id"], emp["id"], assigned_on=str(TODAY - timedelta(days=2)))
        assert resp.status_code == 201
        data = resp.json()
        assert data["employee_id"] == emp["id"]
        assert data["assigned_on"] == str(TODAY - timedelta(days=2))
        assert data["returned_on"] is None
        assert asset_status(client, staff, asset["id"]) == "assigned"

    def test_assign_defaults_to_today(self, make_asset, make_employee, assign):
        resp = assign(make_asset()["id"], make_employee()["id"])
        assert resp.json()["assigned_on"] == str(TODAY)

    def test_already_assigned_asset_refused_br1(self, client, staff, make_asset, make_employee, assign):
        asset = make_asset()
        first, second = make_employee(), make_employee()
        assign(asset["id"], first["id"])
        error = assert_error(assign(asset["id"], second["id"]), 409, "ASSET_ALREADY_ASSIGNED", "BR1")
        assert "already held" in error["message"]
        holder = client.get(f"/assets/{asset['id']}", headers=staff).json()["current_holder"]
        assert holder["id"] == first["id"]

    @pytest.mark.parametrize("status", ["in_repair", "retired"])
    def test_unavailable_asset_refused_br2(self, make_asset, make_employee, assign, status):
        asset = make_asset(status=status)
        error = assert_error(assign(asset["id"], make_employee()["id"]), 409, "ASSET_NOT_AVAILABLE", "BR2")
        assert status in error["message"]

    def test_inactive_employee_refused_br5(self, client, staff, make_asset, make_employee, assign):
        asset = make_asset()
        emp = make_employee(is_active=False)
        assert_error(assign(asset["id"], emp["id"]), 409, "EMPLOYEE_INACTIVE", "BR5")
        assert asset_status(client, staff, asset["id"]) == "available"

    def test_unknown_employee_404(self, make_asset, assign):
        assert_error(assign(make_asset()["id"], 9999), 404, "NOT_FOUND")

    def test_unknown_asset_404(self, make_employee, assign):
        assert_error(assign(9999, make_employee()["id"]), 404, "NOT_FOUND")

    def test_future_date_refused(self, make_asset, make_employee, assign):
        resp = assign(make_asset()["id"], make_employee()["id"], assigned_on=str(TODAY + timedelta(days=1)))
        assert_error(resp, 422, "VALIDATION_ERROR")

    def test_date_before_purchase_refused(self, make_asset, make_employee, assign):
        asset = make_asset(purchase_date=str(TODAY - timedelta(days=10)))
        resp = assign(asset["id"], make_employee()["id"], assigned_on=str(TODAY - timedelta(days=11)))
        assert_error(resp, 422, "ASSIGNED_BEFORE_PURCHASE")

    def test_date_overlapping_previous_holder_refused(self, client, staff, make_asset, make_employee, assign):
        asset = make_asset()
        assign(asset["id"], make_employee()["id"], assigned_on=str(TODAY - timedelta(days=20)))
        client.post(
            f"/assets/{asset['id']}/return",
            json={"returned_on": str(TODAY - timedelta(days=5))},
            headers=staff,
        )
        resp = assign(asset["id"], make_employee()["id"], assigned_on=str(TODAY - timedelta(days=10)))
        assert_error(resp, 422, "OVERLAPS_PREVIOUS_ASSIGNMENT", "BR1")

    def test_bad_body_refused(self, client, staff, make_asset):
        asset = make_asset()
        for body in ({}, {"employee_id": 0}, {"employee_id": "abc"}, {"employee_id": 1, "extra": True}):
            assert_error(client.post(f"/assets/{asset['id']}/assignments", json=body, headers=staff), 422)


class TestReturn:
    def test_return_closes_assignment_br4(self, client, staff, make_asset, make_employee, assign):
        asset = make_asset()
        assign(asset["id"], make_employee()["id"], assigned_on=str(TODAY - timedelta(days=3)))
        resp = client.post(f"/assets/{asset['id']}/return", json={"returned_on": str(TODAY)}, headers=staff)
        assert resp.status_code == 200
        assert resp.json()["returned_on"] == str(TODAY)
        detail = client.get(f"/assets/{asset['id']}", headers=staff).json()
        assert detail["status"] == "available"
        assert detail["current_holder"] is None

    def test_returned_asset_can_be_assigned_again(self, client, staff, make_asset, make_employee, assign):
        asset = make_asset()
        assign(asset["id"], make_employee()["id"])
        client.post(f"/assets/{asset['id']}/return", json={}, headers=staff)
        assert assign(asset["id"], make_employee()["id"]).status_code == 201

    def test_return_of_unassigned_asset_refused(self, client, staff, make_asset):
        asset = make_asset()
        resp = client.post(f"/assets/{asset['id']}/return", json={}, headers=staff)
        assert_error(resp, 409, "ASSET_NOT_ASSIGNED", "BR4")

    def test_return_twice_refused(self, client, staff, make_asset, make_employee, assign):
        asset = make_asset()
        assign(asset["id"], make_employee()["id"])
        client.post(f"/assets/{asset['id']}/return", json={}, headers=staff)
        resp = client.post(f"/assets/{asset['id']}/return", json={}, headers=staff)
        assert_error(resp, 409, "ASSET_NOT_ASSIGNED", "BR4")

    def test_return_before_assign_date_refused(self, client, staff, make_asset, make_employee, assign):
        asset = make_asset()
        assign(asset["id"], make_employee()["id"], assigned_on=str(TODAY - timedelta(days=1)))
        resp = client.post(
            f"/assets/{asset['id']}/return",
            json={"returned_on": str(TODAY - timedelta(days=2))},
            headers=staff,
        )
        assert_error(resp, 422, "RETURN_BEFORE_ASSIGNMENT", "BR4")
        assert asset_status(client, staff, asset["id"]) == "assigned"

    def test_return_future_date_refused(self, client, staff, make_asset, make_employee, assign):
        asset = make_asset()
        assign(asset["id"], make_employee()["id"])
        resp = client.post(
            f"/assets/{asset['id']}/return",
            json={"returned_on": str(TODAY + timedelta(days=1))},
            headers=staff,
        )
        assert_error(resp, 422)

    def test_return_unknown_asset_404(self, client, staff):
        assert_error(client.post("/assets/9999/return", json={}, headers=staff), 404)


class TestHistory:
    def test_history_newest_first(self, client, staff, make_asset, make_employee, assign):
        asset = make_asset(purchase_date=str(TODAY - timedelta(days=300)))
        people = [make_employee(full_name=f"Holder {i}") for i in range(3)]
        for i, person in enumerate(people):
            start = TODAY - timedelta(days=100 - i * 30)
            assign(asset["id"], person["id"], assigned_on=str(start))
            client.post(
                f"/assets/{asset['id']}/return",
                json={"returned_on": str(start + timedelta(days=10))},
                headers=staff,
            )

        data = client.get(f"/assets/{asset['id']}/assignments", headers=staff).json()
        assert data["total"] == 3
        assert [a["employee_name"] for a in data["items"]] == ["Holder 2", "Holder 1", "Holder 0"]
        dates = [a["assigned_on"] for a in data["items"]]
        assert dates == sorted(dates, reverse=True)

    def test_history_of_unknown_asset_404(self, client, staff):
        assert_error(client.get("/assets/9999/assignments", headers=staff), 404)


class TestNoPartialRecords:
    """4.6: a refused or failed operation leaves nothing behind."""

    def test_refused_assign_writes_nothing(self, make_asset, make_employee, assign, session_factory):
        asset = make_asset(status="retired")
        assign(asset["id"], make_employee()["id"])
        assert assignment_rows(session_factory, asset["id"]) == 0

    def test_failure_mid_assignment_is_rolled_back(
        self, client, staff, make_asset, make_employee, session_factory, monkeypatch
    ):
        """Make the commit blow up after the row has been added and the status changed."""
        asset, emp = make_asset(), make_employee()

        def failing_commit(self):
            self.flush()  # the INSERT and UPDATE really reach the database...
            raise RuntimeError("disk full")  # ...and then the commit fails

        monkeypatch.setattr("sqlalchemy.orm.Session.commit", failing_commit)
        resp = client.post(
            f"/assets/{asset['id']}/assignments", json={"employee_id": emp["id"]}, headers=staff
        )
        monkeypatch.undo()

        assert_error(resp, 500, "INTERNAL_ERROR")
        assert assignment_rows(session_factory, asset["id"]) == 0
        assert asset_status(client, staff, asset["id"]) == "available"

    def test_database_index_blocks_second_open_assignment(
        self, client, staff, make_asset, make_employee, session_factory, monkeypatch
    ):
        """Simulates two requests racing: both pass the Python check, the database catches the second."""
        asset = make_asset()
        first, second = make_employee(), make_employee()
        assert (
            client.post(
                f"/assets/{asset['id']}/assignments", json={"employee_id": first["id"]}, headers=staff
            ).status_code
            == 201
        )

        # Pretend the second request read the asset before the first one committed
        real_get_asset = assignment_service.get_asset

        def stale_get_asset(db, asset_id):
            found = real_get_asset(db, asset_id)
            set_committed_value(found, "status", AssetStatus.AVAILABLE)
            return found

        monkeypatch.setattr(assignment_service, "get_asset", stale_get_asset)
        resp = client.post(
            f"/assets/{asset['id']}/assignments", json={"employee_id": second["id"]}, headers=staff
        )
        monkeypatch.undo()

        assert_error(resp, 409, "ASSET_ALREADY_ASSIGNED", "BR1")
        assert assignment_rows(session_factory, asset["id"]) == 1
        holder = client.get(f"/assets/{asset['id']}", headers=staff).json()["current_holder"]
        assert holder["id"] == first["id"]

    def test_refused_return_changes_nothing(self, client, staff, make_asset, make_employee, assign):
        asset = make_asset()
        assign(asset["id"], make_employee()["id"])
        client.post(f"/assets/{asset['id']}/return", json={"returned_on": "2000-01-01"}, headers=staff)
        history = client.get(f"/assets/{asset['id']}/assignments", headers=staff).json()
        assert history["items"][0]["returned_on"] is None
        assert asset_status(client, staff, asset["id"]) == "assigned"
