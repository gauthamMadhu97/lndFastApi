"""Section 5: notifying the external system on assign/return."""

import logging
import socket
import threading
import time

import httpx
import pytest
import uvicorn

from app.integrations.notifier import StubNotifier
from tests.conftest import STAFF


@pytest.fixture
def live_server(app):
    """Runs the app under a real Uvicorn server in a thread.

    Needed for 5.2: TestClient waits for background tasks before it returns,
    so it can't show that the caller isn't kept waiting.
    """
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        if time.monotonic() > deadline:
            raise RuntimeError("test server did not start")
        time.sleep(0.02)
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(timeout=5)


def test_assign_and_return_are_notified(client, staff, app, make_asset, make_employee, assign):
    asset, emp = make_asset(), make_employee()
    assign(asset["id"], emp["id"])
    client.post(f"/assets/{asset['id']}/return", json={}, headers=staff)

    calls = app.state.notifier.calls
    assert [c.event for c in calls] == ["asset.assigned", "asset.returned"]
    assert calls[0].asset_id == asset["id"]
    assert calls[0].asset_tag == asset["asset_tag"]
    assert calls[0].employee_id == emp["id"]


def test_refused_assignment_is_not_notified(app, make_asset, make_employee, assign):
    resp = assign(make_asset(status="retired")["id"], make_employee()["id"])
    assert resp.status_code == 409
    assert app.state.notifier.calls == []


def test_caller_is_not_kept_waiting(app, live_server, make_asset, make_employee):
    slow = StubNotifier(delay=2.0)
    app.state.notifier = slow
    asset, emp = make_asset(), make_employee()

    with httpx.Client(base_url=live_server, timeout=10) as http:
        token = http.post("/auth/token", data={"username": STAFF[0], "password": STAFF[1]}).json()
        headers = {"Authorization": f"Bearer {token['access_token']}"}

        started = time.perf_counter()
        resp = http.post(
            f"/assets/{asset['id']}/assignments", json={"employee_id": emp["id"]}, headers=headers
        )
        elapsed = time.perf_counter() - started

    assert resp.status_code == 201
    assert elapsed < 1.0, f"response took {elapsed:.2f}s, notifier takes 2s"
    assert slow.calls == []  # not delivered yet when the caller got the answer

    deadline = time.monotonic() + 5
    while not slow.calls and time.monotonic() < deadline:
        time.sleep(0.05)
    assert len(slow.calls) == 1, "notification should arrive after the response"


def test_failed_notification_does_not_undo_assignment(client, staff, app, make_asset, make_employee, caplog):
    app.state.notifier = StubNotifier(delay=0, fail=True)
    asset, emp = make_asset(), make_employee()

    with caplog.at_level(logging.ERROR, logger="assetdesk.notifier"):
        resp = client.post(
            f"/assets/{asset['id']}/assignments", json={"employee_id": emp["id"]}, headers=staff
        )

    assert resp.status_code == 201
    assert client.get(f"/assets/{asset['id']}", headers=staff).json()["status"] == "assigned"
    assert "notification failed" in caplog.text


def test_failed_notification_does_not_undo_return(client, staff, app, make_asset, make_employee, assign):
    asset = make_asset()
    assign(asset["id"], make_employee()["id"])
    app.state.notifier = StubNotifier(delay=0, fail=True)

    resp = client.post(f"/assets/{asset['id']}/return", json={}, headers=staff)
    assert resp.status_code == 200
    assert client.get(f"/assets/{asset['id']}", headers=staff).json()["status"] == "available"
