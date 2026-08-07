"""Tests for the Custom Action API view-permission cache (SQL-view source)."""

import pytest
from permissions import check_user_has_view_access, load_view_permissions_cache


def test_cache_empty_when_view_unconfigured(monkeypatch):
    monkeypatch.delenv("DB_VIEW_PERMISSIONS_VIEW", raising=False)
    assert load_view_permissions_cache() == {}


def test_cache_loaded_and_normalized_from_sql_view(monkeypatch, fake_cursor_factory):
    monkeypatch.setenv("DB_VIEW_PERMISSIONS_VIEW", "v_ViewPermissions")
    monkeypatch.setenv("DB_VIEW_PERMISSIONS_SCHEMA", "dbo")
    conn, cur = fake_cursor_factory(
        rows=[
            ("v_Company", "A@allen.com"),
            ("v_Company", "c@allen.com"),
            ("v_Attendee", "a@allen.com"),
        ]
    )
    cache = load_view_permissions_cache(connect=lambda: conn)

    # view names and emails lowercased; grouped per view.
    assert cache["v_company"] == ["a@allen.com", "c@allen.com"]
    assert cache["v_attendee"] == ["a@allen.com"]
    # schema-qualified, bracket-quoted identifiers.
    assert "[dbo].[v_ViewPermissions]" in cur.executed[0][0]


def test_unsafe_identifier_rejected(monkeypatch):
    monkeypatch.setenv("DB_VIEW_PERMISSIONS_VIEW", "bad; DROP TABLE")

    def _should_not_connect():
        raise AssertionError("connect() must not be called for an unsafe identifier")

    with pytest.raises(ValueError):
        load_view_permissions_cache(connect=_should_not_connect)


def test_check_access_uses_cache_case_insensitively():
    cache = {"v_company": ["user@allen.com"]}
    assert check_user_has_view_access("USER@allen.com", "v_Company", cache, frozenset()) is True
    assert check_user_has_view_access("nope@allen.com", "v_Company", cache, frozenset()) is False
    # superuser passes even without a cache entry.
    assert (
        check_user_has_view_access("x@allen.com", "v_Missing", cache, frozenset({"x@allen.com"}))
        is True
    )
