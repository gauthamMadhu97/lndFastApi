"""Section 3: listing, filtering, search and paging."""

import pytest

from tests.conftest import assert_error


@pytest.fixture
def inventory(client, admin, make_asset):
    make_asset(asset_tag="LAP-0001", name="Dell Latitude", category="laptop")
    make_asset(asset_tag="LAP-0002", name="ThinkPad T14", category="laptop", status="in_repair")
    make_asset(asset_tag="MON-0001", name="Dell UltraSharp", category="monitor")
    make_asset(asset_tag="PHN-0001", name="Pixel 8", category="phone", status="retired")
    make_asset(asset_tag="PER-0001", name="MX Keys 50% off", category="peripheral")


def tags(resp):
    return [a["asset_tag"] for a in resp.json()["items"]]


class TestFilter:
    def test_list_everything(self, client, staff, inventory):
        resp = client.get("/assets", headers=staff)
        assert resp.status_code == 200
        assert resp.json()["total"] == 5

    def test_filter_by_status(self, client, staff, inventory):
        resp = client.get("/assets", params={"status": "available"}, headers=staff)
        assert tags(resp) == ["LAP-0001", "MON-0001", "PER-0001"]

    def test_filter_by_category(self, client, staff, inventory):
        resp = client.get("/assets", params={"category": "laptop"}, headers=staff)
        assert tags(resp) == ["LAP-0001", "LAP-0002"]

    def test_filter_by_status_and_category(self, client, staff, inventory):
        resp = client.get("/assets", params={"category": "laptop", "status": "in_repair"}, headers=staff)
        assert tags(resp) == ["LAP-0002"]
        assert resp.json()["total"] == 1


class TestSearch:
    def test_search_by_name_case_insensitive(self, client, staff, inventory):
        resp = client.get("/assets", params={"q": "dell"}, headers=staff)
        assert tags(resp) == ["LAP-0001", "MON-0001"]

    def test_search_by_partial_tag(self, client, staff, inventory):
        assert tags(client.get("/assets", params={"q": "lap-"}, headers=staff)) == ["LAP-0001", "LAP-0002"]

    def test_search_combined_with_filter(self, client, staff, inventory):
        resp = client.get("/assets", params={"q": "dell", "category": "monitor"}, headers=staff)
        assert tags(resp) == ["MON-0001"]

    def test_search_no_match_is_empty_not_error(self, client, staff, inventory):
        resp = client.get("/assets", params={"q": "macbook"}, headers=staff)
        assert resp.status_code == 200
        assert resp.json() == {"items": [], "total": 0, "page": 1, "size": 20}

    def test_wildcard_characters_are_literal(self, client, staff, inventory):
        assert tags(client.get("/assets", params={"q": "50%"}, headers=staff)) == ["PER-0001"]
        assert tags(client.get("/assets", params={"q": "%"}, headers=staff)) == ["PER-0001"]


class TestPaging:
    def test_pages_and_total(self, client, staff, make_asset):
        for i in range(25):
            make_asset(asset_tag=f"BULK-{i:03d}")

        first = client.get("/assets", params={"size": 10}, headers=staff).json()
        assert first["total"] == 25
        assert len(first["items"]) == 10
        assert first["page"] == 1

        last = client.get("/assets", params={"size": 10, "page": 3}, headers=staff).json()
        assert len(last["items"]) == 5
        assert last["total"] == 25

        beyond = client.get("/assets", params={"size": 10, "page": 9}, headers=staff).json()
        assert beyond["items"] == []
        assert beyond["total"] == 25

    def test_pages_do_not_overlap(self, client, staff, make_asset):
        for i in range(6):
            make_asset(asset_tag=f"PG-{i:03d}")
        p1 = tags(client.get("/assets", params={"size": 3, "page": 1}, headers=staff))
        p2 = tags(client.get("/assets", params={"size": 3, "page": 2}, headers=staff))
        assert not set(p1) & set(p2)

    def test_employee_list_is_paged_too(self, client, staff, make_employee):
        for _ in range(4):
            make_employee()
        data = client.get("/employees", params={"size": 3}, headers=staff).json()
        assert len(data["items"]) == 3
        assert data["total"] == 4


class TestRefused:
    @pytest.mark.parametrize(
        "params",
        [
            {"status": "broken"},
            {"category": "tablet"},
            {"status": "AVAILABLE"},
            {"page": 0},
            {"page": -1},
            {"size": 0},
            {"size": 101},
            {"size": "ten"},
            {"q": ""},
            {"q": "x" * 101},
            {"colour": "red"},
        ],
    )
    def test_disallowed_values_refused(self, client, staff, params):
        error = assert_error(client.get("/assets", params=params, headers=staff), 422, "VALIDATION_ERROR")
        assert error["details"][0]["loc"][0] == "query"

    def test_disallowed_value_in_history_paging(self, client, staff, make_asset):
        asset = make_asset()
        resp = client.get(f"/assets/{asset['id']}/assignments", params={"size": 500}, headers=staff)
        assert_error(resp, 422)
