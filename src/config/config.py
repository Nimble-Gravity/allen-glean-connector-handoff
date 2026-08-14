"""Application configuration from environment variables.

Pattern: frozen dataclasses + manual env readers (no pydantic-settings). Required
vars fail loudly; optional vars have defaults. Load via the ``load_*`` functions
after ``load_dotenv()``.
"""

import logging
import os
from dataclasses import dataclass
from logging.handlers import RotatingFileHandler
from pathlib import Path

from glean_index.client import GleanConfig

# Supported SQL authentication modes (see DbSettings.auth_mode).
AUTH_MODE_SQL = "sql"  # SQL login (UID/PWD) — dev phase
AUTH_MODE_MSI = "msi"  # Managed identity (Authentication=ActiveDirectoryMsi) — Azure prod
AUTH_MODE_DEFAULT = "default"  # Authentication=ActiveDirectoryDefault (az-login / env / MSI chain)
# Windows Authentication (Trusted_Connection=yes) — domain-joined SQL Server.
AUTH_MODE_WINDOWS = "windows"
VALID_AUTH_MODES = frozenset({AUTH_MODE_SQL, AUTH_MODE_MSI, AUTH_MODE_DEFAULT, AUTH_MODE_WINDOWS})


@dataclass(frozen=True)
class ConnectorSettings:
    """Environment-backed settings for the connector (indexer).

    Load via load_connector_settings() after load_dotenv().
    """

    # Glean indexing
    glean_enable_indexing: bool
    glean_full_refresh: bool
    glean_datasource: str
    glean_instance: str
    glean_indexing_api_key: str
    # JSON array of emails for users who may see all indexed documents.
    glean_indexing_superuser_allowed_users_json: str

    # Logging
    log_debug: bool
    debug_files: bool

    # Max rows fetched per view (FETCH_ROW_LIMIT). 0 = no limit; >0 → SELECT TOP (N),
    # for a fast dry-run sample or to cap very large views.
    fetch_row_limit: int = 0

    # Columns dropped from every document body (EXCLUDE_COLUMNS, comma-separated) —
    # e.g. PII fields not cleared for indexing. Empty = keep all columns.
    exclude_columns: tuple[str, ...] = ()

    # Base URL stamped as each document's viewURL (VIEW_URL_BASE). Glean REQUIRES a
    # non-empty viewURL. Placeholder default until the real EMS/portal URL is known;
    # must match the datasource's urlRegex in Glean.
    view_url_base: str = "https://ems.allenco.com"

    # DEV/TEST ONLY (GLEAN_ALLOW_ANONYMOUS_ACCESS): grant org-wide (anonymous) access
    # to documents that would otherwise have no ACL, so a test can index without
    # superusers or the groups view. ⚠️ Production ACLs come from the AD groups view —
    # keep this False in prod.
    glean_allow_anonymous_access: bool = False

    def require_glean_indexing_prereqs(self) -> tuple[str, GleanConfig]:
        """Return (datasource, glean_config). Raises ValueError if misconfigured."""
        datasource = self.glean_datasource.strip()
        if not datasource:
            raise ValueError("GLEAN_DATASOURCE is required when GLEAN_ENABLE_INDEXING=true.")
        instance = self.glean_instance.strip()
        api_key = self.glean_indexing_api_key.strip()
        if not instance or not api_key:
            raise ValueError(
                "Missing Glean configuration. "
                "Set GLEAN_INSTANCE and GLEAN_INDEXING_API_KEY in .env."
            )
        return datasource, GleanConfig(instance=instance, indexing_api_key=api_key)


