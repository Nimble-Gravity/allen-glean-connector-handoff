"""Declarative catalog of the EMS report views the indexer snapshots into Glean.

This is the single place to list the in-scope views ("connectivity is
configuration, not code"). ``registry.build_view_specs`` turns each entry into a
runnable ViewSpec that reads the view and maps every row to one Glean document via
the generic ``rows_to_documents`` builder — no per-view Python required.

**Source = the `rpt` (report) schema** of the Allen & Co ``Conference`` database —
the client's recommended, report-optimized (already-joined) views, confirmed via
``scripts/discover_schema.py``. Each entry pins ``schema="rpt"`` so it works
regardless of ``DB_SCHEMA``.

The catalog implements the **layered, EventInstanceID-anchored document model**
(see ``docs/document-model.md``):
  - **Tier 1 — ``attendee``** (``v_Attendee_Global``): one doc per ``AttendeeID`` with
    stable global identity (name, company, dietary/allergy).
  - **Tier 2 — ``attendeeConf``** (``v_Invitation_CurrentStatus``): one doc per
    ``(AttendeeID, EventInstanceID)`` — the person's status at a specific conference.
    Self-sufficient (person name + conference code/name + status) so Glean can answer
    "was <name> at <conference>?". ``EventInstanceID`` rides as a custom property for
    per-conference filtering.
  - **Tier 3 — detail** (travel / activity / catering): per-conference facts, keyed by
    a composite id. Shipped **disabled** — enable after Tier 1/2 dry-runs look good.

Conference identity: ``EventInstanceShort`` (e.g. "SV26") / ``EventInstance``
("Sun Valley Conference 2026") come inline on Tier 2. The **current** conference is
``IsDefault = 1`` on the EventInstance master (``dbo.v_EventInstance``); the hourly job
filters Tier 2 to that ``EventInstanceID`` (job concern, not the catalog).

To refine/extend: re-run ``scripts/discover_schema.py`` on the VM, edit below, then
dry-run and inspect ``.outputs/ems_documents_*.json`` (verify unique ids, readable
titles, PII absent). Use ``id_columns`` for composite keys and ``property_columns`` for
filterable metadata — no per-view Python needed for the common case.

⚠️ Tier-2 completeness: ``v_Invitation_CurrentStatus`` covers *invited* guests. If the
client needs the complete roster (local staff / vendors / children who never went
through the invitation flow), swap or add ``v_EventInstance_Attendee`` (the registration
record the client named — has ``UpdatedOn`` for incremental sync, but carries IDs, not
the person name / conference code, so its title is weaker). Decide after a dry-run.

NOTE: this catalog targets the real ``rpt`` schema; the local Docker mock
(``infra/sql/mirror_schema.sql``, dbo) no longer matches it.
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
    id_columns:       composite key columns (joined by ":") — overrides id_column.
                      Use for per-conference docs keyed by (AttendeeID,
                      EventInstanceID) and for junction rows with no single key.
    title_columns:    columns concatenated (" – ") into the document title.
    property_columns: columns emitted as Glean custom properties (filterable
                      metadata, e.g. EventInstanceID) as well as in the body.
    watermark_column: change-tracking column for incremental sync, or None to
                      always full-fetch this view.
    schema:           SQL schema; None inherits the run's DB_SCHEMA default.
    build:            optional custom builder; when None the generic
                      rows_to_documents mapping is used.
    """

    view_name: str
    object_type: str
    id_column: str
    id_columns: tuple[str, ...] = ()
    title_columns: tuple[str, ...] = ()
    property_columns: tuple[str, ...] = ()
    watermark_column: str | None = "ModifiedDate"
    schema: str | None = None
    enabled: bool = True  # False → skipped by build_view_specs (not fetched/indexed)
    build: BuildFn | None = field(default=None, compare=False)


# The rpt (report) schema. Columns confirmed against the real DB
# (scripts/discover_schema.py → .outputs/schema.json). schema="rpt" is pinned per entry.
VIEW_CATALOG: tuple[ViewCatalogEntry, ...] = (
    # ── Tier 1 — Attendee (global identity): one document per AttendeeID ──────
    ViewCatalogEntry(
        view_name="v_Attendee_Global",
        object_type="attendee",
        id_column="AttendeeID",
        title_columns=("InformalName", "Company"),  # "Jane Doe – Acme Corp"
        property_columns=("AttendeeID",),
        watermark_column=None,  # global view has no change-tracking column → full-fetch
        schema="rpt",
    ),
    # ── Tier 2 — Attendee @ Conference: one doc per (AttendeeID, EventInstanceID) ─
    #    Self-sufficient (person name + conference code/name + status) so Glean can
    #    answer "was <name> at <conference>?". EventInstanceID rides as a property.
    ViewCatalogEntry(
        view_name="v_Invitation_CurrentStatus",
        object_type="attendeeConf",
        id_column="AttendeeID",
        id_columns=("AttendeeID", "EventInstanceID"),
        title_columns=("FormalName", "EventInstanceShort"),  # "Jane Doe – SV26"
        property_columns=(
            "AttendeeID",
            "EventInstanceID",
            "EventInstanceShort",
            "EventYear",
            "InvitationStatus",
            "Company",
        ),
        watermark_column=None,  # "current status" view; full-fetch (row-capped in test)
        schema="rpt",
    ),
    # ── Tier 3 — per-conference detail (DISABLED for v1) ──────────────────────
    #    Enable once Tier 1/2 dry-runs look good. Composite ids keep each fact unique;
    #    EventInstanceID rides as a property for per-conference filtering. Confirm the
    #    title/property columns against a dry-run before enabling.
    ViewCatalogEntry(
        view_name="v_TravelAir",
        object_type="travelAir",
        id_column="RecordID",
        id_columns=("AttendeeID", "EventInstanceID", "RecordID"),
        title_columns=("AirlineName", "FlightNumber"),
        property_columns=("AttendeeID", "EventInstanceID", "TravelRecordTypeName", "TravelDate"),
        watermark_column="UpdatedOn",
        schema="rpt",
        enabled=False,
    ),
    ViewCatalogEntry(
        view_name="v_TravelGround",
        object_type="travelGround",
        id_column="RecordID",
        id_columns=("AttendeeID", "EventInstanceID", "RecordID"),
        title_columns=("TravelMethodGroundName", "TravelDate"),
        property_columns=("AttendeeID", "EventInstanceID", "TravelRecordTypeName", "TravelDate"),
        watermark_column="UpdatedOn",
        schema="rpt",
        enabled=False,
    ),
    ViewCatalogEntry(
        view_name="v_Activity_Attendee_TimeRange",
        object_type="activityAttendee",
        id_column="EventInstanceActivityID",
        id_columns=("AttendeeID", "EventInstanceID", "EventInstanceActivityID"),
        title_columns=(),
        property_columns=("AttendeeID", "EventInstanceID", "ActivityID"),
        watermark_column=None,
        schema="rpt",
        enabled=False,
    ),
    ViewCatalogEntry(
        view_name="v_Catering_TableAssignment",
        object_type="catering",
        id_column="EventInstanceActivityID",
        id_columns=("AttendeeID", "EventInstanceID", "EventInstanceActivityID"),
        title_columns=("Activity", "FormalName"),
        property_columns=("AttendeeID", "EventInstanceID", "ActivityID"),
        watermark_column=None,
        schema="rpt",
        enabled=False,
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
            id_columns=entry.id_columns,
            title_columns=entry.title_columns,
            property_columns=entry.property_columns,
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
