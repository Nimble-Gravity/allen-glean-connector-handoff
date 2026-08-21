"""Tests for GET /metadata router."""

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
    monkeypatch.setattr(api_main, "build_api_notifier", lambda: rec)
    monkeypatch.setattr(api_main, "load_api_key", lambda: "test-key")
    return rec


def _client() -> TestClient:
    return TestClient(api_main.app)


def _auth() -> dict:
    return {"Authorization": "Bearer test-key"}


def _make_fake_conn(monkeypatch, fake_cursor_factory, *, rows, description):
    conn, cur = fake_cursor_factory(rows=rows, description=description)
    monkeypatch.setattr("routers.metadata.get_connection", lambda settings: conn)
    return cur


# --- Happy paths ---


def test_metadata_show_all_views(monkeypatch, recorder, fake_cursor_factory):
    rows = [("vwAlpha",), ("vwBeta",)]
    _make_fake_conn(monkeypatch, fake_cursor_factory, rows=rows, description=[("TABLE_NAME",)])
    with _client() as client:
        resp = client.get(
            "/metadata",
            params={"user_email": "a@sdh.com", "show_all_views": "true"},
            headers=_auth(),
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["views"] == ["vwAlpha", "vwBeta"]


def test_metadata_show_all_views_filters_by_schema(monkeypatch, recorder, fake_cursor_factory):
    cur = _make_fake_conn(
        monkeypatch, fake_cursor_factory, rows=[("vwAlpha",)], description=[("TABLE_NAME",)]
    )
    with _client() as client:
        resp = client.get(
            "/metadata",
            params={"user_email": "a@sdh.com", "show_all_views": "true"},
            headers=_auth(),
        )
    assert resp.status_code == 200
    sql, params = cur.executed[0]
    assert "TABLE_SCHEMA = ?" in sql  # only the configured schema (dbo in tests)
    assert "dbo" in params


def test_metadata_show_view_columns(monkeypatch, recorder, fake_cursor_factory):
    rows = [
        ("LotID", "int", "NO"),
        ("salesPrice", "decimal", "YES"),
        ("CloseDate", "date", "YES"),
    ]
    _make_fake_conn(
        monkeypatch,
        fake_cursor_factory,
        rows=rows,
        description=[("COLUMN_NAME",), ("DATA_TYPE",), ("IS_NULLABLE",)],
    )
    with _client() as client:
        resp = client.get(
            "/metadata",
            params={"user_email": "a@sdh.com", "show_view_columns": "vwTest"},
            headers=_auth(),
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["view"] == "vwTest"
    assert len(body["columns"]) == 3
    assert body["columns"][0]["column_name"] == "LotID"


# --- 404 ---


def test_metadata_view_not_found(monkeypatch, recorder, fake_cursor_factory):
    _make_fake_conn(monkeypatch, fake_cursor_factory, rows=[], description=[])
    with _client() as client:
        resp = client.get(
            "/metadata",
            params={"user_email": "a@sdh.com", "show_view_columns": "vwMissing"},
            headers=_auth(),
        )
    assert resp.status_code == 404


# --- 400 validation errors ---


def test_metadata_both_params_returns_400(monkeypatch, recorder):
    with _client() as client:
        resp = client.get(
            "/metadata",
            params={
                "user_email": "a@sdh.com",
                "show_all_views": "true",
                "show_view_columns": "vwTest",
            },
            headers=_auth(),
        )
    assert resp.status_code == 400
    assert recorder.events == []


def test_metadata_no_params_returns_400(monkeypatch, recorder):
    with _client() as client:
        resp = client.get(
            "/metadata",
            params={"user_email": "a@sdh.com"},
            headers=_auth(),
        )
    assert resp.status_code == 400


def test_metadata_invalid_show_view_columns_returns_400(monkeypatch, recorder):
    with _client() as client:
        resp = client.get(
            "/metadata",
            params={"user_email": "a@sdh.com", "show_view_columns": "bad view!"},
            headers=_auth(),
        )
    assert resp.status_code == 400
    assert recorder.events == []


# --- 500 DB errors ---


def test_metadata_db_error_on_connection(monkeypatch, recorder):
    monkeypatch.setattr(
        "routers.metadata.get_connection",
        lambda settings: (_ for _ in ()).throw(pyodbc.Error("timeout")),
    )
    with _client() as client:
        resp = client.get(
            "/metadata",
            params={"user_email": "a@sdh.com", "show_all_views": "true"},
            headers=_auth(),
        )
    assert resp.status_code == 500
    assert len(recorder.events) == 1
    assert recorder.events[0].error_type == ErrorType.API_REQUEST


def test_metadata_db_error_during_execute(monkeypatch, recorder, fake_cursor_factory):
    conn, cur = fake_cursor_factory(rows=[], description=[])

    def _boom(sql, *params):
        raise pyodbc.Error("execute failed")

    cur.execute = _boom
    monkeypatch.setattr("routers.metadata.get_connection", lambda settings: conn)

    with _client() as client:
        resp = client.get(
            "/metadata",
            params={"user_email": "a@sdh.com", "show_all_views": "true"},
            headers=_auth(),
        )
    assert resp.status_code == 500