@dataclass(frozen=True)
class DbSettings:
    """Azure SQL Managed Instance connection settings.

    The connection string is built from these fields in
    ``allenco_connector/db_connection.py`` (indexer) and ``allenco_custom_action/db.py``
    (API). Only these fields change between connectivity options — the retry loop,
    pooling policy, and query code stay identical ("connectivity is configuration,
    not code").

    auth_mode:
        - "sql"     → SQL login (UID/PWD). Used during the dev phase.
        - "msi"     → Managed identity (Authentication=ActiveDirectoryMsi). Azure prod.
        - "default" → Authentication=ActiveDirectoryDefault (az-login / env / MSI chain).
        - "windows" → Windows Authentication (Trusted_Connection=yes). No UID/PWD:
                      the process runs as a Windows principal that has DB access.
                      For a domain-joined SQL Server (e.g. SQL Server on an Azure VM),
                      matching SSMS's "Windows Authentication" option.

    TLS: Azure SQL MI presents a real, validatable certificate, so for MI keep
    ``encrypt=True`` + ``trust_server_certificate=False``. A domain-joined SQL Server
    may only have a self-signed cert and allow *optional* encryption — mirror SSMS's
    "Encryption: Optional" with ``encrypt=False`` (or keep encryption on and set
    ``trust_server_certificate=True``). Set ``host_name_in_certificate`` only when
    connecting through a local tunnel (Option B2), where the driver dials
    ``127.0.0.1`` but must still validate the server's real certificate name.

    port: appended to SERVER as ``SERVER=host,port``. Set to 0 to omit the port and
    let the driver resolve a default instance / named instance from the host alone.
    """

    server: str
    database: str
    # Default schema the in-scope views live in. The mock EMS uses "dbo"; the real
    # Allen & Co Conference views may live in a "Conference" schema — set DB_SCHEMA.
    # A ViewCatalogEntry may still override this per view.
    schema: str = "dbo"
    port: int = 1433
    driver: str = "ODBC Driver 18 for SQL Server"
    auth_mode: str = AUTH_MODE_SQL
    user: str = ""
    password: str = ""
    encrypt: bool = True
    trust_server_certificate: bool = False
    host_name_in_certificate: str | None = None
    # Client ID of a USER-assigned managed identity (auth_mode=msi). Required so the
    # ODBC driver targets the right identity — a user-assigned MI needs its client id;
    # leave empty only for a system-assigned identity.
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
        schema=_read_str_env("DB_SCHEMA", default="dbo") or "dbo",
        # DB_PORT=0 omits the port (SERVER=host) so the driver can resolve a default
        # or named instance from the host alone.
        port=_read_int_env("DB_PORT", default=1433),
        driver=_read_str_env("DB_DRIVER", default="ODBC Driver 18 for SQL Server"),
        auth_mode=auth_mode,
        user=user,
        password=password,
        encrypt=_read_bool_env("DB_ENCRYPT", default=True),
        trust_server_certificate=_read_bool_env("DB_TRUST_SERVER_CERTIFICATE", default=False),
        host_name_in_certificate=_read_str_env("DB_HOST_NAME_IN_CERTIFICATE") or None,
        msi_client_id=_read_str_env("DB_MSI_CLIENT_ID") or _read_str_env("AZURE_CLIENT_ID"),
    )


@dataclass(frozen=True)
class GroupsSettings:
    """Source of user → AD/Entra group memberships, read from a SQL view.

    Allen & Co exposes directory group membership as a SQL view in the same
    read-only DB (the decided source — not Microsoft Graph). One row per
    (user, group). ``load_source_users`` (main.py) queries it to populate each
    ``GlobalUser.groups`` so documents get group-derived ACLs.

    ``view`` empty → the feature is off: no groups view is queried and
    ``load_source_users`` returns [] (dry runs then rely on superuser ACLs only).
    """

    view: str = ""  # DB_GROUPS_VIEW, e.g. "v_UserGroups"; empty disables the fetch
    schema: str = "dbo"  # DB_GROUPS_SCHEMA; defaults to DB_SCHEMA
    email_column: str = "Email"  # DB_GROUPS_EMAIL_COLUMN
    group_column: str = "GroupName"  # DB_GROUPS_GROUP_COLUMN
    name_column: str = ""  # DB_GROUPS_NAME_COLUMN (optional display name)


def load_groups_settings() -> GroupsSettings:
    """Read the AD/Entra groups-view settings from the environment.

    The groups view lives in the same DB as the data views; its schema defaults to
    DB_SCHEMA when DB_GROUPS_SCHEMA is unset.
    """
    default_schema = _read_str_env("DB_SCHEMA", default="dbo") or "dbo"
    return GroupsSettings(
        view=_read_str_env("DB_GROUPS_VIEW"),
        schema=_read_str_env("DB_GROUPS_SCHEMA", default=default_schema) or default_schema,
        email_column=_read_str_env("DB_GROUPS_EMAIL_COLUMN", default="Email") or "Email",
        group_column=_read_str_env("DB_GROUPS_GROUP_COLUMN", default="GroupName") or "GroupName",
        name_column=_read_str_env("DB_GROUPS_NAME_COLUMN"),
    )


