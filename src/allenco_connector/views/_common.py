"""Shared helpers for turning EMS view rows into Glean documents.

SKELETON: ``rows_to_documents`` is a generic one-document-per-row mapping so the
pipeline runs end-to-end today. Replace each view's call with real shaping
(grouping, sections, computed fields, ACLs) as the EMS schema is confirmed —
mirror SMART's ``views/daily_financial_extract/document_builder.py`` for the
richer pattern.
"""

import logging
from collections.abc import Iterable, Sequence
from typing import Any

import pandas as pd
from glean.api_client.models.documentdefinition import DocumentDefinition
from glean.api_client.models.userreferencedefinition import UserReferenceDefinition

from glean_index.types.documents import build_document

logger = logging.getLogger(__name__)


def rows_to_documents(
    df: pd.DataFrame,
    *,
    object_type: str,
    datasource: str,
    id_column: str,
    title_columns: Sequence[str],
    allowed_users: Iterable[UserReferenceDefinition] | None = None,
    view_url: str | None = None,
) -> list[DocumentDefinition]:
    """Build one Glean document per DataFrame row (generic skeleton mapping).

    Tolerant of missing columns: falls back to the row position for the id and to
    ``object_type`` for the title so a stub view builds even before the real EMS
    column names are confirmed.
    """
    allowed = list(allowed_users or [])
    docs: list[DocumentDefinition] = []

    for position, (_, row) in enumerate(df.iterrows()):
        payload = {key: _jsonable(value) for key, value in row.to_dict().items()}
        raw_id = row[id_column] if id_column in row else None
        document_id = str(raw_id).strip() if raw_id is not None and pd.notna(raw_id) else ""
        if not document_id:
            document_id = f"{object_type}:{position}"

        title_parts = [str(row[c]) for c in title_columns if c in row and pd.notna(row[c])]
        title = " – ".join(title_parts) if title_parts else f"{object_type} {document_id}"

        docs.append(
            build_document(
                object_type=object_type,
                datasource=datasource,
                document_id=document_id,
                title=title,
                view_url=view_url,
                body_payload=payload,
                allowed_users=allowed or None,
            )
        )

    logger.info("rows_to_documents[%s]: built %d document(s).", object_type, len(docs))
    return docs


def _jsonable(value: Any) -> Any:
    """Coerce a pandas/pyodbc scalar into a JSON-serializable Python value."""
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except (TypeError, ValueError):
        # Arrays / non-scalar values: fall through to the checks below.
        pass
    if hasattr(value, "isoformat"):  # Timestamp / datetime / date / time
        return value.isoformat()
    if hasattr(value, "item"):  # numpy scalar → native Python
        try:
            return value.item()
        except (ValueError, AttributeError):
            pass
    if isinstance(value, (int, float, str, bool)):
        return value
    return str(value)
