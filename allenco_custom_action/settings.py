"""Settings for the Custom Action API.

Mirrors the DB-related parts of src/config/config.py without importing from it
(the parent config imports the Glean SDK, which is not a dependency here). Keep
DbSettings and the auth-mode constants in sync with src/config/config.py.
"""

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

# Load the shared .env from the project root (one level up).
load_dotenv(dotenv_path=Path(__file__).parent.parent / ".env", override=True)

# Azure SQL authentication modes (mirror of config.config).
AUTH_MODE_SQL = "sql"
AUTH_MODE_MSI = "msi"
AUTH_MODE_DEFAULT = "default"
VALID_AUTH_MODES = frozenset({AUTH_MODE_SQL, AUTH_MODE_MSI, AUTH_MODE_DEFAULT})


@dataclass(frozen=True)
class DbSettings:
    """Azure SQL Managed Instance connection settings (see config.config.DbSettings)."""

    server: str
    database: str
    port: int = 1433
    driver: str = "ODBC Driver 18 for SQL Server"
    auth_mode: str = AUTH_MODE_SQL
    user: str = ""
    password: str = ""
    encrypt: bool = True
    trust_server_certificate: bool = False
    host_name_in_certificate: str | None = None
    # Client ID of a USER-assigned managed identity (auth_mode=msi); empty for
    # system-assigned. See config.config.DbSettings.
    msi_client_id: str = ""


def load_db_settings() -> DbSettings:
    """Read Azure SQL MI settings from the current process environment."""
    auth_mode = _read_str_env("DB_AUTH_MODE", default=AUTH_MODE_SQL).lower()
    if auth_mode not in VALID_AUTH_MODES:
        raise OSError(
            f"DB_AUTH_MODE='{auth_mode}' is invalid. "
            f"Use one of: {', '.join(sorted(VALID_AUTH_MODES))}."
        )
    user = _read_str_env("DB_USER")
    password = _read_str_env("DB_PASSWORD")
    if auth_mode == AUTH_MODE_SQL and not (user and password):
        raise OSError("DB_AUTH_MODE=sql requires DB_USER and DB_PASSWORD. Check your .env file.")
    return DbSettings(
        server=_read_required_str_env("DB_SERVER"),
        database=_read_required_str_env("DB_NAME"),
        port=int(_read_str_env("DB_PORT", default="1433") or "1433"),
        driver=_read_str_env("DB_DRIVER", default="ODBC Driver 18 for SQL Server"),
        auth_mode=auth_mode,
        user=user,
        password=password,
        encrypt=_read_bool_env("DB_ENCRYPT", default=True),
        trust_server_certificate=_read_bool_env("DB_TRUST_SERVER_CERTIFICATE", default=False),
        host_name_in_certificate=_read_str_env("DB_HOST_NAME_IN_CERTIFICATE") or None,
        msi_client_id=_read_str_env("DB_MSI_CLIENT_ID") or _read_str_env("AZURE_CLIENT_ID"),
    )


def load_api_key() -> str:
    """Read the expected API key for the Custom Action server from the environment."""
    return _read_required_str_env("CUSTOM_ACTION_API_KEY")


def load_max_rows() -> int:
    """Read MAX_ROWS from environment; default 500, minimum 1."""
    raw = _read_str_env("MAX_ROWS", default="500")
    return max(1, int(raw))


def _read_bool_env(key: str, *, default: bool) -> bool:
    raw = (os.environ.get(key) or "").strip().lower()
    if raw in ("1", "true", "yes"):
        return True
    if raw in ("0", "false", "no"):
        return False
    return default


def _read_required_str_env(key: str) -> str:
    value = (os.environ.get(key) or "").strip()
    if not value:
        raise OSError(f"Required environment variable '{key}' is not set. Check your .env file.")
    return value


def _read_str_env(key: str, *, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()
