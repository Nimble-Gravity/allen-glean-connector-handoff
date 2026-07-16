"""Optional Glean indexing superusers loaded from environment JSON.

Superusers are merged into every indexed document's allowedUsers and, when absent
from the datasource user list, appended to the user bulk upload so Glean can resolve them.
"""

import hashlib
import json
import logging
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Any

from glean.api_client.models.datasourceuserdefinition import DatasourceUserDefinition
from glean.api_client.models.userreferencedefinition import UserReferenceDefinition

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class IndexingSuperuser:
    """One superuser entry from GLEAN_INDEXING_SUPERUSER_ALLOWED_USERS JSON."""

    datasource_user_id: str
    email: str
    name: str | None = None

    def as_user_reference(self) -> UserReferenceDefinition:
        return UserReferenceDefinition(
            datasource_user_id=self.datasource_user_id,
            email=self.email,
        )

    def glean_display_name(self) -> str:
        n = (self.name or "").strip()
        return n or self.email


def load_indexing_superusers_from_json(raw: str | None) -> list[IndexingSuperuser]:
    """Parse a JSON array of email strings into IndexingSuperuser entries.

    Expected format: ["user@example.com", "other@example.com"]. datasource_user_id
    is derived automatically as sha256(email.lower()).
    """
    text = (raw or "").strip()
    if not text:
        return []
    try:
        data = json.loads(text)
    except json.JSONDecodeError as exc:
        logger.error(
            "GLEAN_INDEXING_SUPERUSER_ALLOWED_USERS is not valid JSON — no superusers loaded. "
            "Error: %s. Raw value: %r",
            exc,
            text,
        )
        return []
    if not isinstance(data, list):
        logger.error(
            "GLEAN_INDEXING_SUPERUSER_ALLOWED_USERS must be a JSON array; got %s. "
            'Expected format: ["email1@company.com", "email2@company.com"]',
            type(data).__name__,
        )
        return []
    out: list[IndexingSuperuser] = []
    for index, item in enumerate(data):
        entry = _superuser_from_row(item, index)
        if entry is not None:
            out.append(entry)
    if out:
        logger.info(
            "Loaded %s superuser(s) from GLEAN_INDEXING_SUPERUSER_ALLOWED_USERS: %s",
            len(out),
            ", ".join(s.email for s in out),
        )
    elif text:
        logger.warning(
            "GLEAN_INDEXING_SUPERUSER_ALLOWED_USERS was set but no valid emails were loaded."
        )
    return out


def merge_allowed_user_references(
    base: Iterable[UserReferenceDefinition],
    extra: Iterable[UserReferenceDefinition],
) -> list[UserReferenceDefinition]:
    """Append extra references, skipping duplicates by datasource_user_id (first wins)."""
    seen_ids: set[str] = set()
    out: list[UserReferenceDefinition] = []
    for ref in (*base, *extra):
        uid = (ref.datasource_user_id or "").strip()
        email = (ref.email or "").strip()
        if not uid or not email or uid in seen_ids:
            continue
        seen_ids.add(uid)
        out.append(ref)
    return out


def extend_permissions_users_for_superusers(
    indexed_users: list[DatasourceUserDefinition],
    *,
    global_datasource_user_ids: set[str],
    superusers: Sequence[IndexingSuperuser],
) -> list[DatasourceUserDefinition]:
    """Return a copy of indexed_users plus superusers not already present.

    Deduplicates by datasource_user_id and email — a superuser already indexed
    under the same sha256 ID is not added twice.
    """
    if not superusers:
        return list(indexed_users)
    out = list(indexed_users)
    existing_ids = {str(u.user_id).strip() for u in out if u.user_id is not None}
    existing_emails = {(u.email or "").strip().lower() for u in out if u.email}
    for s in superusers:
        uid = s.datasource_user_id.strip()
        email = s.email.strip()
        if not uid or not email:
            continue
        if (
            uid in global_datasource_user_ids
            or uid in existing_ids
            or email.lower() in existing_emails
        ):
            continue
        out.append(
            DatasourceUserDefinition(
                email=email,
                name=s.glean_display_name(),
                user_id=uid,
                is_active=True,
            )
        )
        existing_ids.add(uid)
        existing_emails.add(email.lower())
    added = len(out) - len(indexed_users)
    if added:
        logger.info("Added %s superuser(s) to Glean datasource user bulk index.", added)
    return out


def _superuser_from_row(item: Any, index: int) -> IndexingSuperuser | None:
    if not isinstance(item, str):
        logger.warning("Superuser entry %s is not a string email; skipping.", index)
        return None
    email = item.strip().lower()
    if not email:
        logger.warning("Superuser entry %s is an empty string; skipping.", index)
        return None
    uid = hashlib.sha256(email.encode()).hexdigest()
    return IndexingSuperuser(datasource_user_id=uid, email=email)
