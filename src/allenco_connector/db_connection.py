"""Azure SQL Managed Instance connection via pyodbc (indexer side).

Requires Microsoft ODBC Driver 18 for SQL Server on the host. The connection is
not opened at import time — call get_connection() explicitly.

⚠️ TLS — the #1 trap when porting from the on-prem SMART connector: Azure SQL MI
presents a real, validatable certificate, so this builder keeps
``TrustServerCertificate=no``. Never copy SMART's ``TrustServerCertificate=yes``
(that was an on-prem self-signed workaround) — it would silently disable cert
validation.

This module MIRRORS allenco_custom_action/db.py (same connection string + retry
loop). The only intended difference is pooling: OFF here (one-shot indexer), ON
in the API. Keep the two in sync by hand.
"""

import logging
import time

import pyodbc

from config.config import AUTH_MODE_MSI, AUTH_MODE_SQL, AUTH_MODE_WINDOWS, DbSettings

logger = logging.getLogger(__name__)

_DEFAULT_CONNECT_TIMEOUT = 30
_DEFAULT_RETRY_ATTEMPTS = 3
_DEFAULT_RETRY_DELAY = 5.0


def build_connection_string(settings: DbSettings) -> str:
    """Build the pyodbc connection string for the configured auth mode.

    Shared shape across every connectivity option (inside VNet / VPN / tunnel /
    public) — only the SERVER host and the TLS/auth fields differ, and those come
    from DbSettings. See config.DbSettings for the auth_mode / TLS semantics.
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
        # Tunnel (Option B2): dial 127.0.0.1 but validate the server's real cert name.
        parts.append(f"HostNameInCertificate={settings.host_name_in_certificate};")

    mode = settings.auth_mode.lower()
    if mode == AUTH_MODE_SQL:
        parts.append(f"UID={settings.user};")
        parts.append(f"PWD={settings.password};")
    elif mode == AUTH_MODE_WINDOWS:
        # Windows Authentication (SSPI/Kerberos): connect as the OS process identity.
        # No UID/PWD — the connector must run as a Windows principal with DB access
        # (native on a domain-joined Windows host; needs a Kerberos keytab elsewhere).
        parts.append("Trusted_Connection=yes;")
    elif mode == AUTH_MODE_MSI:
        parts.append("Authentication=ActiveDirectoryMsi;")
        # A USER-assigned managed identity must be selected by its client id;
        # omit UID only for a system-assigned identity.
        if settings.msi_client_id:
            parts.append(f"UID={settings.msi_client_id};")
    else:  # AUTH_MODE_DEFAULT
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

    Args:
        settings: MI connection parameters (host, auth mode, TLS).
        connect_timeout: Seconds to wait per individual connection attempt.
        retry_attempts: Total number of attempts before raising.
        retry_delay: Seconds to wait between attempts.

    Raises:
        pyodbc.Error: If all connection attempts fail.
    """
    connection_string = build_connection_string(settings)

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
        "Check DB_SERVER, DB_AUTH_MODE, credentials, and network reach to the MI "
        "(VNet / VPN / tunnel)."
    ) from last_exc
