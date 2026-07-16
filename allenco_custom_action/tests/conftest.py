"""Pytest setup for the Custom Action API tests.

Adds the API package dir to sys.path so the flat imports used by the app
(`from db import ...`, `from notifications_setup import ...`) resolve, and
provides the API-key env so settings load without a real .env.
"""

import os
import sys
from pathlib import Path

import pytest
from dotenv import load_dotenv

_API_DIR = Path(__file__).resolve().parent.parent
if str(_API_DIR) not in sys.path:
    sys.path.insert(0, str(_API_DIR))

# Load the shared .env before any module reads os.environ.
load_dotenv(dotenv_path=_API_DIR.parent / ".env", override=True)

# Minimal env so load_db_settings()/load_api_key() succeed during app startup.
os.environ.setdefault("CUSTOM_ACTION_API_KEY", "test-key")
os.environ.setdefault("DB_SERVER", "test-server")
os.environ.setdefault("DB_NAME", "test-db")
os.environ.setdefault("DB_AUTH_MODE", "sql")
os.environ.setdefault("DB_USER", "test-user")
os.environ.setdefault("DB_PASSWORD", "test-pass")
# The permission cache is an empty stub (AD/Entra not wired), so make the test
# user a superuser — otherwise every view-access check denies (403). See
# permissions.py.
os.environ.setdefault("GLEAN_INDEXING_SUPERUSER_ALLOWED_USERS", '["a@sdh.com"]')


# ---------------------------------------------------------------------------
# Fake DB connection helpers
# ---------------------------------------------------------------------------


class FakeCursor:
    """Stand-in for a pyodbc cursor that returns pre-programmed results."""

    def __init__(self, *, rows=None, description=None, fetchone_seq=None):
        self.rows = rows or []
        self.description = description or []
        # fetchone_seq: list of values returned on successive fetchone() calls.
        # Default: [[1]] means "view exists" check passes.
        self._fetchone_seq = list(fetchone_seq if fetchone_seq is not None else [[1]])
        self.executed = []

    def execute(self, sql, *params):
        self.executed.append((sql, params))

    def fetchone(self):
        return self._fetchone_seq.pop(0) if self._fetchone_seq else None

    def fetchall(self):
        return self.rows


class FakeConn:
    def __init__(self, cursor: FakeCursor):
        self._cursor = cursor

    def cursor(self) -> FakeCursor:
        return self._cursor

    def close(self) -> None:
        pass


@pytest.fixture
def fake_cursor_factory():
    """Return a factory that creates (FakeConn, FakeCursor) pairs."""

    def _make(*, rows=None, description=None, fetchone_seq=None):
        cur = FakeCursor(rows=rows, description=description, fetchone_seq=fetchone_seq)
        return FakeConn(cur), cur

    return _make
