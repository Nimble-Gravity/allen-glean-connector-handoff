"""Declarative catalog of the EMS views the indexer snapshots into Glean.

This is the single place to list the in-scope views ("connectivity is
configuration, not code"). ``registry.build_view_specs`` turns each entry into a
runnable ViewSpec that reads the view and maps every row to one Glean document via
the generic ``rows_to_documents`` builder — no per-view Python required.

HOW TO POPULATE against the real Allen & Co "Conference" schema:
  1. On the dev VM (real DB reachable) run ``python scripts/discover_schema.py``.
     It dumps ``.outputs/schema.json`` and prints ready-to-paste catalog entries
     for every Conference view (with guessed id / title / watermark columns).
  2. Replace the seed entries below with those, correcting the guessed columns
     against the real schema. Set ``schema=None`` to inherit DB_SCHEMA (recommended
     so you set the Conference schema once in .env), or pin it per entry.
  3. Re-run the dry run and inspect ``.outputs/ems_documents.json``.

The entries below are a SEED matching the mock schema (infra/sql/mirror_schema.sql)
so the pipeline and tests run today. The column names are the mock's, NOT confirmed
against the real EMS — treat them as placeholders until step 2.
"""

from collections.abc import Callable
from dataclasses import dataclass, field

import pandas as pd
from glean.api_client.models.documentdefinition import DocumentDefinition
from glean.api_client.models.userreferencedefinition import UserReferenceDefinition

BuildFn = Callable[..., list[DocumentDefinition]]


@dataclass(frozen=True)
class ViewCatalogEntry:
    """One EMS view and how to turn its rows into Glean documents.

    view_name:        the SQL view name (without schema brackets).
    object_type:      Glean object type + document-id prefix (e.g. "attendee").
    id_column:        column used as the stable per-row document id.
    title_columns:    columns concatenated (" – ") into the document title.
    watermark_column: change-tracking column for incremental sync, or None to
                      always full-fetch this view.
    schema:           SQL schema; None inherits the run's DB_SCHEMA default.
    build:            optional custom builder; when None the generic
                      rows_to_documents mapping is used.
    """

    view_name: str
    object_type: str
    id_column: str
    title_columns: tuple[str, ...] = ()
    watermark_column: str | None = "ModifiedDate"
    schema: str | None = None
    build: BuildFn | None = field(default=None, compare=False)


# SEED — mock EMS columns; confirm/replace against the real Conference schema.
VIEW_CATALOG: tuple[ViewCatalogEntry, ...] = (
    ViewCatalogEntry(
        view_name="v_Attendee",
        object_type="attendee",
        id_column="AttendeeID",
        title_columns=("FirstName", "LastName"),
    ),
    ViewCatalogEntry(
        view_name="v_Attendee_Event",
        object_type="attendee_event",
        id_column="AttendeeEventID",
        title_columns=("EventName", "AttendeeID"),
    ),
    ViewCatalogEntry(
        view_name="v_Company",
        object_type="company",
        id_column="CompanyID",
        title_columns=("CompanyName",),
    ),
    ViewCatalogEntry(
        view_name="v_Participation",
        object_type="participation",
        id_column="ParticipationID",
        title_columns=("CompanyID", "AttendeeID"),
    ),
)


def _generic_builder(entry: ViewCatalogEntry) -> BuildFn:
    """Return a build function that maps this view's rows via rows_to_documents.

    Imported lazily to avoid a circular import (registry ← catalog ← _common).
    """
    from allenco_connector.views._common import rows_to_documents

    def build(
        df: pd.DataFrame,
        *,
        datasource: str,
        allowed_users: list[UserReferenceDefinition] | None = None,
    ) -> list[DocumentDefinition]:
        return rows_to_documents(
            df,
            object_type=entry.object_type,
            datasource=datasource,
            id_column=entry.id_column,
            title_columns=entry.title_columns,
            allowed_users=allowed_users,
        )

    return build


def builder_for(entry: ViewCatalogEntry) -> BuildFn:
    """The entry's custom builder if set, else the generic row→document mapping."""
    return entry.build if entry.build is not None else _generic_builder(entry)