def load_connector_settings() -> ConnectorSettings:
    """Read connector settings from the current process environment."""
    return ConnectorSettings(
        glean_enable_indexing=_read_bool_env("GLEAN_ENABLE_INDEXING", default=False),
        glean_full_refresh=_read_bool_env("GLEAN_FULL_REFRESH", default=False),
        glean_datasource=_read_str_env("GLEAN_DATASOURCE"),
        glean_instance=_read_str_env("GLEAN_INSTANCE"),
        glean_indexing_api_key=_read_str_env("GLEAN_INDEXING_API_KEY"),
        glean_indexing_superuser_allowed_users_json=_read_str_env(
            "GLEAN_INDEXING_SUPERUSER_ALLOWED_USERS"
        ),
        log_debug=_read_bool_env("LOG_DEBUG", default=False),
        debug_files=_read_bool_env("DEBUG_FILES", default=False),
        fetch_row_limit=max(0, _read_int_env("FETCH_ROW_LIMIT", default=0)),
        exclude_columns=_read_csv_env("EXCLUDE_COLUMNS"),
        view_url_base=_read_str_env("VIEW_URL_BASE", default="https://ems.allenco.com")
        or "https://ems.allenco.com",
        glean_allow_anonymous_access=_read_bool_env("GLEAN_ALLOW_ANONYMOUS_ACCESS", default=False),
    )


def configure_logging(settings: ConnectorSettings | None = None) -> None:
    """Configure root logging (console, or rotating files when debug_files is true)."""
    effective = settings if settings is not None else load_connector_settings()
    debug_enabled = effective.log_debug
    use_file_logging = effective.debug_files

    formatter = logging.Formatter("%(asctime)s %(levelname)s %(name)s - %(message)s")
    root_level = logging.DEBUG if debug_enabled else logging.INFO

    root_logger = logging.getLogger()
    root_logger.setLevel(root_level)
    for handler in list(root_logger.handlers):
        root_logger.removeHandler(handler)

    if use_file_logging:
        # CWD/env-based (not __file__-relative): the package is pip-installed into a
        # read-only site-packages in the container, so a package-relative path would
        # not be writable. Locally (run from the repo root) this is the repo root.
        base = os.environ.get("CONNECTOR_OUTPUT_DIR") or os.getcwd()
        project_root = Path(base)
        info_dir = project_root / "logs" / "info"
        error_dir = project_root / "logs" / "error"
        info_dir.mkdir(parents=True, exist_ok=True)
        error_dir.mkdir(parents=True, exist_ok=True)

        info_handler = RotatingFileHandler(
            info_dir / "allenco-glean-connector.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        info_handler.setLevel(root_level)
        info_handler.setFormatter(formatter)
        root_logger.addHandler(info_handler)

        error_handler = RotatingFileHandler(
            error_dir / "allenco-glean-connector.log",
            maxBytes=5 * 1024 * 1024,
            backupCount=5,
            encoding="utf-8",
        )
        error_handler.setLevel(logging.ERROR)
        error_handler.setFormatter(formatter)
        root_logger.addHandler(error_handler)
    else:
        stream_handler = logging.StreamHandler()
        stream_handler.setLevel(root_level)
        stream_handler.setFormatter(formatter)
        root_logger.addHandler(stream_handler)

    if not debug_enabled:
        for noisy in ("httpcore", "httpx", "asyncio"):
            logging.getLogger(noisy).setLevel(logging.WARNING)


def _read_bool_env(key: str, *, default: bool) -> bool:
    raw = (os.environ.get(key) or "").strip().lower()
    if raw in ("1", "true", "yes"):
        return True
    if raw in ("0", "false", "no"):
        return False
    return default


def _read_csv_env(key: str) -> tuple[str, ...]:
    raw = (os.environ.get(key) or "").strip()
    if not raw:
        return ()
    return tuple(part.strip() for part in raw.split(",") if part.strip())


def _read_int_env(key: str, *, default: int) -> int:
    raw = (os.environ.get(key) or "").strip()
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _read_str_env(key: str, *, default: str = "") -> str:
    return (os.environ.get(key) or default).strip()


def _read_required_str_env(key: str) -> str:
    value = (os.environ.get(key) or "").strip()
    if not value:
        raise OSError(f"Required environment variable '{key}' is not set. Check your .env file.")
    return value
