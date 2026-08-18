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
(see ``docs/document-model.md``), split by BIND status on the read replica:

**Enabled (bind today, no ConferenceImage):**
  - **Tier 2 — ``attendeeConf``** (``v_EventInstance_Attendee``): one doc per
    ``(AttendeeID, EventInstanceID)`` — the registration/attendance record the client
    named. Carries IDs + company (no person name in this view), ``UpdatedOn`` for
    incremental sync, and ``EventInstanceID`` as a custom property.
  - **Tier 3 — detail** (``catering``, ``activityAttendee``, ``travelAir``,
    ``travelGround``): per-conference facts, composite-keyed. ``catering``
    (``v_Catering_TableAssignment``) carries the person name.

**Disabled (blocked on ConferenceImage — the name-bearing views):**
  - **Tier 1 — ``attendee``** (``v_Attendee_Global``) and **``attendeeStatus``**
    (``v_Invitation_CurrentStatus``, name + conference code + status — the richest doc
    for "was <name> at <conference>?"). Their definitions transitively read
    ``ConferenceImage.dbo.Attendee_Picture`` (the photo table), which is not present on
    the replica → SQL 4413. **Enable them once the client grants read access to
    ``ConferenceImage``.** Verified with ``scripts/probe_views.py``.

Conference identity: ``EventInstanceShort`` (e.g. "SV26") / ``EventInstance`` come inline
on the disabled name-bearing views; the **current** conference is ``IsDefault = 1`` on the
EventInstance master (``dbo.v_EventInstance``); the hourly job filters Tier 2 to that
``EventInstanceID`` (job concern, not the catalog).

To refine/extend: run ``scripts/probe_views.py`` (bind check) + ``discover_schema.py``
(columns) on the VM, edit below, then dry-run and inspect ``.outputs/ems_documents_*.json``.
Use ``id_columns`` for composite keys and ``property_columns`` for filterable metadata.

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


# The rpt (report) schema. Columns confirmed against the real DB and each view's BIND
# status verified with scripts/probe_views.py. schema="rpt" is pinned per entry.
#
# ⚠️ ConferenceImage: the name-bearing attendee/identity views transitively read
#    ConferenceImage.dbo.Attendee_Picture (the photo table), which is NOT present on the
#    read replica → those views fail to bind (SQL 4413) and are DISABLED below. Enable
#    them once the client grants the replica read access to ConferenceImage. Everything
#    in the "binds today" group works without it.
VIEW_CATALOG: tuple[ViewCatalogEntry, ...] = (
    # ══ Binds today (no ConferenceImage) — ENABLED ═══════════════════════════════
    # Tier 2 — Attendee @ Conference (the registration/attendance record the client
    # named: "check for an EventInstance_Attendee record for that AttendeeID +
    # EventInstanceID"). One doc per (AttendeeID, EventInstanceID); EventInstanceID
    # rides as a custom property for per-conference filtering. No person name in this
    # view (only IDs + company), so its title is company/code — the name-bearing
    # v_Invitation_CurrentStatus below is the richer Tier 2, pending ConferenceImage.
    ViewCatalogEntry(
        view_name="v_EventInstance_Attendee",
        object_type="attendeeConf",
        id_column="RecordID",
        id_columns=("AttendeeID", "EventInstanceID"),
        title_columns=("CompanyName", "AttendeeCode"),
        property_columns=(
            "AttendeeID",
            "EventInstanceID",
            "CompanyName",
            "AttendeeCode",
            "AttendeeCodeType",
        ),
        watermark_column="UpdatedOn",
        schema="rpt",
    ),
    # Tier 3 — per-conference detail. Composite ids keep each fact unique; EventInstanceID
    # rides as a property. v_Catering_TableAssignment carries the person name (FormalName).
    ViewCatalogEntry(
        view_name="v_Catering_TableAssignment",
        object_type="catering",
        id_column="EventInstanceActivityID",
        id_columns=("AttendeeID", "EventInstanceID", "EventInstanceActivityID"),
        title_columns=("FormalName", "Activity"),  # "Jane Doe – Welcome Dinner"
        property_columns=("AttendeeID", "EventInstanceID", "ActivityID"),
        watermark_column=None,
        schema="rpt",
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
    ),
    ViewCatalogEntry(
        view_name="v_TravelAir",
        object_type="travelAir",
        id_column="RecordID",
        id_columns=("AttendeeID", "EventInstanceID", "RecordID"),
        title_columns=("AirlineName", "FlightNumber"),
        property_columns=("AttendeeID", "EventInstanceID", "TravelRecordTypeName", "TravelDate"),
        watermark_column="UpdatedOn",
        schema="rpt",
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
    ),
    # ══ Blocked on ConferenceImage — DISABLED (enable when the replica can read it) ══
    # These carry the person NAME (best for "was <name> at <conference>?") but their
    # definitions transitively read ConferenceImage.dbo.Attendee_Picture, so they do NOT
    # bind here. Verified with scripts/probe_views.py.
    ViewCatalogEntry(
        view_name="v_Attendee_Global",  # Tier 1 — global identity
        object_type="attendee",
        id_column="AttendeeID",
        title_columns=("InformalName", "Company"),  # "Jane Doe – Acme Corp"
        property_columns=("AttendeeID",),
        watermark_column=None,
        schema="rpt",
        enabled=False,  # ← needs ConferenceImage
    ),
    ViewCatalogEntry(
        view_name="v_Invitation_CurrentStatus",  # Tier 2 (richer) — name + conf code + status
        object_type="attendeeStatus",
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
        watermark_column=None,
        schema="rpt",
        enabled=False,  # ← needs ConferenceImage
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
