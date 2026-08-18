"""Tests for the indexer pipeline's per-view resilience (main._fetch_documents)."""

import pyodbc

from main import _fetch_documents
from notifications.events import ErrorType


class _FakeSpec:
    """A stand-in ViewSpec: returns canned docs, or raises to simulate a bad view."""

    def __init__(self, name, docs=None, boom=None, watermark=None):
        self.view_name = name
        self._docs = list(docs or [])
        self._boom = boom
        self._watermark = watermark

    def build_documents(self, conn, *, datasource, allowed_users=None, since=None):
        if self._boom is not None:
            raise self._boom
        return list(self._docs), self._watermark


class _NoSyncStore:
    incremental = False


class _RecordingSyncState:
    def __init__(self):
        self.watermarks = {}

    def watermark_for(self, view_name):  # pragma: no cover - not used when non-incremental
        return None

    def set_watermark(self, view_name, value, *, count):
        self.watermarks[view_name] = (value, count)


def _collecting_notifier():
    events = []

    def notify(error_type, message, *, detail=None):
        events.append((error_type, message, detail))

    return notify, events


def test_failing_view_is_skipped_and_run_continues():
    notify, events = _collecting_notifier()
    specs = [
        _FakeSpec("v_ok1", docs=["d1", "d2"]),
        # a cross-DB binding error like the real ConferenceImage failure
        _FakeSpec("v_bad", boom=pyodbc.ProgrammingError("4413 binding error")),
        _FakeSpec("v_ok2", docs=["d3"]),
    ]
    documents, failed_views, fetched = _fetch_documents(
        specs,
        conn=object(),
        datasource="ds",
        allowed_refs=[],
        sync_state=_RecordingSyncState(),
        sync_store=_NoSyncStore(),
        use_incremental=False,
        notify=notify,
    )
    # the good views still produced their documents; the bad one was skipped
    assert documents == ["d1", "d2", "d3"]
    assert fetched == 3
    assert failed_views == ["v_bad"]
    # the failure was reported as a VIEW_FETCH event naming the view
    assert len(events) == 1
    error_type, message, detail = events[0]
    assert error_type == ErrorType.VIEW_FETCH
    assert "v_bad" in message
    assert detail  # carries the traceback


def test_all_views_ok_reports_nothing():
    notify, events = _collecting_notifier()
    specs = [_FakeSpec("v_a", docs=["a"]), _FakeSpec("v_b", docs=["b", "c"])]
    documents, failed_views, fetched = _fetch_documents(
        specs,
        conn=object(),
        datasource="ds",
        allowed_refs=[],
        sync_state=_RecordingSyncState(),
        sync_store=_NoSyncStore(),
        use_incremental=False,
        notify=notify,
    )
    assert documents == ["a", "b", "c"]
    assert fetched == 3
    assert failed_views == []
    assert events == []


def test_incremental_watermark_persisted_per_view():
    notify, _ = _collecting_notifier()

    class _IncStore:
        incremental = True

    state = _RecordingSyncState()
    specs = [_FakeSpec("v_a", docs=["a"], watermark="2026-01-01")]
    _fetch_documents(
        specs,
        conn=object(),
        datasource="ds",
        allowed_refs=[],
        sync_state=state,
        sync_store=_IncStore(),
        use_incremental=False,
        notify=notify,
    )
    assert state.watermarks == {"v_a": ("2026-01-01", 1)}
