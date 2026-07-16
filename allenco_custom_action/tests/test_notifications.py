"""Tests for error-notification wiring in the Custom Action API.

Uses FastAPI's TestClient with the notifier and DB connection replaced by fakes,
so no real email/webhook or SQL Server is touched.
"""

import pyodbc
import pytest
from fastapi.testclient import TestClient

import main as api_main
from notifications.events import ErrorEvent, ErrorType
from notifications.senders.base import Notifier


class RecordingNotifier(Notifier):
    name = "recording"

    def __init__(self):
        self.events: list[ErrorEvent] = []

    def send(self, event: ErrorEvent) -> None:
        self.events.append(event)


@pytest.fixture
def recorder(monkeypatch) -> RecordingNotifier:
    rec = RecordingNotifier()
    # build_api_notifier is called in the lifespan; return our recorder instead.
    monkeypatch.setattr(api_main, "build_api_notifier", lambda: rec)
    # Pin the API key so auth is deterministic regardless of the real .env.
    monkeypatch.setattr(api_main, "load_api_key", lambda: "test-key")
    return rec


def _client() -> TestClient:
    return TestClient(api_main.app)


def _auth() -> dict:
    return {"Authorization": "Bearer test-key"}


def test_db_error_on_query_notifies(monkeypatch, recorder):
    def _boom(settings, **kwargs):
        raise pyodbc.Error("connection refused")

    monkeypatch.setattr("routers.query.get_connection", _boom)

    with _client() as client:
        resp = client.get(
            "/query",
            params={"user_email": "a@sdh.com", "view_name": "vwTest"},
            headers=_auth(),
        )

    assert resp.status_code == 500
    assert len(recorder.events) == 1
    event = recorder.events[0]
    assert event.error_type == ErrorType.API_REQUEST
    assert "GET /query" in event.message
    assert event.connector_name == "Allen & Co Custom Action API"
    assert event.recommended_resolution


def test_db_error_on_metadata_notifies(monkeypatch, recorder):
    def _boom(settings, **kwargs):
        raise pyodbc.Error("login timeout")

    monkeypatch.setattr("routers.metadata.get_connection", _boom)

    with _client() as client:
        resp = client.get(
            "/metadata",
            params={"user_email": "a@sdh.com", "show_all_views": "true"},
            headers=_auth(),
        )

    assert resp.status_code == 500
    assert [e.error_type for e in recorder.events] == [ErrorType.API_REQUEST]


def test_validation_error_does_not_notify(monkeypatch, recorder):
    # A 400 (bad view_name) must NOT trigger an alert — only DB failures do.
    with _client() as client:
        resp = client.get(
            "/query",
            params={"user_email": "a@sdh.com", "view_name": "bad name!"},
            headers=_auth(),
        )

    assert resp.status_code == 400
    assert recorder.events == []


def test_startup_failure_notifies(monkeypatch, recorder):
    def _boom():
        raise OSError("Required environment variable 'DB_SERVER' is not set.")

    monkeypatch.setattr(api_main, "load_db_settings", _boom)

    with pytest.raises(OSError):
        with _client():
            pass

    assert [e.error_type for e in recorder.events] == [ErrorType.API_STARTUP]
