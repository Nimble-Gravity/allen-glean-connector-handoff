"""Declarative catalog of the EMS report views the indexer fetches.

This is the single place to list the in-scope views ("connectivity is
configuration, not code"). ``registry.build_view_specs`` turns each enabled
entry into a runnable ViewSpec that fetches the view as a DataFrame.
Document building is handled by ``document_builder.build_conference_attendance_documents``,
which aggregates all views into one document per (AttendeeID, EventInstanceID).

**Source = the `rpt` (report) schema** of the Allen & Co ``Conference`` database —
the client's recommended, report-optimized (already-joined) views, confirmed via
``scripts/discover_schema.py``. Each entry pins ``schema="rpt"`` so it works
regardless of ``DB_SCHEMA``.

**Enabled (bind today, no ConferenceImage):**
  - Tier 2 — ``v_EventInstance_Attendee``: registration / attendance record.
    ``UpdatedOn`` is the watermark column (available for incremental sync once
    multi-view watermarking is implemented).
  - Tier 3 — detail: ``v_Catering_TableAssignment`` (carries FormalName),
    ``v_Activity_Attendee_TimeRange``, ``v_TravelAir``, ``v_TravelGround``.

**Disabled (blocked on ConferenceImage — the name-bearing views):**
  - ``v_Attendee_Global`` and ``v_Invitation_CurrentStatus`` transitively read
    ``ConferenceImage.dbo.Attendee_Picture``, which is not present on the
    replica → SQL 4413. Enable once the client grants read access to ConferenceImage.
    Verified with ``scripts/probe_views.py``.

To refine/extend: run ``scripts/probe_views.py`` (bind check) + ``discover_schema.py``
(columns) on the VM, edit below, then dry-run and inspect ``.outputs/ems_documents_*.json``.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ViewCatalogEntry:
    """One EMS view to fetch.

    view_name:        the SQL view name (without schema brackets).
    watermark_column: change-tracking column for incremental sync, or None to
                      always full-fetch this view.
    schema:           SQL schema; None inherits the run's DB_SCHEMA default.
    enabled:          False → skipped by build_view_specs (not fetched/indexed).
    """

    view_name: str
    watermark_column: str | None = None
    schema: str | None = None
    enabled: bool = True


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
    # Tier 2 — registration record. UpdatedOn is available for future incremental sync.
    ViewCatalogEntry(
        view_name="v_EventInstance_Attendee",
        watermark_column="UpdatedOn",
        schema="rpt",
    ),
    # Tier 3 — per-conference detail. v_Catering_TableAssignment carries FormalName
    # (the only bindable view with a person name).
    ViewCatalogEntry(
        view_name="v_Catering_TableAssignment",
        watermark_column=None,
        schema="rpt",
    ),
    ViewCatalogEntry(
        view_name="v_Activity_Attendee_TimeRange",
        watermark_column=None,
        schema="rpt",
    ),
    ViewCatalogEntry(
        view_name="v_TravelAir",
        watermark_column="UpdatedOn",
        schema="rpt",
    ),
    ViewCatalogEntry(
        view_name="v_TravelGround",
        watermark_column="UpdatedOn",
        schema="rpt",
    ),
    # ══ Blocked on ConferenceImage — DISABLED (enable when the replica can read it) ══
    # These carry the person NAME but their definitions transitively read
    # ConferenceImage.dbo.Attendee_Picture → SQL 4413 bind error on the replica.
    ViewCatalogEntry(
        view_name="v_Attendee_Global",
        schema="rpt",
        enabled=False,
    ),
    ViewCatalogEntry(
        view_name="v_Invitation_CurrentStatus",
        schema="rpt",
        enabled=False,
    ),
)
