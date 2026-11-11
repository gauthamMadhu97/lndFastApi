"""Section 2: asset records."""

from datetime import date, timedelta

import pytest

from tests.conftest import assert_error

TODAY = date.today()


def asset_body(**overrides):
    return {
        "asset_tag": "lap-1001",
        "name": "Dell Latitude 5440",
        "category": "laptop",
        "serial_number": "DL5440-XYZ",
        "purchase_date": str(TODAY - timedelta(days=100)),
        "warranty_expiry": str(TODAY + timedelta(days=900)),
    } | overrides


class TestCreate:
    def test_create_asset(self, client, admin):
        resp = client.post("/assets", json=asset_body(), headers=admin)
        assert resp.status_code == 201
        data = resp.json()
        assert data["asset_tag"] == "LAP-1001"  # normalised to upper case
        assert data["status"] == "available"
        assert data["category"] == "laptop"

    @pytest.mark.parametrize("category", ["laptop", "monitor", "phone", "peripheral"])
    def test_every_allowed_category_accepted(self, client, admin, category):
        resp = client.post(
            "/assets", json=asset_body(asset_tag=f"T-{category}", category=category), headers=admin
        )
        assert resp.status_code == 201

    @pytest.mark.parametrize("category", ["tablet", "LAPTOP ", "", None])
    def test_unknown_category_refused(self, client, admin, category):
        assert_error(client.post("/assets", json=asset_body(category=category), headers=admin), 422)

    @pytest.mark.parametrize("status", ["available", "in_repair", "retired"])
    def test_settable_statuses_accepted(self, client, admin, status):
        tag = f"S-{status.replace('_', '-')}"
        resp = client.post("/assets", json=asset_body(asset_tag=tag, status=status), headers=admin)
        assert resp.status_code == 201
        assert resp.json()["status"] == status

    def test_unknown_status_refused(self, client, admin):
        assert_error(client.post("/assets", json=asset_body(status="lost"), headers=admin), 422)

    def test_status_assigned_cannot_be_set_directly(self, client, admin):
        error = assert_error(client.post("/assets", json=asset_body(status="assigned"), headers=admin), 422)
        assert "BR3" in error["details"][0]["msg"]

    def test_warranty_before_purchase_refused_br6(self, client, admin):
        body = asset_body(purchase_date="2025-05-01", warranty_expiry="2025-04-30")
        error = assert_error(client.post("/assets", json=body, headers=admin), 422)
        assert "BR6" in error["details"][0]["msg"]

    def test_warranty_same_day_as_purchase_refused_br6(self, client, admin):
        body = asset_body(purchase_date="2025-05-01", warranty_expiry="2025-05-01")
        assert_error(client.post("/assets", json=body, headers=admin), 422)

    def test_future_purchase_date_refused(self, client, admin):
        body = asset_body(
            purchase_date=str(TODAY + timedelta(days=1)), warranty_expiry=str(TODAY + timedelta(days=400))
        )
        assert_error(client.post("/assets", json=body, headers=admin), 422)

    def test_duplicate_tag_refused_br8(self, client, admin):
        client.post("/assets", json=asset_body(), headers=admin)
        resp = client.post(
            "/assets", json=asset_body(asset_tag="LAP-1001", serial_number="OTHER"), headers=admin
        )
        assert_error(resp, 409, "DUPLICATE_ASSET_TAG", "BR8")

    @pytest.mark.parametrize("tag", ["ab", "has space", "x" * 33, "tag/slash"])
    def test_bad_tag_format_refused(self, client, admin, tag):
        assert_error(client.post("/assets", json=asset_body(asset_tag=tag), headers=admin), 422)

    def test_bad_date_refused(self, client, admin):
        assert_error(client.post("/assets", json=asset_body(purchase_date="2025-13-40"), headers=admin), 422)


