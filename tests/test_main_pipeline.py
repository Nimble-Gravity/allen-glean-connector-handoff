"""Tests for the indexer pipeline's per-view resilience (main._fetch_all_views)."""

import pandas as pd
import pyodbc

from main import _fetch_all_views
from notifications.events import ErrorType


class _FakeSpec:
    """A stand-in ViewSpec: returns a canned DataFrame, or raises to simulate a bad view."""

    def __init__(self, name, df=None, boom=None):
        self.view_name = name
        self._df = df if df is not None else pd.DataFrame({"id": [1]})
        self._boom = boom

    def fetch(self, conn, *, since=None):
        if self._boom is not None:
            raise self._boom
        return self._df


def _collecting_notifier():
    events = []

    def notify(error_type, message, *, detail=None):
        events.append((error_type, message, detail))

    return notify, events


def test_failing_view_is_skipped_and_run_continues():
    notify, events = _collecting_notifier()
    df_ok = pd.DataFrame({"id": [1, 2]})
    specs = [
        _FakeSpec("v_ok1", df=df_ok),
        _FakeSpec("v_bad", boom=pyodbc.ProgrammingError("4413 binding error")),
        _FakeSpec("v_ok2", df=df_ok),
    ]
    dfs, failed_views = _fetch_all_views(specs, conn=object(), notify=notify)

    # the good views produced their DataFrames; the bad one was skipped
    assert set(dfs.keys()) == {"v_ok1", "v_ok2"}
    assert failed_views == ["v_bad"]
    # the failure was reported as a VIEW_FETCH event naming the view
    assert len(events) == 1
    error_type, message, detail = events[0]
    assert error_type == ErrorType.VIEW_FETCH
    assert "v_bad" in message
    assert detail  # carries the traceback


def test_all_views_ok_reports_nothing():
    notify, events = _collecting_notifier()
    specs = [_FakeSpec("v_a"), _FakeSpec("v_b")]
    dfs, failed_views = _fetch_all_views(specs, conn=object(), notify=notify)
    assert set(dfs.keys()) == {"v_a", "v_b"}
    assert failed_views == []
    assert events == []


def test_empty_specs_returns_empty_dfs():
    notify, _ = _collecting_notifier()
    dfs, failed_views = _fetch_all_views([], conn=object(), notify=notify)
    assert dfs == {}
    assert failed_views == []
