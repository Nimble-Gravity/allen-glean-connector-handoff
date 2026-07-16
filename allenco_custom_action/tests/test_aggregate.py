"""Tests for GET /aggregate router."""

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


def _make_fake_conn(monkeypatch, fake_cursor_factory, *, rows, description, fetchone_seq=None):
    conn, cur = fake_cursor_factory(rows=rows, description=description, fetchone_seq=fetchone_seq)
    monkeypatch.setattr("routers.aggregate.get_connection", lambda settings: conn)
    return cur


# --- Happy paths ---


def test_aggregate_count(monkeypatch, recorder, fake_cursor_factory):
    _make_fake_conn(
        monkeypatch,
        fake_cursor_factory,
        rows=[(42,)],
        description=[("count",)],
        fetchone_seq=[[1]],
    )
    with _client() as client:
        resp = client.get(
            "/aggregate",
            params={
                "user_email": "a@sdh.com",
                "view_name": "vwTest",
                "aggregation": "count",
            },
            headers=_auth(),
        )
    assert resp.status_code == 200
    body = resp.json()
    assert body["row_count"] == 1
    assert body["data"][0]["count"] == 42


def test_aggregate_sum(monkeypatch, recorder, fake_cursor_factory):
    cur = _make_fake_conn(
        monkeypatch,
        fake_cursor_factory,
        rows=[(1_000_000.0,)],
        description=[("sum",)],
        fetchone_seq=[[1]],
    )
    with _client() as client:
        resp = client.get(
            "/aggregate",
            params={
                "user_email": "a@sdh.com",
                "view_name": "vwTest",
                "aggregation": "sum",
                "agg_column": "salesPrice",
            },
            headers=_auth(),
        )
    assert resp.status_code == 200
    sql_executed = [e[0] for e in cur.executed]
    assert any("SUM([salesPrice])" in sql for sql in sql_executed)


def test_aggregate_avg(monkeypatch, recorder, fake_cursor_factory):
    cur = _make_fake_conn(
        monkeypatch,
        fake_cursor_factory,
        rows=[(450_000.0,)],
        description=[("avg",)],
        fetchone_seq=[[1]],
    )
    with _client() as client:
        resp = client.get(
            "/aggregate",
            params={
                "user_email": "a@sdh.com",
                "view_name": "vwTest",
                "aggregation": "avg",
                "agg_column": "salesPrice",
            },
            headers=_auth(),
        )
    assert resp.status_code == 200
    sql_executed = [e[0] for e in cur.executed]
    assert any("AVG([salesPrice])" in sql for sql in sql_executed)


def test_aggregate_min_and_max(monkeypatch, recorder, fake_cursor_factory):
    for agg in ("min", "max"):
        _make_fake_conn(
            monkeypatch,
            fake_cursor_factory,
            rows=[(100.0,)],
            description=[(agg,)],
            fetchone_seq=[[1]],
        )
        with _client() as client:
            resp = client.get(
                "/aggregate",
                params={
                    "user_email": "a@sdh.com",
                    "view_name": "vwTest",
                    "aggregation": agg,
                    "agg_column": "salesPrice",
                },
                headers=_auth(),
            )
        assert resp.status_code == 200


def test_aggregate_with_group_by(monkeypatch, recorder, fake_cursor_factory):
    rows = [("Alpha", 5), ("Beta", 3)]
    description = [("Division",), ("count",)]
    cur = _make_fake_conn(
        monkeypatch,
        fake_cursor_factory,
        rows=rows,
        description=description,
        fetchone_seq=[[1]],
    )
    with _client() as client:
        resp = client.get(
            "/aggregate",
            params={
                "user_email": "a@sdh.com",
                "view_name": "vwTest",
                "aggregation": "count",
                "group_by_column": "Division",
            },
            headers=_auth(),
        )
    assert resp.status_code == 200
    sql_executed = [e[0] for e in cur.executed]
    assert any("GROUP BY [Division]" in sql for sql in sql_executed)


