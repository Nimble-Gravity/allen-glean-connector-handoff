"""Tests for the AD/Entra document-access policy stub and the user model."""

from glean_index.permission_policies import (
    IndexedDocumentKind,
    user_may_access_indexed_document,
)
from glean_index.types.users import (
    GlobalUser,
    build_allowed_user_references,
    build_users_for_permissions_indexing,
)


def test_all_document_kinds_denied_in_stub():
    user = GlobalUser(datasource_user_id="id1", email="a@allenandco.com", groups=("EMS-Readers",))
    # Skeleton denies by default until the AD/Entra rule is wired.
    for kind in IndexedDocumentKind:
        assert user_may_access_indexed_document(user, kind) is False


def test_global_user_carries_groups():
    user = GlobalUser(datasource_user_id="id", email="a@b.com", groups=("g1", "g2"))
    assert user.groups == ("g1", "g2")


def test_build_allowed_user_references_skips_incomplete():
    users = [
        GlobalUser(datasource_user_id="id1", email="a@b.com"),
        GlobalUser(datasource_user_id="", email="x@b.com"),  # no id → skipped
    ]
    refs = build_allowed_user_references(users)
    assert len(refs) == 1
    assert refs[0].email == "a@b.com"


def test_build_users_for_permissions_indexing_defaults_name_to_email():
    users = [GlobalUser(datasource_user_id="id1", email="a@b.com")]
    out = build_users_for_permissions_indexing(users)
    assert out[0].name == "a@b.com"
    assert out[0].user_id == "id1"
    assert out[0].is_active is True
