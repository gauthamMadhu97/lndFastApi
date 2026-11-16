"""Section 8: request reference, timing, access log, CORS."""

import json
import logging
import re

import pytest
from fastapi.testclient import TestClient

from app.core.logging import JsonFormatter
from tests.conftest import assert_error

ALLOWED_ORIGIN = "http://localhost:5173"


def access_records(caplog):
    return [r for r in caplog.records if r.name == "assetdesk.access"]


@pytest.fixture
def boom_client(app):
    """A client for an app with an extra route that always crashes."""

    def boom() -> None:
        raise RuntimeError("simulated bug")

    app.add_api_route("/boom", boom, methods=["GET"])
    with TestClient(app, raise_server_exceptions=False) as c:
        yield c


class TestRequestReference:
    def test_every_response_has_a_reference(self, client):
        ids = {client.get("/health").headers["X-Request-ID"] for _ in range(5)}
        assert len(ids) == 5
        assert all(re.fullmatch(r"[0-9a-f]{32}", i) for i in ids)

    def test_reference_matches_error_body(self, client, staff):
        resp = client.get("/assets/999", headers=staff)
        assert resp.json()["error"]["request_id"] == resp.headers["X-Request-ID"]

    def test_caller_supplied_reference_is_kept(self, client):
        resp = client.get("/health", headers={"X-Request-ID": "trace-abc-12345"})
        assert resp.headers["X-Request-ID"] == "trace-abc-12345"

    @pytest.mark.parametrize("bad", ["short", "has spaces in it", "x" * 65, 'inject"quote"here'])
    def test_unsafe_caller_reference_is_replaced(self, client, bad):
        resp = client.get("/health", headers={"X-Request-ID": bad})
        assert resp.headers["X-Request-ID"] != bad
        assert re.fullmatch(r"[0-9a-f]{32}", resp.headers["X-Request-ID"])


class TestTiming:
    def test_time_taken_returned(self, client):
        value = client.get("/health").headers["X-Process-Time-Ms"]
        assert float(value) >= 0

    def test_slow_request_reports_longer_time(self, client, staff, make_asset):
        tag = make_asset()["asset_tag"]
        resp = client.post("/warranty-checks", json={"asset_tags": [tag]}, headers=staff)
        assert float(resp.headers["X-Process-Time-Ms"]) >= 450  # stub waits 0.5s


class TestAccessLog:
    def test_successful_request_logged(self, client, staff, make_asset, caplog):
        asset = make_asset()
        with caplog.at_level(logging.INFO, logger="assetdesk"):
            resp = client.get(f"/assets/{asset['id']}", headers=staff)
        fields = access_records(caplog)[-1].fields
        assert fields["method"] == "GET"
        assert fields["path"] == "/assets/{asset_id}"
        assert fields["operation"] == "get_asset"
        assert fields["status"] == 200
        assert fields["outcome"] == "success"
        assert fields["duration_ms"] >= 0
        assert fields["request_id"] == resp.headers["X-Request-ID"]

    def test_failed_request_logged(self, client, staff, make_asset, make_employee, caplog):
        asset, emp = make_asset(status="retired"), make_employee()
        with caplog.at_level(logging.INFO, logger="assetdesk"):
            resp = client.post(
                f"/assets/{asset['id']}/assignments", json={"employee_id": emp["id"]}, headers=staff
            )
        fields = access_records(caplog)[-1].fields
        assert fields["status"] == 409
        assert fields["outcome"] == "failure"
        assert fields["operation"] == "assign_asset"
        assert fields["request_id"] == resp.headers["X-Request-ID"]

    def test_unknown_route_logged(self, client, caplog):
        with caplog.at_level(logging.INFO, logger="assetdesk"):
            client.get("/does-not-exist")
        fields = access_records(caplog)[-1].fields
        assert fields["status"] == 404
        assert fields["path"] == "/does-not-exist"

    def test_log_line_is_json(self, client, caplog):
        with caplog.at_level(logging.INFO, logger="assetdesk"):
            client.get("/health")
        line = json.loads(JsonFormatter().format(access_records(caplog)[-1]))
        assert {"ts", "level", "msg", "method", "path", "status", "duration_ms", "request_id"} <= line.keys()


class TestFailedRequestsToo:
    @pytest.mark.parametrize(
        "method,path,expected",
        [
            ("GET", "/assets", 401),
            ("GET", "/nowhere", 404),
            ("PUT", "/health", 405),
        ],
    )
    def test_headers_on_errors(self, client, method, path, expected):
        resp = client.request(method, path)
        assert resp.status_code == expected
        assert resp.headers["X-Request-ID"]
        assert float(resp.headers["X-Process-Time-Ms"]) >= 0

    def test_headers_on_validation_error(self, client, staff):
        resp = client.get("/assets", params={"status": "x"}, headers=staff)
        assert_error(resp, 422)
        assert "X-Process-Time-Ms" in resp.headers

    def test_unhandled_error_gets_reference_and_json(self, boom_client, caplog):
        with caplog.at_level(logging.INFO, logger="assetdesk"):
            resp = boom_client.get("/boom")
        error = assert_error(resp, 500, "INTERNAL_ERROR")
        assert "simulated bug" not in error["message"]  # no internals leaked to the caller
        assert float(resp.headers["X-Process-Time-Ms"]) >= 0
        assert access_records(caplog)[-1].fields["status"] == 500
        assert "simulated bug" in caplog.text  # but it is in our logs


class TestCors:
    def test_preflight_from_allowed_origin(self, client):
        resp = client.options(
            "/assets",
            headers={
                "Origin": ALLOWED_ORIGIN,
                "Access-Control-Request-Method": "POST",
                "Access-Control-Request-Headers": "Authorization, Content-Type",
            },
        )
        assert resp.status_code == 200
        assert resp.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
        assert "POST" in resp.headers["Access-Control-Allow-Methods"]
        assert resp.headers["X-Request-ID"]

    def test_preflight_from_other_origin_refused(self, client):
        resp = client.options(
            "/assets",
            headers={
                "Origin": "http://evil.example.com",
                "Access-Control-Request-Method": "GET",
            },
        )
        assert resp.status_code == 400
        assert "Access-Control-Allow-Origin" not in resp.headers

    def test_browser_can_read_reference_headers(self, client, staff):
        resp = client.get("/assets", headers={**staff, "Origin": ALLOWED_ORIGIN})
        assert resp.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
        exposed = resp.headers["Access-Control-Expose-Headers"]
        assert "X-Request-ID" in exposed
        assert "X-Process-Time-Ms" in exposed

    def test_simple_request_from_other_origin_gets_no_cors_header(self, client):
        resp = client.get("/health", headers={"Origin": "http://evil.example.com"})
        assert "Access-Control-Allow-Origin" not in resp.headers

    def test_cors_headers_on_a_crash(self, boom_client):
        resp = boom_client.get("/boom", headers={"Origin": ALLOWED_ORIGIN})
        assert resp.status_code == 500
        assert resp.headers["Access-Control-Allow-Origin"] == ALLOWED_ORIGIN
