"""Document-access policy for Allen & Co indexed documents.

Allen & Co ties Glean document access to **Active Directory / Entra ID group
membership** (not SMART's SQL "security view" + can_access_financial_data flag).
This module is the single place that decides, per document kind, whether a user
may see a document — keep the rules here so views and the indexer stay dumb.

⚠️ SKELETON STUB. The concrete rule depends on an open decision (see CLAUDE.md →
"Open questions"): whether group memberships come from Microsoft Graph or from a
SQL view that mirrors AD groups. Until that is wired, this denies by default.
Replace the TODO branches with real ``<group> in user.groups`` checks before
production.
"""

from enum import StrEnum
from typing import assert_never

from glean_index.types.users import GlobalUser


class IndexedDocumentKind(StrEnum):
    """The kinds of documents the indexer pushes — one per EMS view in scope."""

    ATTENDEE = "attendee"
    ATTENDEE_EVENT = "attendee_event"
    COMPANY = "company"
    PARTICIPATION = "participation"


def user_may_access_indexed_document(user: GlobalUser, kind: IndexedDocumentKind) -> bool:
    """Return True if ``user`` may access a document of ``kind``.

    The ``match`` is exhaustive (assert_never) so adding a new IndexedDocumentKind
    without deciding its access rule is a type error, not a silent allow.
    """
    match kind:
        case (
            IndexedDocumentKind.ATTENDEE
            | IndexedDocumentKind.ATTENDEE_EVENT
            | IndexedDocumentKind.COMPANY
            | IndexedDocumentKind.PARTICIPATION
        ):
            # TODO Allen & Co: replace with the real AD/Entra group rule, e.g.
            #   return "EMS-Readers" in user.groups
            return False
        case _:  # pragma: no cover - exhaustiveness guard
            assert_never(kind)