def test_aggregate_with_filter(monkeypatch, recorder, fake_cursor_factory):
    cur = _make_fake_conn(
        monkeypatch,
        fake_cursor_factory,
        rows=[(2,)],
        description=[("count",)],
        fetchone_seq=[[1]],
    )
    with _client() as client:
        resp = client.get(
            "/aggregate",
            params={
                "user_email": "a@sdh.com",
                "view_name": "vwTest",
                "aggregation": "count",
                "filter_by_column": "Division",
                "filter_value": "West",
            },
            headers=_auth(),
        )
    assert resp.status_code == 200
    sql_executed = [e[0] for e in cur.executed]
    assert any("WHERE [Division] = ?" in sql for sql in sql_executed)


# --- 400 validation errors ---


@pytest.mark.parametrize(
    "params,expected_status",
    [
        # Invalid aggregation function
        ({"user_email": "a@sdh.com", "view_name": "vwTest", "aggregation": "median"}, 400),
        # Non-count without agg_column
        ({"user_email": "a@sdh.com", "view_name": "vwTest", "aggregation": "sum"}, 400),
        # Invalid view_name
        ({"user_email": "a@sdh.com", "view_name": "bad view!", "aggregation": "count"}, 400),
        # Invalid agg_column
        (
            {
                "user_email": "a@sdh.com",
                "view_name": "vwTest",
                "aggregation": "sum",
                "agg_column": "col!",
            },
            400,
        ),
        # Invalid group_by_column
        (
            {
                "user_email": "a@sdh.com",
                "view_name": "vwTest",
                "aggregation": "count",
                "group_by_column": "col!",
            },
            400,
        ),
        # Invalid filter_by_column
        (
            {
                "user_email": "a@sdh.com",
                "view_name": "vwTest",
                "aggregation": "count",
                "filter_by_column": "col!",
            },
            400,
        ),
    ],
)
def test_aggregate_validation_errors(monkeypatch, recorder, params, expected_status):
    with _client() as client:
        resp = client.get("/aggregate", params=params, headers=_auth())
    assert resp.status_code == expected_status
    assert recorder.events == []


# --- 404 ---


def test_aggregate_view_not_found(monkeypatch, recorder, fake_cursor_factory):
    _make_fake_conn(
        monkeypatch,
        fake_cursor_factory,
        rows=[],
        description=[],
        fetchone_seq=[[0]],
    )
    with _client() as client:
        resp = client.get(
            "/aggregate",
            params={
                "user_email": "a@sdh.com",
                "view_name": "vwMissing",
                "aggregation": "count",
            },
            headers=_auth(),
        )
    assert resp.status_code == 404


# --- 500 DB errors ---


def test_aggregate_db_error_on_connection(monkeypatch, recorder):
    monkeypatch.setattr(
        "routers.aggregate.get_connection",
        lambda settings: (_ for _ in ()).throw(pyodbc.Error("timeout")),
    )
    with _client() as client:
        resp = client.get(
            "/aggregate",
            params={
                "user_email": "a@sdh.com",
                "view_name": "vwTest",
                "aggregation": "count",
            },
            headers=_auth(),
        )
    assert resp.status_code == 500
    assert len(recorder.events) == 1
    assert recorder.events[0].error_type == ErrorType.API_REQUEST


def test_aggregate_db_error_during_execute(monkeypatch, recorder, fake_cursor_factory):
    conn, cur = fake_cursor_factory(rows=[], description=[], fetchone_seq=[[1]])

    call_count = 0

    def _boom(sql, *params):
        nonlocal call_count
        call_count += 1
        if call_count == 1:
            cur.executed.append((sql, params))
        else:
            raise pyodbc.Error("execute failed")

    cur.execute = _boom
    monkeypatch.setattr("routers.aggregate.get_connection", lambda settings: conn)

    with _client() as client:
        resp = client.get(
            "/aggregate",
            params={
                "user_email": "a@sdh.com",
                "view_name": "vwTest",
                "aggregation": "count",
            },
            headers=_auth(),
        )
    assert resp.status_code == 500