class TestRetrieve:
    def test_get_available_asset_has_no_holder(self, client, staff, make_asset):
        asset = make_asset()
        resp = client.get(f"/assets/{asset['id']}", headers=staff)
        assert resp.status_code == 200
        assert resp.json()["current_holder"] is None

    def test_get_assigned_asset_shows_holder(self, client, staff, make_asset, make_employee, assign):
        asset = make_asset()
        emp = make_employee(full_name="Meera Iyer")
        assign(asset["id"], emp["id"])
        data = client.get(f"/assets/{asset['id']}", headers=staff).json()
        assert data["status"] == "assigned"
        assert data["current_holder"]["id"] == emp["id"]
        assert data["current_holder"]["full_name"] == "Meera Iyer"
        assert data["current_holder"]["assigned_on"] == str(TODAY)

    def test_get_missing_asset_404(self, client, staff):
        assert_error(client.get("/assets/4242", headers=staff), 404, "NOT_FOUND")


class TestUpdate:
    def test_patch_name_and_status(self, client, admin, make_asset):
        asset = make_asset()
        resp = client.patch(
            f"/assets/{asset['id']}", json={"name": "Renamed", "status": "in_repair"}, headers=admin
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Renamed"
        assert resp.json()["status"] == "in_repair"
        assert resp.json()["asset_tag"] == asset["asset_tag"]

    def test_patch_warranty_against_stored_purchase_date_br6(self, client, admin, make_asset):
        asset = make_asset(purchase_date="2024-01-01", warranty_expiry="2026-01-01")
        resp = client.patch(f"/assets/{asset['id']}", json={"warranty_expiry": "2023-12-31"}, headers=admin)
        assert_error(resp, 422, "WARRANTY_BEFORE_PURCHASE", "BR6")

    def test_patch_bad_category_refused(self, client, admin, make_asset):
        asset = make_asset()
        assert_error(client.patch(f"/assets/{asset['id']}", json={"category": "car"}, headers=admin), 422)

    def test_patch_status_to_assigned_refused(self, client, admin, make_asset):
        asset = make_asset()
        assert_error(client.patch(f"/assets/{asset['id']}", json={"status": "assigned"}, headers=admin), 422)

    def test_patch_status_of_assigned_asset_refused(self, client, admin, make_asset, make_employee, assign):
        asset = make_asset()
        assign(asset["id"], make_employee()["id"])
        resp = client.patch(f"/assets/{asset['id']}", json={"status": "retired"}, headers=admin)
        assert_error(resp, 409, "ASSET_IS_ASSIGNED", "BR4")

    def test_patch_to_taken_tag_refused_br8(self, client, admin, make_asset):
        make_asset(asset_tag="TAKEN-1")
        asset = make_asset()
        resp = client.patch(f"/assets/{asset['id']}", json={"asset_tag": "taken-1"}, headers=admin)
        assert_error(resp, 409, "DUPLICATE_ASSET_TAG", "BR8")

    def test_patch_missing_asset_404(self, client, admin):
        assert_error(client.patch("/assets/4242", json={"name": "x"}, headers=admin), 404)


class TestDelete:
    def test_delete_asset_and_its_history(self, client, admin, staff, make_asset, make_employee, assign):
        asset = make_asset()
        assign(asset["id"], make_employee()["id"])
        client.post(f"/assets/{asset['id']}/return", json={}, headers=staff)

        assert client.delete(f"/assets/{asset['id']}", headers=admin).status_code == 204
        assert client.get(f"/assets/{asset['id']}", headers=admin).status_code == 404

    def test_delete_assigned_asset_refused(self, client, admin, make_asset, make_employee, assign):
        asset = make_asset()
        assign(asset["id"], make_employee()["id"])
        assert_error(client.delete(f"/assets/{asset['id']}", headers=admin), 409, "ASSET_IS_ASSIGNED")

    def test_delete_missing_asset_404(self, client, admin):
        assert_error(client.delete("/assets/4242", headers=admin), 404)
