"""Shared helpers for turning EMS view rows into Glean documents.

SKELETON: ``rows_to_documents`` is a generic one-document-per-row mapping so the
pipeline runs end-to-end today. Replace each view's call with real shaping
(grouping, sections, computed fields, ACLs) as the EMS schema is confirmed —
mirror SMART's ``views/daily_financial_extract/document_builder.py`` for the
richer pattern.
"""

import fnmatch
import logging
from collections.abc import Iterable, Sequence
from typing import Any

import pandas as pd
from glean.api_client.models.customproperty import CustomProperty
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
    id_columns: Sequence[str] = (),
    property_columns: Sequence[str] = (),
    allowed_users: Iterable[UserReferenceDefinition] | None = None,
    view_url: str | None = None,
    view_url_base: str = "",
    exclude_columns: Sequence[str] = (),
) -> list[DocumentDefinition]:
    """Build one Glean document per DataFrame row (generic mapping).

    Tolerant of missing columns: falls back to the row position for the id and to
    ``object_type`` for the title so a view builds even before the real EMS column
    names are confirmed. ``exclude_columns`` are dropped from the document body — e.g.
    PII fields not cleared for indexing. Each entry is a **case-insensitive glob**, so
    a pattern like ``License*`` drops every license column (LicenseName, LicenseState,
    LicenseCountryName, …) — exact names (no wildcard) still match exactly.

    ``id_columns`` (when non-empty) builds a **composite** row key from several
    columns' values joined by ``:`` — use it for per-conference documents keyed by
    ``(AttendeeID, EventInstanceID)`` and for junction rows without a single unique
    key (avoids the collisions that force post-hoc dedup). It takes precedence over
    ``id_column``.

    ``property_columns`` are emitted as Glean **custom properties** (filterable
    metadata) in addition to appearing in the body — e.g. ``EventInstanceID`` so the
    assistant can answer "was X at conference Y?". Missing/null values are skipped.

    Glean requires a non-empty viewURL per document. When ``view_url_base`` is set, a
    per-row URL ``{base}/{object_type}/{key}`` is stamped (unless an explicit
    ``view_url`` is given). Replace the base with the real EMS/portal URL later.
    """
    allowed = list(allowed_users or [])
    exclude_patterns = [c.strip().lower() for c in exclude_columns if c.strip()]
    url_base = (view_url_base or "").rstrip("/")
    docs: list[DocumentDefinition] = []

    for position, (_, row) in enumerate(df.iterrows()):
        payload = {
            key: _jsonable(value)
            for key, value in row.to_dict().items()
            if not _is_excluded(key, exclude_patterns)
        }
        row_key = _row_key(row, id_columns, id_column)
        # Prefix with object_type so ids stay unique ACROSS views that reuse a column
        # name (several views key on RecordID). Uniqueness WITHIN a view depends on the
        # key columns being a real per-row key — use id_columns for composite keys.
        document_id = f"{object_type}:{row_key or position}"

        title_parts = [str(row[c]) for c in title_columns if c in row and pd.notna(row[c])]
        # Fall back to the id (already prefixed with object_type) rather than repeating it.
        title = " – ".join(title_parts) if title_parts else document_id

        doc_view_url = view_url
        if not doc_view_url and url_base:
            doc_view_url = f"{url_base}/{object_type}/{row_key or position}"

        # Values are stringified: the datasource declares every custom property as TEXT
        # (see scripts/setup_datasource.py), so ints/dates go up as strings to match.
        custom_properties = [
            CustomProperty(name=col, value=str(_jsonable(row[col])))
            for col in property_columns
            if col in row and pd.notna(row[col])
        ]

        docs.append(
            build_document(
                object_type=object_type,
                datasource=datasource,
                document_id=document_id,
                title=title,
                view_url=doc_view_url,
                body_payload=payload,
                allowed_users=allowed or None,
                custom_properties=custom_properties or None,
            )
        )

    logger.info("rows_to_documents[%s]: built %d document(s).", object_type, len(docs))
    return docs


def _row_key(row: pd.Series, id_columns: Sequence[str], id_column: str) -> str:
    """The per-row id fragment: a ``:``-joined composite of ``id_columns`` (skipping
    missing/null values) when given, else the single ``id_column``. Empty when no key
    column is present (caller falls back to the row position)."""
    cols = list(id_columns) if id_columns else [id_column]
    parts = [
        str(row[c]).strip() for c in cols if c in row and pd.notna(row[c]) and str(row[c]).strip()
    ]
    return ":".join(parts)


def _is_excluded(column: str, patterns: Sequence[str]) -> bool:
    """True if a column name matches any EXCLUDE_COLUMNS glob (case-insensitive).

    ``patterns`` are pre-lowercased; a wildcard entry like ``license*`` drops every
    license column, while a plain name matches only that exact column.
    """
    name = column.lower()
    return any(fnmatch.fnmatchcase(name, pattern) for pattern in patterns)


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
