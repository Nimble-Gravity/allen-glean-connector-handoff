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
import time

import pyodbc

# Enable ODBC-level connection pooling. Must be set before the first connect().
pyodbc.pooling = True

from settings import AUTH_MODE_MSI, AUTH_MODE_SQL, DbSettings  # noqa: E402

logger = logging.getLogger(__name__)

_DEFAULT_CONNECT_TIMEOUT = 30
_DEFAULT_RETRY_ATTEMPTS = 3
_DEFAULT_RETRY_DELAY = 5.0


def build_connection_string(settings: DbSettings, *, connect_timeout: int) -> str:
    """Build the pyodbc connection string for the configured auth mode.

    Mirror of allenco_connector.db_connection.build_connection_string. See
    settings.DbSettings for the auth_mode / TLS semantics.
    """
    parts = [
        f"DRIVER={{{settings.driver}}};",
        f"SERVER={settings.server},{settings.port};",
        f"DATABASE={settings.database};",
        f"Connection Timeout={connect_timeout};",
        f"Encrypt={'yes' if settings.encrypt else 'no'};",
        f"TrustServerCertificate={'yes' if settings.trust_server_certificate else 'no'};",
    ]
    if settings.host_name_in_certificate:
        parts.append(f"HostNameInCertificate={settings.host_name_in_certificate};")

    mode = settings.auth_mode.lower()
    if mode == AUTH_MODE_SQL:
        parts.append(f"UID={settings.user};")
        parts.append(f"PWD={settings.password};")
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
    connection_string = build_connection_string(settings, connect_timeout=connect_timeout)

    last_exc: Exception | None = None
    for attempt in range(1, retry_attempts + 1):
        try:
            conn = pyodbc.connect(connection_string, timeout=connect_timeout)
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
