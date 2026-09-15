"""Build Glean DocumentDefinitions for the `conference` object type.

One document per EventInstanceID, sourced from `rpt.v_EventInstance_PrevNext`.
KPIs (attendee counts, travel breakdown) are computed from DataFrames already
fetched for `conferenceAttendance`, so no extra DB queries are needed.
"""

import logging
from collections.abc import Iterable
from typing import Any

import pandas as pd
from glean.api_client.models.customproperty import CustomProperty
from glean.api_client.models.documentdefinition import DocumentDefinition
from glean.api_client.models.userreferencedefinition import UserReferenceDefinition

from glean_index.types.documents import build_document

logger = logging.getLogger(__name__)

_OBJECT_TYPE = "conference"


# ── Helpers (reuse the same pattern as document_builder) ─────────────────────


def _native(val: Any) -> Any:
    import numpy as np

    if isinstance(val, np.integer):
        return int(val)
    if isinstance(val, np.floating):
        return float(val)
    if isinstance(val, np.bool_):
        return bool(val)
    return val


def _get(row: Any, col: str, default: Any = None) -> Any:
    try:
        val = row[col]
    except (KeyError, IndexError):
        return default
    if val is None:
        return default
    try:
        if pd.isna(val):
            return default
    except (TypeError, ValueError):
        pass
    return _native(val)


def _str(row: Any, col: str) -> str | None:
    val = _get(row, col)
    if val is None:
        return None
    s = str(val).strip()
    return s or None


# ── KPI builders ─────────────────────────────────────────────────────────────


def _attendee_kpis(df: pd.DataFrame) -> dict[str, Any]:
    """Compute per-conference attendee KPIs from v_EventInstance_Attendee rows."""
    if df.empty:
        return {}

    total = df["AttendeeID"].nunique() if "AttendeeID" in df.columns else 0

    def _flag_sum(col: str) -> int:
        if col not in df.columns:
            return 0
        return int(df[col].eq(True).sum())

    kpis: dict[str, Any] = {
        "total_attendees": total,
        "allen_watchlist_count": _flag_sum("IsAllenWatchlist"),
        "first_time_count": _flag_sum("IsFirstTimeAttendee"),
        "lodging_required_count": _flag_sum("IsLodgingRequired"),
        "travel_required_count": _flag_sum("IsTravelRequired"),
    }

    # Top companies by attendee count
    if "CompanyName" in df.columns:
        top = (
            df.dropna(subset=["CompanyName"])
            .groupby("CompanyName")["AttendeeID"]
            .nunique()
            .sort_values(ascending=False)
            .head(10)
        )
        kpis["top_companies"] = [
            {"company": name, "count": int(count)} for name, count in top.items()
        ]

    return kpis


def _travel_kpis(df: pd.DataFrame) -> dict[str, Any]:
    """Compute per-conference travel KPIs from v_Travel rows."""
    if df.empty:
        return {}

    # Drop deleted rows if the column exists
    if "IsDeleted" in df.columns:
        df = df[~df["IsDeleted"].eq(True)]

    direction_col = "TravelRecordTypeName"
    allen_col = "IsAllenPlane"
    date_col = "AirTravelDate"

    arrivals = df[df[direction_col].str.lower().eq("arrival")] if direction_col in df.columns else df

    allen_arrivals = 0
    commercial_arrivals = 0
    if allen_col in arrivals.columns:
        allen_arrivals = int(arrivals[allen_col].eq(1).sum())
        commercial_arrivals = int((~arrivals[allen_col].eq(1)).sum())

    kpis: dict[str, Any] = {
        "allen_plane_arrivals": allen_arrivals,
        "commercial_arrivals": commercial_arrivals,
    }

    if date_col in df.columns:
        arr_dates = arrivals[date_col].dropna()
        if not arr_dates.empty:
            kpis["arrival_date_range"] = {
                "first": str(arr_dates.min())[:10],
                "last": str(arr_dates.max())[:10],
            }
        dep_col_filter = df[direction_col].str.lower().eq("departure") if direction_col in df.columns else None
        if dep_col_filter is not None:
            dep_dates = df.loc[dep_col_filter, date_col].dropna()
            if not dep_dates.empty:
                kpis["departure_date_range"] = {
                    "first": str(dep_dates.min())[:10],
                    "last": str(dep_dates.max())[:10],
                }

    return kpis


