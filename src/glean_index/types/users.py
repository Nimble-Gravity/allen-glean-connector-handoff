from collections.abc import Iterable
from dataclasses import dataclass

from glean.api_client.models.datasourceuserdefinition import DatasourceUserDefinition
from glean.api_client.models.userreferencedefinition import UserReferenceDefinition


@dataclass(frozen=True)
class GlobalUser:
    """Datasource user identity for document permissions and Glean user indexing.

    ``groups`` holds the user's Active Directory / Entra ID group memberships.
    Allen & Co document access is derived from these groups (see
    glean_index/permission_policies.py). This replaces SMART's
    ``can_access_financial_data`` boolean.
    """

    datasource_user_id: str
    email: str
    name: str | None = None
    groups: tuple[str, ...] = ()


def build_allowed_user_references(
    users: Iterable[GlobalUser],
) -> list[UserReferenceDefinition]:
    """Build allowedUsers entries for document permissions."""
    out: list[UserReferenceDefinition] = []
    for u in users:
        uid = (u.datasource_user_id or "").strip()
        email = (u.email or "").strip()
        if not uid or not email:
            continue
        out.append(UserReferenceDefinition(datasource_user_id=uid, email=email))
    return out


def build_users_for_permissions_indexing(
    users: Iterable[GlobalUser],
) -> list[DatasourceUserDefinition]:
    """Build users for bulk_index_users (Glean permissions / datasource users API)."""
    out: list[DatasourceUserDefinition] = []
    for u in users:
        uid = (u.datasource_user_id or "").strip()
        email = (u.email or "").strip()
        if not uid or not email:
            continue
        name = (u.name or "").strip() or email
        out.append(DatasourceUserDefinition(email=email, name=name, user_id=uid, is_active=True))
    return out
