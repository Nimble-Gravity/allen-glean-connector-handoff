import json
import time
from collections.abc import Iterable
from typing import Any

from glean.api_client.models.contentdefinition import ContentDefinition
from glean.api_client.models.customproperty import CustomProperty
from glean.api_client.models.documentdefinition import DocumentDefinition
from glean.api_client.models.documentpermissionsdefinition import (
    DocumentPermissionsDefinition,
)
from glean.api_client.models.userreferencedefinition import UserReferenceDefinition


def build_document(
    *,
    object_type: str,
    datasource: str,
    document_id: str,
    title: str,
    view_url: str | None,
    body_payload: Any,
    allowed_users: Iterable[UserReferenceDefinition] | None = None,
    created_at: int | None = None,
    updated_at: int | None = None,
    custom_properties: list[CustomProperty] | None = None,
) -> DocumentDefinition:
    """Build a Glean Indexing API document with a JSON body."""
    created = created_at if created_at is not None else now_epoch_seconds()
    updated = updated_at if updated_at is not None else created

    view_url_norm = (view_url or "").strip() or None

    body_text = json.dumps(body_payload, indent=2, sort_keys=True)
    body = ContentDefinition(mime_type="text/plain", text_content=body_text)

    props = list(custom_properties or [])

    permissions = None
    allowed_users_list = list(allowed_users or [])
    if allowed_users_list:
        permissions = DocumentPermissionsDefinition(allowed_users=allowed_users_list)

    return DocumentDefinition(
        object_type=object_type,
        datasource=datasource,
        id=document_id,
        title=title,
        view_url=view_url_norm,
        created_at=created,
        updated_at=updated,
        permissions=permissions,
        body=body,
        custom_properties=props,
    )


def now_epoch_seconds() -> int:
    return int(time.time())


def build_json_body(payload: Any, *, indent: int = 2) -> ContentDefinition:
    """Create a ContentDefinition body containing JSON as text/plain."""
    text = json.dumps(payload, indent=indent, sort_keys=True)
    return ContentDefinition(mime_type="text/plain", text_content=text)
