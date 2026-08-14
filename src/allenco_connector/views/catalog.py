"""Declarative catalog of the EMS views the indexer snapshots into Glean.

This is the single place to list the in-scope views ("connectivity is
configuration, not code"). ``registry.build_view_specs`` turns each entry into a
runnable ViewSpec that reads the view and maps every row to one Glean document via
the generic ``rows_to_documents`` builder — no per-view Python required.

The in-scope views are the **`cnf` (Conference) schema** of the Allen & Co
``Conference`` database — 11 views covering attendees, their event profiles,
activities, and travel. Confirmed via ``scripts/discover_schema.py`` against the
real DB (server aml-azr-sql-001, database ``Conference``). Connect with
``DB_NAME=Conference``; each entry pins ``schema="cnf"`` so it works regardless of
``DB_SCHEMA``.

To refine or extend: re-run ``python scripts/discover_schema.py`` on the VM (dumps
``.outputs/schema.json`` + pasteable entries), edit below, then dry-run and inspect
``.outputs/ems_documents_*.json``.

⚠️ Two things to confirm with the client (flagged inline):
  - The 🟡 travel/junction views (v_TravelAir, v_TravelGroupInfo, v_ActivityAttendants)
    lack a single unique row key, so a document-per-row can collide (e.g. multiple
    flights per attendee). The dry run will surface duplicate ids; fix with the real
    PK or a composite id (via a per-entry ``build`` override).
  - Only v_Attendee exposes a real change-tracking column (``UpdatedOn``). The rest
    full-fetch each run (``watermark_column=None``) — the discovery heuristic's
    date guesses (DOB/StartDate/…) are NOT modification timestamps.

NOTE: this catalog now targets the real cnf schema; the local Docker mock
(infra/sql/mirror_schema.sql, dbo) no longer matches it. Update the mock to mirror
these views if you want to keep the local smoke-test loop.
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
    enabled: bool = True  # False → skipped by build_view_specs (not fetched/indexed)
    build: BuildFn | None = field(default=None, compare=False)


# The cnf (Conference) schema — 11 views. Columns confirmed against the real DB
# (scripts/discover_schema.py). schema="cnf" is pinned per entry.
VIEW_CATALOG: tuple[ViewCatalogEntry, ...] = (
    # -- core entities (clear per-row key) ------------------------------------
    ViewCatalogEntry(
        view_name="v_Attendee",
        object_type="attendee",
        id_column="RecordID",
        title_columns=("FirstName", "LastName"),
        watermark_column="UpdatedOn",  # the only real change-tracking column
        schema="cnf",
    ),
    ViewCatalogEntry(
        view_name="v_StartInformation",
        object_type="start_information",
        id_column="EventInstanceAttendeeID",
        title_columns=("FirstName", "LastName"),
        watermark_column=None,
        schema="cnf",
        # DISABLED: ~8M rows and a complex view, so SELECT TOP (N) does NOT short-
        # circuit — a fetch materializes the whole thing and hangs. Re-enable once the
        # client confirms the granularity/event filter for this view (scope question).
        enabled=False,
    ),
    ViewCatalogEntry(
        view_name="v_AttendeeContact",
        object_type="attendee_contact",
        id_column="AttendeeID",
        title_columns=("Email",),
        watermark_column=None,
        schema="cnf",
    ),
    ViewCatalogEntry(
        view_name="v_AssistantsInformation",
        object_type="assistant",
        id_column="RowID",
        title_columns=("Name",),
        watermark_column=None,
        schema="cnf",
    ),
    ViewCatalogEntry(
        view_name="v_Activity",
        object_type="activity",
        id_column="RecordID",
        title_columns=("Name",),
        watermark_column=None,
        schema="cnf",
    ),
    # -- 🟡 travel / junction: id_column is a best guess and may COLLIDE per row.
    #    Confirm the real PK (or use a composite id via a build override).
    ViewCatalogEntry(
        view_name="v_ActivityAttendants",
        object_type="activity_attendant",
        id_column="EventInstanceActivityID",  # TODO: confirm unique per row
        title_columns=("FirstName", "LastName"),
        watermark_column=None,
        schema="cnf",
    ),
    ViewCatalogEntry(
        view_name="v_TravelAir",
        object_type="travel_air",
        id_column="AttendeeID",  # TODO: NOT unique per row (many flights/attendee)
        title_columns=("FirstName", "LastName"),
        watermark_column=None,
        schema="cnf",
    ),
    ViewCatalogEntry(
        view_name="v_TravelGroupInfo",
        object_type="travel_group",
        id_column="HeadID",  # TODO: confirm unique per row
        title_columns=(),
        watermark_column=None,
        schema="cnf",
    ),
    # -- 🔵 small reference/lookup views (low search value; drop if not useful) -
    ViewCatalogEntry(
        view_name="v_Airline",
        object_type="airline",
        id_column="RecordID",
        title_columns=(),
        watermark_column=None,
        schema="cnf",
    ),
    ViewCatalogEntry(
        view_name="v_GarmentSizes",
        object_type="garment_size",
        id_column="RecordID",
        title_columns=("NameAlias",),
        watermark_column=None,
        schema="cnf",
    ),
    ViewCatalogEntry(
        view_name="v_PreferenceType",
        object_type="preference_type",
        id_column="RecordID",
        title_columns=("Description",),
        watermark_column=None,
        schema="cnf",
    ),
)


def _generic_builder(
    entry: ViewCatalogEntry,
    exclude_columns: tuple[str, ...] = (),
    view_url_base: str = "",
) -> BuildFn:
    """Return a build function that maps this view's rows via rows_to_documents.

    ``exclude_columns`` (EXCLUDE_COLUMNS) are dropped from every body; ``view_url_base``
    (VIEW_URL_BASE) stamps a per-row viewURL. Imported lazily to avoid a circular
    import (registry ← catalog ← _common).
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
            view_url_base=view_url_base,
            exclude_columns=exclude_columns,
        )

    return build


def builder_for(
    entry: ViewCatalogEntry,
    exclude_columns: tuple[str, ...] = (),
    view_url_base: str = "",
) -> BuildFn:
    """The entry's custom builder if set, else the generic row→document mapping.

    A custom ``build`` handles its own shaping; ``exclude_columns`` / ``view_url_base``
    apply only to the generic mapping.
    """
    if entry.build is not None:
        return entry.build
    return _generic_builder(entry, exclude_columns, view_url_base)
