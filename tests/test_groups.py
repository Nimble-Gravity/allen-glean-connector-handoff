"""Tests for the SQL groups-view loader (user → AD/Entra group memberships)."""

import hashlib

import pytest

from allenco_connector.groups import load_users_with_groups
from config.config import GroupsSettings


class _Cursor:
    def __init__(self, rows):
        self.rows = rows
        self.executed = []

    def execute(self, sql, *params):
        self.executed.append((sql, params))

    def fetchall(self):
        return self.rows


class _Conn:
    def __init__(self, rows):
        self._cursor = _Cursor(rows)

    def cursor(self):
        return self._cursor


def test_returns_empty_when_view_unconfigured():
    assert load_users_with_groups(_Conn([]), GroupsSettings(view="")) == []


def test_returns_empty_when_no_connection():
    assert load_users_with_groups(None, GroupsSettings(view="v_UserGroups")) == []


def test_aggregates_rows_into_users():
    rows = [
        ("A@allen.com", "EMS-Readers", "Ada"),
        ("a@allen.com", "Analysts", "Ada"),
        ("b@allen.com", "EMS-Readers", None),
    ]
    settings = GroupsSettings(
        view="v_UserGroups",
        schema="dbo",
        email_column="Email",
        group_column="GroupName",
        name_column="DisplayName",
    )
    users = load_users_with_groups(_Conn(rows), settings)
    by_email = {u.email: u for u in users}

    assert set(by_email) == {"a@allen.com", "b@allen.com"}
    # groups aggregated across rows and sorted; email normalized to lowercase.
    assert by_email["a@allen.com"].groups == ("Analysts", "EMS-Readers")
    assert by_email["a@allen.com"].name == "Ada"
    # id derivation matches the superuser sha256(lowercased email).
    assert by_email["a@allen.com"].datasource_user_id == hashlib.sha256(b"a@allen.com").hexdigest()


def test_query_is_schema_qualified_and_bracketed():
    conn = _Conn([])
    load_users_with_groups(conn, GroupsSettings(view="v_UserGroups", schema="Conference"))
    sql = conn.cursor().executed[0][0]
    assert "[Conference].[v_UserGroups]" in sql
    assert "[Email]" in sql and "[GroupName]" in sql


def test_rejects_unsafe_identifier():
    with pytest.raises(ValueError):
        load_users_with_groups(_Conn([]), GroupsSettings(view="x; DROP TABLE"))
