"""Document-access policy for Allen & Co indexed documents.

Allen & Co ties Glean document access to **Active Directory / Entra ID group
membership**, sourced from a **SQL view that mirrors AD groups** (the decided
option — not Microsoft Graph; see allenco_connector.groups). This module is the
single place that decides, per document kind, whether a user with a given set of
groups may see a document — keep the rules here so views and the indexer stay dumb.

The set of groups that grant access is configured via ``GLEAN_ALLOWED_GROUPS``
(comma-separated) — "connectivity is configuration, not code". When that is unset
the policy denies by default (no user passes), which is the safe skeleton state
until the real EMS-reader group name(s) are confirmed against the directory.
"""

import os
from enum import StrEnum
from typing import assert_never

from glean_index.types.users import GlobalUser


class IndexedDocumentKind(StrEnum):
    """The kinds of documents the indexer pushes — one per EMS view in scope."""

    ATTENDEE = "attendee"
    ATTENDEE_EVENT = "attendee_event"
    COMPANY = "company"
    PARTICIPATION = "participation"


def load_allowed_groups() -> frozenset[str]:
    """AD/Entra groups that grant access to indexed documents.

    Parsed from GLEAN_ALLOWED_GROUPS (comma-separated). Empty when unset →
    deny-by-default.
    """
    raw = (os.environ.get("GLEAN_ALLOWED_GROUPS") or "").strip()
    if not raw:
        return frozenset()
    return frozenset(g.strip() for g in raw.split(",") if g.strip())


def user_may_access_indexed_document(user: GlobalUser, kind: IndexedDocumentKind) -> bool:
    """Return True if ``user`` may access a document of ``kind``.

    Access is granted when the user is a member of any group in
    ``GLEAN_ALLOWED_GROUPS``. The ``match`` is exhaustive (assert_never) so adding a
    new IndexedDocumentKind without deciding its access rule is a type error, not a
    silent allow. All in-scope EMS kinds currently share one rule; split the branch
    when a kind needs a distinct group.
    """
    match kind:
        case (
            IndexedDocumentKind.ATTENDEE
            | IndexedDocumentKind.ATTENDEE_EVENT
            | IndexedDocumentKind.COMPANY
            | IndexedDocumentKind.PARTICIPATION
        ):
            return bool(load_allowed_groups().intersection(user.groups))
        case _:  # pragma: no cover - exhaustiveness guard
            assert_never(kind)
