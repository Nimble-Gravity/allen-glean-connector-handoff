"""Load user → AD/Entra group memberships from a SQL view.

Allen & Co's decided permission source: a read-only SQL view in the EMS DB that
mirrors directory group membership, one row per (user, group). This module reads
it and returns ``GlobalUser`` records whose ``groups`` drive document ACLs
(glean_index.permission_policies) and Glean datasource-user indexing.

The view/columns are configured via env (config.GroupsSettings). When DB_GROUPS_VIEW
is unset the feature is off and this returns []. Identifiers from config are
validated against a strict allow-list and bracket-quoted before interpolation (the
values are operator-controlled, not end-user input, but we fail loud on typos and
never build a query from an unsafe identifier).
"""

import hashlib
import logging
import re

import pyodbc

from config.config import GroupsSettings
from glean_index.types.users import GlobalUser

logger = logging.getLogger(__name__)

_SAFE_IDENTIFIER = re.compile(r"^[A-Za-z0-9_]+$")


def _safe_identifier(name: str, kind: str) -> str:
    """Return ``name`` if it is a bare SQL identifier, else raise ValueError."""
    if not _SAFE_IDENTIFIER.match(name or ""):
        raise ValueError(
            f"Unsafe {kind} '{name}' in groups-view config; "
            "only letters, digits, and underscore are allowed."
        )
    return name


def _derive_user_id(email_lower: str) -> str:
    """sha256 of the lowercased email — matches the superuser id derivation."""
    return hashlib.sha256(email_lower.encode()).hexdigest()


def load_users_with_groups(
    conn: pyodbc.Connection | None,
    settings: GroupsSettings,
) -> list[GlobalUser]:
    """Read (email, group[, name]) rows from the configured groups view.

    Aggregates to one GlobalUser per email with a sorted tuple of groups. Returns
    [] when the view is not configured or no connection is available (e.g. a dry
    run with an unreachable DB), so the pipeline still runs on superuser ACLs.
    """
    if not settings.view:
        logger.info("Groups view not configured (DB_GROUPS_VIEW empty) — no source users.")
        return []
    if conn is None:
        logger.warning("Groups view configured but no DB connection — returning no source users.")
        return []

    schema = _safe_identifier(settings.schema, "schema")
    view = _safe_identifier(settings.view, "view name")
    email_col = _safe_identifier(settings.email_column, "email column")
    group_col = _safe_identifier(settings.group_column, "group column")
    columns = [f"[{email_col}]", f"[{group_col}]"]
    name_col = None
    if settings.name_column:
        name_col = _safe_identifier(settings.name_column, "name column")
        columns.append(f"[{name_col}]")

    sql = f"SELECT {', '.join(columns)} FROM [{schema}].[{view}]"
    cursor = conn.cursor()
    cursor.execute(sql)
    rows = cursor.fetchall()

    by_email: dict[str, dict] = {}
    for row in rows:
        email = (str(row[0]).strip().lower()) if row[0] is not None else ""
        if not email:
            continue
        group = str(row[1]).strip() if row[1] is not None else ""
        name = ""
        if name_col is not None and len(row) > 2 and row[2] is not None:
            name = str(row[2]).strip()
        entry = by_email.setdefault(email, {"name": "", "groups": set()})
        if group:
            entry["groups"].add(group)
        if name and not entry["name"]:
            entry["name"] = name

    users = [
        GlobalUser(
            datasource_user_id=_derive_user_id(email),
            email=email,
            name=data["name"] or None,
            groups=tuple(sorted(data["groups"])),
        )
        for email, data in by_email.items()
    ]
    logger.info(
        "Loaded %d user(s) with group memberships from [%s].[%s].",
        len(users),
        schema,
        view,
    )
    return users
