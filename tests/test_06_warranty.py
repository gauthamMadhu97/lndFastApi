"""Section 6: bulk warranty enquiry."""

import asyncio
import time
from datetime import date, timedelta

import pytest

from app.integrations.warranty_client import StubWarrantyClient
from tests.conftest import assert_error

TODAY = date.today()


@pytest.fixture
def twenty_assets(make_asset):
    return [make_asset(asset_tag=f"WTY-{i:03d}")["asset_tag"] for i in range(20)]


def check(client, headers, tags):
    return client.post("/warranty-checks", json={"asset_tags": tags}, headers=headers)


def test_single_asset(client, staff, make_asset):
    asset = make_asset(warranty_expiry=str(TODAY + timedelta(days=30)))
    resp = check(client, staff, [asset["asset_tag"]])
    assert resp.status_code == 200
    result = resp.json()["results"][0]
    assert result == {
        "asset_tag": asset["asset_tag"],
        "ok": True,
        "in_warranty": True,
        "warranty_expiry": str(TODAY + timedelta(days=30)),
        "days_remaining": 30,
        "error": None,
    }


def test_expired_warranty_reported(client, staff, make_asset):
    asset = make_asset(purchase_date="2020-01-01", warranty_expiry="2022-01-01")
    result = check(client, staff, [asset["asset_tag"]]).json()["results"][0]
    assert result["ok"] is True
    assert result["in_warranty"] is False
    assert result["days_remaining"] == 0


def test_twenty_assets_take_about_as_long_as_one(client, staff, twenty_assets):
    # the stub takes 0.5s per asset: one after another would be ~10s
    started = time.perf_counter()
    check(client, staff, twenty_assets[:1])
    one = time.perf_counter() - started

    started = time.perf_counter()
    resp = check(client, staff, twenty_assets)
    twenty = time.perf_counter() - started

    assert resp.status_code == 200
    assert resp.json()["succeeded"] == 20
    assert twenty < one + 0.5, f"1 asset: {one:.2f}s, 20 assets: {twenty:.2f}s"


def test_results_keep_request_order(client, staff, twenty_assets):
    tags = list(reversed(twenty_assets[:5]))
    results = check(client, staff, tags).json()["results"]
    assert [r["asset_tag"] for r in results] == tags


def test_one_failure_does_not_lose_the_rest(client, staff, app, twenty_assets):
    app.state.warranty_client = StubWarrantyClient(delay=0.05, failing_tags={"WTY-007"})
    data = check(client, staff, twenty_assets).json()
    assert data["succeeded"] == 19
    assert data["failed"] == 1
    failed = [r for r in data["results"] if not r["ok"]]
    assert failed[0]["asset_tag"] == "WTY-007"
    assert "lookup failed" in failed[0]["error"]


def test_hanging_lookup_times_out_without_blocking_others(client, staff, app, settings, twenty_assets):
    class HangsOnOne(StubWarrantyClient):
        async def check(self, asset_tag, warranty_expiry):
            if asset_tag == "WTY-003":
                await asyncio.sleep(30)
            return await super().check(asset_tag, warranty_expiry)

    app.state.warranty_client = HangsOnOne(delay=0.05)
    settings.warranty_timeout_seconds = 0.5

    started = time.perf_counter()
    data = check(client, staff, twenty_assets[:5]).json()
    assert time.perf_counter() - started < 2
    assert data["succeeded"] == 4
    assert data["results"][3] == {
        "asset_tag": "WTY-003",
        "ok": False,
        "in_warranty": None,
        "warranty_expiry": None,
        "days_remaining": None,
        "error": "warranty lookup failed: timed out",
    }


def test_unknown_tag_reported_others_returned(client, staff, twenty_assets):
    data = check(client, staff, [twenty_assets[0], "NOPE-999"]).json()
    assert data["succeeded"] == 1
    assert data["results"][1] == {
        "asset_tag": "NOPE-999",
        "ok": False,
        "in_warranty": None,
        "warranty_expiry": None,
        "days_remaining": None,
        "error": "asset not found",
    }


@pytest.mark.parametrize(
    "tags",
    [
        [],
        [f"T-{i:03d}" for i in range(51)],
        ["LAP-0001", "lap-0001"],
        ["bad tag!"],
    ],
)
def test_bad_request_refused(client, staff, tags):
    assert_error(check(client, staff, tags), 422, "VALIDATION_ERROR")


def test_missing_body_refused(client, staff):
    assert_error(client.post("/warranty-checks", json={}, headers=staff), 422)
