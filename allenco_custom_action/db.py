"""Azure SQL Managed Instance connection via pyodbc (Custom Action API side).

MIRRORS src/allenco_connector/db_connection.py — same connection string builder and
retry loop. Keep the two in sync if either changes.

Connection pooling is enabled at module level (pyodbc.pooling = True): conn.close()
returns the connection to the ODBC pool rather than closing the TCP socket, so the
next request reuses it. Do NOT enable pooling in the batch indexer — it is a
one-shot script where pooling adds overhead with no benefit.

⚠️ TLS — Azure SQL MI has a real, validatable certificate. This builder keeps
``TrustServerCertificate=no``; never copy SMART's on-prem ``=yes`` workaround.
"""

import logging
import struct
import time
from datetime import datetime, timedelta, timezone

import pyodbc

# Enable ODBC-level connection pooling. Must be set before the first connect().
pyodbc.pooling = True

from settings import AUTH_MODE_MSI, AUTH_MODE_SQL, AUTH_MODE_WINDOWS, DbSettings  # noqa: E402

logger = logging.getLogger(__name__)

_DEFAULT_CONNECT_TIMEOUT = 30
_DEFAULT_RETRY_ATTEMPTS = 3
_DEFAULT_RETRY_DELAY = 5.0

# SQL Server DATETIMEOFFSET arrives as SQL_SS_TIMESTAMPOFFSET (-155), which pyodbc has
# no built-in decoder for — a fetch of such a column raises "-155 is not supported".
# Mirror of allenco_connector.db_connection (keep the two in sync).
SQL_SS_TIMESTAMPOFFSET = -155


def handle_datetimeoffset(raw: bytes) -> datetime:
    """Decode a SQL Server DATETIMEOFFSET value to a timezone-aware datetime."""
    y, mo, d, h, mi, s, ns, tz_h, tz_m = struct.unpack("<6hI2h", raw)
    return datetime(y, mo, d, h, mi, s, ns // 1000, timezone(timedelta(hours=tz_h, minutes=tz_m)))


def build_connection_string(settings: DbSettings) -> str:
    """Build the pyodbc connection string for the configured auth mode.

    Mirror of allenco_connector.db_connection.build_connection_string. See
    settings.DbSettings for the auth_mode / TLS semantics.
    """
    # port=0 → omit ",port" so the driver resolves a default/named instance by host.
    server = f"{settings.server},{settings.port}" if settings.port else settings.server
    parts = [
        f"DRIVER={{{settings.driver}}};",
        f"SERVER={server};",
        f"DATABASE={settings.database};",
        f"Encrypt={'yes' if settings.encrypt else 'no'};",
        f"TrustServerCertificate={'yes' if settings.trust_server_certificate else 'no'};",
    ]
    if settings.host_name_in_certificate:
        parts.append(f"HostNameInCertificate={settings.host_name_in_certificate};")

    mode = settings.auth_mode.lower()
    if mode == AUTH_MODE_SQL:
        parts.append(f"UID={settings.user};")
        parts.append(f"PWD={settings.password};")
    elif mode == AUTH_MODE_WINDOWS:
        # Windows Authentication (SSPI/Kerberos): connect as the OS process identity.
        # No UID/PWD — the process must run as a Windows principal with DB access.
        parts.append("Trusted_Connection=yes;")
    elif mode == AUTH_MODE_MSI:
        parts.append("Authentication=ActiveDirectoryMsi;")
        # A USER-assigned managed identity must be selected by its client id;
        # omit UID only for a system-assigned identity.
        if settings.msi_client_id:
            parts.append(f"UID={settings.msi_client_id};")
    else:  # "default"
        parts.append("Authentication=ActiveDirectoryDefault;")
    return "".join(parts)


def get_connection(
    settings: DbSettings,
    *,
    connect_timeout: int = _DEFAULT_CONNECT_TIMEOUT,
    retry_attempts: int = _DEFAULT_RETRY_ATTEMPTS,
    retry_delay: float = _DEFAULT_RETRY_DELAY,
) -> pyodbc.Connection:
    """Return a live pyodbc connection to the Azure SQL MI.

    Retries on failure to handle cold-start scenarios where the server needs a few
    seconds to wake up.

    Raises:
        pyodbc.Error: If all connection attempts fail.
    """
    connection_string = build_connection_string(settings)

    last_exc: Exception | None = None
    for attempt in range(1, retry_attempts + 1):
        try:
            conn = pyodbc.connect(connection_string, timeout=connect_timeout)
            # Teach pyodbc to decode DATETIMEOFFSET columns (else fetch raises -155).
            conn.add_output_converter(SQL_SS_TIMESTAMPOFFSET, handle_datetimeoffset)
            logger.info(
                "Connected to Azure SQL MI '%s' (auth=%s, attempt %d/%d)",
                settings.server,
                settings.auth_mode,
                attempt,
                retry_attempts,
            )
            return conn
        except pyodbc.Error as exc:
            last_exc = exc
            logger.warning(
                "Connection attempt %d/%d to '%s' failed: %s",
                attempt,
                retry_attempts,
                settings.server,
                exc,
            )
            if attempt < retry_attempts:
                time.sleep(retry_delay)

    raise pyodbc.Error(
        f"All {retry_attempts} connection attempt(s) to '{settings.server}' failed. "
        "Check DB_SERVER, DB_AUTH_MODE, credentials, and network reach to the MI."
    ) from last_exc
