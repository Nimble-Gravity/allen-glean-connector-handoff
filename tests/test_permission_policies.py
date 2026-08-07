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


def test_denied_when_no_allowed_groups_configured(monkeypatch):
    monkeypatch.delenv("GLEAN_ALLOWED_GROUPS", raising=False)
    user = GlobalUser(datasource_user_id="id1", email="a@allenandco.com", groups=("EMS-Readers",))
    # Deny-by-default until GLEAN_ALLOWED_GROUPS names the reader group(s).
    for kind in IndexedDocumentKind:
        assert user_may_access_indexed_document(user, kind) is False


def test_granted_when_user_in_an_allowed_group(monkeypatch):
    monkeypatch.setenv("GLEAN_ALLOWED_GROUPS", "EMS-Readers, Analysts")
    user = GlobalUser(datasource_user_id="id1", email="a@allenandco.com", groups=("EMS-Readers",))
    for kind in IndexedDocumentKind:
        assert user_may_access_indexed_document(user, kind) is True


def test_denied_when_user_not_in_allowed_group(monkeypatch):
    monkeypatch.setenv("GLEAN_ALLOWED_GROUPS", "Admins")
    user = GlobalUser(datasource_user_id="id1", email="a@allenandco.com", groups=("EMS-Readers",))
    assert user_may_access_indexed_document(user, IndexedDocumentKind.COMPANY) is False


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
