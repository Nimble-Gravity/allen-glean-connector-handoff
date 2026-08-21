"""View-level permission checks for the Custom Action API.

Intentionally does not import from src/ to avoid the Glean SDK dependency.

Allen & Co derives view access from Active Directory / Entra ID groups exposed as a
**SQL view** in the EMS DB (the decided source — not Microsoft Graph; mirrors the
indexer's allenco_connector.groups). The view maps (EMS view name → allowed user
email), one row per grant. It is configured via env (see load_view_permissions_cache)
and is **opt-in**: when DB_VIEW_PERMISSIONS_VIEW is unset the cache is empty, the API
boots without touching the DB, and only superusers
(GLEAN_INDEXING_SUPERUSER_ALLOWED_USERS) pass — every other user is denied.
"""

import json
import logging
import os
from collections.abc import Callable

from validators import SAFE_IDENTIFIER

logger = logging.getLogger(__name__)

PERMISSION_DENIED_MESSAGE = "The user does not have permission to access this view."


def load_view_permissions_cache(
    connect: Callable[[], object] | None = None,
) -> dict[str, list[str]]:
    """Return {lowercase_view_name: [allowed_emails]} from the SQL permissions view.

    Env configuration ("connectivity is configuration, not code"):
      DB_VIEW_PERMISSIONS_VIEW          the view name (empty → feature off, empty cache)
      DB_VIEW_PERMISSIONS_SCHEMA        schema (default: DB_SCHEMA, else dbo)
      DB_VIEW_PERMISSIONS_VIEW_COLUMN   column holding the EMS view name (default ViewName)
      DB_VIEW_PERMISSIONS_EMAIL_COLUMN  column holding the user email (default Email)

    Identifiers are validated against SAFE_IDENTIFIER and bracket-quoted before use.
    ``connect`` is an optional connection factory (for tests); production opens a
    pooled connection via db.get_connection. Called once at API startup.
    """
    view = (os.environ.get("DB_VIEW_PERMISSIONS_VIEW") or "").strip()
    if not view:
        logger.warning(
            "load_view_permissions_cache: SQL permissions view not configured "
            "(DB_VIEW_PERMISSIONS_VIEW empty) — empty cache (only superusers pass)."
        )
        return {}

    schema = (
        os.environ.get("DB_VIEW_PERMISSIONS_SCHEMA") or os.environ.get("DB_SCHEMA") or "dbo"
    ).strip()
    view_col = (os.environ.get("DB_VIEW_PERMISSIONS_VIEW_COLUMN") or "ViewName").strip()
    email_col = (os.environ.get("DB_VIEW_PERMISSIONS_EMAIL_COLUMN") or "Email").strip()
    for ident, kind in (
        (schema, "schema"),
        (view, "view name"),
        (view_col, "view column"),
        (email_col, "email column"),
    ):
        if not SAFE_IDENTIFIER.match(ident):
            raise ValueError(f"Unsafe {kind} '{ident}' in view-permissions config.")

    if connect is None:
        from db import get_connection
        from settings import load_db_settings

        def connect() -> object:
            return get_connection(load_db_settings())

    conn = connect()
    try:
        cursor = conn.cursor()
        cursor.execute(f"SELECT [{view_col}], [{email_col}] FROM [{schema}].[{view}]")
        cache: dict[str, list[str]] = {}
        for row in cursor.fetchall():
            view_name = str(row[0]).strip().lower() if row[0] is not None else ""
            email = str(row[1]).strip().lower() if row[1] is not None else ""
            if view_name and email:
                cache.setdefault(view_name, []).append(email)
    finally:
        conn.close()
    logger.info(
        "Loaded view-permission entries for %d view(s) from [%s].[%s].",
        len(cache),
        schema,
        view,
    )
    return cache


def load_view_permissions_all_access() -> bool:
    """Whether every authenticated user may access every view (all-access mode).

    Allen & Co runs all-access: the per-view SQL permissions gate is not used and
    ``check_user_has_view_access`` always passes (``user_email`` is still logged for
    audit). Enable with ``VIEW_PERMISSIONS_ALL_ACCESS=true``; default off preserves
    deny-by-default, so the gate can be re-enabled later without a code change.
    """
    raw = (os.environ.get("VIEW_PERMISSIONS_ALL_ACCESS") or "").strip().lower()
    return raw in ("1", "true", "yes")


def load_superuser_emails() -> frozenset[str]:
    """Parse GLEAN_INDEXING_SUPERUSER_ALLOWED_USERS into a frozenset of lowercase emails."""
    raw = (os.environ.get("GLEAN_INDEXING_SUPERUSER_ALLOWED_USERS") or "").strip()
    if not raw:
        return frozenset()
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        logger.error(
            "GLEAN_INDEXING_SUPERUSER_ALLOWED_USERS is not valid JSON — no superusers loaded."
        )
        return frozenset()
    if not isinstance(data, list):
        logger.error("GLEAN_INDEXING_SUPERUSER_ALLOWED_USERS must be a JSON array.")
        return frozenset()
    emails: set[str] = set()
    for item in data:
        if isinstance(item, str) and item.strip():
            emails.add(item.strip().lower())
    if emails:
        logger.info("Loaded %d superuser email(s).", len(emails))
    return frozenset(emails)


def check_user_has_view_access(
    user_email: str,
    view_name: str,
    cache: dict[str, list[str]],
    superuser_emails: frozenset[str],
    all_access: bool = False,
) -> bool:
    """Return True if user_email is permitted to access view_name.

    All-access short-circuit: when ``all_access`` is set every user passes (Allen &
    Co's decided posture). Otherwise: superusers always pass; else the user must
    appear in the view's allow-list from ``cache``. Returns False when the view is
    absent from the cache (deny-by-default) — which, with an empty cache, means
    every non-superuser is denied until the SQL permissions view is configured.
    """
    normalized = user_email.strip().lower()

    if all_access:
        logger.debug(
            "check_user_has_view_access: all-access mode — GRANTED '%s' for '%s'.",
            normalized,
            view_name,
        )
        return True

    if normalized in superuser_emails:
        logger.debug(
            "check_user_has_view_access: '%s' is superuser — GRANTED for '%s'.",
            normalized,
            view_name,
        )
        return True

    allowed_emails = cache.get(view_name.lower())
    if not allowed_emails:
        logger.warning(
            "check_user_has_view_access: no AD/Entra permission entry for '%s' — DENIED to '%s'.",
            view_name,
            normalized,
        )
        return False

    has_access = normalized in {e.strip().lower() for e in allowed_emails}
    logger.info(
        "check_user_has_view_access: '%s' → %s for user '%s'.",
        view_name,
        "GRANTED" if has_access else "DENIED",
        normalized,
    )
    return has_access