# ── Public builder ────────────────────────────────────────────────────────────


def build_conference_documents(
    df_event: pd.DataFrame,
    df_attendee: pd.DataFrame,
    df_travel: pd.DataFrame,
    *,
    datasource: str,
    allowed_users: Iterable[UserReferenceDefinition] | None = None,
    view_url: str = "",
) -> list[DocumentDefinition]:
    """One DocumentDefinition per EventInstanceID from v_EventInstance_PrevNext.

    KPIs are derived from df_attendee and df_travel (already in memory from the
    conferenceAttendance pipeline) — no additional DB queries.

    Returns an empty list if df_event is empty (logs a warning).
    """
    if df_event.empty:
        logger.warning(
            "build_conference_documents: v_EventInstance_PrevNext returned no rows "
            "— conference documents will not be produced."
        )
        return []

    # Pre-index attendee and travel rows by EventInstanceID for O(1) lookup.
    def _group_by_event(df: pd.DataFrame) -> dict[Any, pd.DataFrame]:
        if df.empty or "EventInstanceID" not in df.columns:
            return {}
        return {k: g for k, g in df.groupby("EventInstanceID")}

    attendee_by_event = _group_by_event(df_attendee)
    travel_by_event = _group_by_event(df_travel)

    allowed = list(allowed_users or [])
    documents: list[DocumentDefinition] = []

    for _, row in df_event.iterrows():
        eid = _get(row, "EventInstanceID")
        if eid is None:
            continue
        eid = int(eid)

        is_current = bool(_get(row, "IsCurrentByMaster"))
        short_code = _str(row, "EventInstanceShort") or f"Conference #{eid}"
        full_name = _str(row, "EventInstance") or short_code
        master_name = _str(row, "EventMaster")

        # Title: "[Current] SV26 – Allen & Co Conference 2026"
        title_base = f"{short_code} – {full_name}" if full_name != short_code else short_code
        title = f"[Current] {title_base}" if is_current else title_base

        payload: dict[str, Any] = {
            "event_instance_id": eid,
            "code": short_code,
            "name": full_name,
            "is_current": is_current,
        }
        if master_name:
            payload["event_master"] = master_name

        year = _get(row, "EventYear")
        if year is not None:
            payload["year"] = int(year)

        for date_field in ("EventStartDate", "EndEndDate"):
            val = _str(row, date_field)
            if val:
                payload[date_field.lower()] = val[:10]

        for bag_field in ("BagPullStartDateTime", "BagPullEndDateTime"):
            val = _str(row, bag_field)
            if val:
                payload[bag_field.lower()] = val

        # Prev / Next context
        prev_short = _str(row, "EventInstanceShortPrev")
        next_short = _str(row, "EventInstanceShortNext")
        if prev_short:
            payload["previous_conference"] = prev_short
        if next_short:
            payload["next_conference"] = next_short

        # KPIs
        att_df = attendee_by_event.get(eid, pd.DataFrame())
        trv_df = travel_by_event.get(eid, pd.DataFrame())
        payload["attendee_kpis"] = _attendee_kpis(att_df)
        payload["travel_kpis"] = _travel_kpis(trv_df)

        custom_props = [
            CustomProperty(name="isCurrent", value="true" if is_current else "false"),
        ]
        if year is not None:
            custom_props.append(CustomProperty(name="eventYear", value=str(int(year))))

        documents.append(
            build_document(
                object_type=_OBJECT_TYPE,
                datasource=datasource,
                document_id=f"conference::{eid}",
                title=title,
                view_url=view_url or None,
                body_payload=payload,
                allowed_users=allowed or None,
                custom_properties=custom_props,
            )
        )

    logger.info("build_conference_documents: built %s documents.", len(documents))
    return documents
