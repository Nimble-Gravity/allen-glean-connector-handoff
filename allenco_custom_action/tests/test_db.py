"""Tests for the API-side Azure MI connection-string builder.

Mirrors tests/test_db_connection.py on the indexer side — both builders must stay
in sync (same TLS + auth-mode behaviour).
"""

from db import build_connection_string
from settings import (
    AUTH_MODE_DEFAULT,
    AUTH_MODE_MSI,
    AUTH_MODE_SQL,
    AUTH_MODE_WINDOWS,
    DbSettings,
)


def _settings(**overrides) -> DbSettings:
    base = dict(
        server="mi.zone.database.windows.net",
        database="ems",
        auth_mode=AUTH_MODE_SQL,
        user="glean_ro",
        password="secret",
    )
    base.update(overrides)
    return DbSettings(**base)


def test_sql_auth_includes_credentials_and_validates_cert():
    cs = build_connection_string(_settings())
    assert "UID=glean_ro;" in cs
    assert "PWD=secret;" in cs
    assert "TrustServerCertificate=no;" in cs


def test_msi_auth_omits_credentials():
    cs = build_connection_string(_settings(auth_mode=AUTH_MODE_MSI, user="", password=""))
    assert "Authentication=ActiveDirectoryMsi;" in cs
    assert "UID=" not in cs


def test_msi_user_assigned_appends_client_id():
    cs = build_connection_string(
        _settings(auth_mode=AUTH_MODE_MSI, user="", password="", msi_client_id="abc-123-client")
    )
    assert "Authentication=ActiveDirectoryMsi;" in cs
    assert "UID=abc-123-client;" in cs


def test_default_auth_uses_active_directory_default():
    cs = build_connection_string(_settings(auth_mode=AUTH_MODE_DEFAULT, user="", password=""))
    assert "Authentication=ActiveDirectoryDefault;" in cs


def test_windows_auth_uses_trusted_connection():
    cs = build_connection_string(_settings(auth_mode=AUTH_MODE_WINDOWS, user="", password=""))
    assert "Trusted_Connection=yes;" in cs
    assert "UID=" not in cs
    assert "PWD=" not in cs
    assert "Authentication=" not in cs


def test_encryption_optional_emits_encrypt_no():
    cs = build_connection_string(_settings(encrypt=False))
    assert "Encrypt=no;" in cs


def test_port_zero_omits_port_from_server():
    cs = build_connection_string(_settings(server="ALC-AZR-SQL-001", port=0))
    assert "SERVER=ALC-AZR-SQL-001;" in cs
    assert "ALC-AZR-SQL-001,0" not in cs
