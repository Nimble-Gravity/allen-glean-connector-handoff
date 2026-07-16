"""Tests for GET /query router."""

import pyodbc
import pytest
from fastapi.testclient import TestClient

import main as api_main
from notifications.events import ErrorEvent
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


def _make_fake_conn(monkeypatch, fake_cursor_factory, *, rows, description, fetchone_seq=None):
    conn, cur = fake_cursor_factory(rows=rows, description=description, fetchone_seq=fetchone_seq)
    monkeypatch.setattr("routers.query.get_connection", lambda settings: conn)
    return cur


# --- Happy paths ---


def test_query_happy_path_basic(monkeypatch, recorder, fake_cursor_factory):
    rows = [("Alice", 30), ("Bob", 25)]
    description = [("name",), ("age",)]
    _make_fake_conn(
        monkeypatch,
        fake_cursor_factory,
        rows=rows,
        description=description,
        fetchone_seq=[[1]],
    )
    with _client() as client:
        resp = client.get(
            "/query",
            params={"user_email": "a@sdh.com", "view_name": "vwTest"},
            headers=_auth(),
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["row_count"] == 2
    assert body["data"][0]["name"] == "Alice"


def test_query_happy_path_with_filter(monkeypatch, recorder, fake_cursor_factory):
    cur = _make_fake_conn(
        monkeypatch,
        fake_cursor_factory,
        rows=[("Alice",)],
        description=[("name",)],
        fetchone_seq=[[1]],
    )
    with _client() as client:
        resp = client.get(
            "/query",
            params={
                "user_email": "a@sdh.com",
                "view_name": "vwTest",
                "filter_by_column": "name",
                "filter_value": "Alice",
            },
            headers=_auth(),
        )
    assert resp.status_code == 200
    sql_executed = [e[0] for e in cur.executed]
    assert any("WHERE" in sql for sql in sql_executed)


def test_query_happy_path_with_sort(monkeypatch, recorder, fake_cursor_factory):
    cur = _make_fake_conn(
        monkeypatch,
        fake_cursor_factory,
        rows=[],
        description=[("name",)],
        fetchone_seq=[[1]],
    )
    with _client() as client:
        resp = client.get(
            "/query",
            params={
                "user_email": "a@sdh.com",
                "view_name": "vwTest",
                "sort_by_column": "name",
                "sort_order": "DESC",
            },
            headers=_auth(),
        )
    assert resp.status_code == 200
    sql_executed = [e[0] for e in cur.executed]
    assert any("ORDER BY [name] DESC" in sql for sql in sql_executed)


def test_query_happy_path_with_distinct_column(monkeypatch, recorder, fake_cursor_factory):
    cur = _make_fake_conn(
        monkeypatch,
        fake_cursor_factory,
        rows=[("Alpha",)],
        description=[("division",)],
        fetchone_seq=[[1]],
    )
    with _client() as client:
        resp = client.get(
            "/query",
            params={
                "user_email": "a@sdh.com",
                "view_name": "vwTest",
                "distinct_column": "division",
            },
            headers=_auth(),
        )
    assert resp.status_code == 200
    sql_executed = [e[0] for e in cur.executed]
    assert any("DISTINCT" in sql for sql in sql_executed)


def test_query_happy_path_with_select_columns(monkeypatch, recorder, fake_cursor_factory):
    _make_fake_conn(
        monkeypatch,
        fake_cursor_factory,
        rows=[("Alice",)],
        description=[("name",)],
        fetchone_seq=[[1]],
    )
    with _client() as client:
        resp = client.get(
            "/query",
            params={
                "user_email": "a@sdh.com",
                "view_name": "vwTest",
                "select_columns": "name, age",
            },
            headers=_auth(),
        )
    assert resp.status_code == 200


def test_query_happy_path_distinct_with_filter(monkeypatch, recorder, fake_cursor_factory):
    cur = _make_fake_conn(
        monkeypatch,
        fake_cursor_factory,
        rows=[("Alpha",)],
        description=[("division",)],
        fetchone_seq=[[1]],
    )
    with _client() as client:
        resp = client.get(
            "/query",
            params={
                "user_email": "a@sdh.com",
                "view_name": "vwTest",
                "distinct_column": "division",
                "filter_by_column": "region",
                "filter_value": "West",
            },
            headers=_auth(),
        )
    assert resp.status_code == 200
    sql_executed = [e[0] for e in cur.executed]
    assert any("AND [region] = ?" in sql for sql in sql_executed)


def test_query_effective_limit_respects_smaller_request(monkeypatch, recorder, fake_cursor_factory):
    cur = _make_fake_conn(
        monkeypatch,
        fake_cursor_factory,
        rows=[],
        description=[("x",)],
        fetchone_seq=[[1]],
    )
    with _client() as client:
        resp = client.get(
            "/query",
            params={"user_email": "a@sdh.com", "view_name": "vwTest", "limit": "5"},
            headers=_auth(),
        )
    assert resp.status_code == 200
    # The limit=5 is smaller than max_rows (default 1000), so params should include 5
    select_calls = [e for e in cur.executed if "SELECT TOP" in e[0]]
    assert select_calls
    assert 5 in select_calls[0][1][0]


# --- 400 validation errors ---


@pytest.mark.parametrize(
    "params,expected_status",
    [
        ({"user_email": "a@sdh.com", "view_name": "bad name!"}, 400),
        ({"user_email": "a@sdh.com", "view_name": "vwTest", "filter_by_column": "col; DROP"}, 400),
        ({"user_email": "a@sdh.com", "view_name": "vwTest", "distinct_column": "col!"}, 400),
        ({"user_email": "a@sdh.com", "view_name": "vwTest", "sort_by_column": "col!"}, 400),
        ({"user_email": "a@sdh.com", "view_name": "vwTest", "sort_order": "SIDEWAYS"}, 400),
        (
            {"user_email": "a@sdh.com", "view_name": "vwTest", "sort_order": "ASC"},
            400,
        ),  # no sort_by_column
        ({"user_email": "a@sdh.com", "view_name": "vwTest", "limit": "0"}, 400),
        ({"user_email": "a@sdh.com", "view_name": "vwTest", "select_columns": "  "}, 400),
        (
            {"user_email": "a@sdh.com", "view_name": "vwTest", "select_columns": "valid,bad col!"},
            400,
        ),
    ],
)
def test_query_validation_errors(monkeypatch, recorder, params, expected_status):
    with _client() as client:
        resp = client.get("/query", params=params, headers=_auth())
    assert resp.status_code == expected_status
    assert recorder.events == []


# --- 404 ---


def test_query_view_not_found(monkeypatch, recorder, fake_cursor_factory):
    _make_fake_conn(
        monkeypatch,
        fake_cursor_factory,
        rows=[],
        description=[],
        fetchone_seq=[[0]],  # COUNT = 0 means view doesn't exist
    )
    with _client() as client:
        resp = client.get(
            "/query",
            params={"user_email": "a@sdh.com", "view_name": "vwMissing"},
            headers=_auth(),
        )
    assert resp.status_code == 404


# --- 500 DB errors ---


def test_query_db_error_on_connection(monkeypatch, recorder):
    monkeypatch.setattr(
        "routers.query.get_connection",
        lambda settings: (_ for _ in ()).throw(pyodbc.Error("connection refused")),
    )
    with _client() as client:
        resp = client.get(
            "/query",
            params={"user_email": "a@sdh.com", "view_name": "vwTest"},
            headers=_auth(),
        )
    assert resp.status_code == 500


def test_query_db_error_during_execute(monkeypatch, recorder, fake_cursor_factory):
    conn, cur = fake_cursor_factory(rows=[], description=[], fetchone_seq=[[1]])

    original_execute = cur.execute

    call_count = 0

    def _boom(sql, *params):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            # First call: view-exists check
            original_execute(sql, *params)
        else:
            raise pyodbc.Error("query failed")

    cur.execute = _boom
    monkeypatch.setattr("routers.query.get_connection", lambda settings: conn)

    with _client() as client:
        resp = client.get(
            "/query",
            params={"user_email": "a@sdh.com", "view_name": "vwTest"},
            headers=_auth(),
        )
    assert resp.status_code == 500
