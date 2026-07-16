"""View-level permission checks for the Custom Action API.

Intentionally does not import from src/ to avoid the Glean SDK dependency.

⚠️ SKELETON STUB. SMART sourced per-view access from a SQL ViewPermissions table
(`[GleanSMART].[dbo].[ViewPermissions]`). Allen & Co derives access from Active
Directory / Entra ID groups instead — the concrete source (Microsoft Graph vs a
SQL view mirroring AD groups) is an open decision (see CLAUDE.md → "Open
questions"). Until it is wired, the permission cache is empty and only superusers
(GLEAN_INDEXING_SUPERUSER_ALLOWED_USERS) pass; every other user is denied.
"""

import json
import logging
import os

logger = logging.getLogger(__name__)

PERMISSION_DENIED_MESSAGE = "The user does not have permission to access this view."


def load_view_permissions_cache() -> dict[str, list[str]]:
    """Return {lowercase_view_name: [allowed_emails]} — currently an empty stub.

    TODO Allen & Co: populate from AD/Entra group membership (Graph or a SQL view
    that mirrors AD groups). Called once at API startup.
    """
    logger.warning(
        "load_view_permissions_cache: AD/Entra permission source not yet wired — "
        "returning empty cache (only superusers will pass view-access checks)."
    )
    return {}


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
) -> bool:
    """Return True if user_email is permitted to access view_name.

    Fast path: superusers always pass. Otherwise the user must appear in the
    view's allow-list from ``cache``. Returns False when the view is absent from
    the cache (deny-by-default) — which, with the current empty stub cache, means
    every non-superuser is denied until AD/Entra is wired.
    """
    normalized = user_email.strip().lower()

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
