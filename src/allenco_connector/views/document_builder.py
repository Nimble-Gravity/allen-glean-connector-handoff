"""Build Glean DocumentDefinitions from 5 EMS views.

One document per (AttendeeID, EventInstanceID) — a Conference Attendance Profile
that aggregates registration, catering, activities, and travel into one rich body.
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

_OBJECT_TYPE = "conferenceAttendance"

# v_EventInstance_Attendee booleans → human-readable labels (only True values emitted)
_ATTENDEE_FLAG_MAP: dict[str, str] = {
    "IsLodgingRequired": "Lodging Required",
    "IsTravelRequired": "Travel Required",
    "IsGiftBagRequired": "Gift Bag Required",
    "IsCarRentalRequired": "Car Rental Required",
    "isDepartureLetterNeeded": "Departure Letter Needed",
    "IsSitterAllocated": "Sitter Allocated",
    "HasOwnGolfBag": "Has Own Golf Bag",
    "IsAccompaniedByServiceDog": "Service Dog",
    "IsVaccinated": "Vaccinated",
    "IsCovidPreTest": "Covid Pre-Test",
    "IsWaiverRequired": "Waiver Required",
    "IsWaiverSigned": "Waiver Signed",
    "IsWaiverOnFile": "Waiver On File",
    "IsBackgroundCheckRequired": "Background Check Required",
    "IsBackgroundCheckDone": "Background Check Done",
    "IsAllenWatchlist": "Allen Watchlist",
    "IsReserveCompanion": "Reserve Companion",
    "IsReserveBabysitter": "Reserve Babysitter",
    "IsConfirmedDinnerArrangements": "Dinner Confirmed",
    "IsConfirmedActivityArrangements": "Activity Confirmed",
}


# ── Helpers ───────────────────────────────────────────────────────────────────


def _native(val: Any) -> Any:
    """Convert numpy scalars to Python-native types so json.dumps works."""
    import numpy as np

    if isinstance(val, (np.integer,)):
        return int(val)
    if isinstance(val, (np.floating,)):
        return float(val)
    if isinstance(val, (np.bool_,)):
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


def _join_notes(*parts: str | None) -> str | None:
    joined = "; ".join(p for p in parts if p and str(p).strip())
    return joined or None


# ── Name lookup ───────────────────────────────────────────────────────────────


def _build_name_lookup(df_catering: pd.DataFrame) -> dict[int, str]:
    """Build {AttendeeID: FormalName} scanning all catering rows (cross-event).

    v_EventInstance_Attendee has no person name; catering is the only bindable
    view that carries FormalName. A cross-event lookup ensures attendees who
    attended some conferences without catering records still get their name.
    """
    lookup: dict[int, str] = {}
    if df_catering.empty or "AttendeeID" not in df_catering.columns:
        return lookup
    for _, row in df_catering.iterrows():
        aid = _get(row, "AttendeeID")
        name = _str(row, "FormalName")
        if aid is not None and name and int(aid) not in lookup:
            lookup[int(aid)] = name
    return lookup


# ── Per-section builders ──────────────────────────────────────────────────────


def _build_flags(row: Any) -> list[str]:
    flags = [label for col, label in _ATTENDEE_FLAG_MAP.items() if _get(row, col)]
    # IsFirstTimeAttendee is stored as "***" (non-empty string) when true, not a bool
    if _get(row, "IsFirstTimeAttendee"):
        flags.append("First Time Attendee")
    return flags


def _build_catering(df: pd.DataFrame) -> list[dict[str, Any]]:
    entries = []
    for _, row in df.iterrows():
        entry: dict[str, Any] = {
            "session": _str(row, "EventInstanceActivity"),
            "activity_type": _str(row, "Activity"),
            "table": _get(row, "TableNumber"),
            "seat": _get(row, "SeatNumber"),
            "start": _str(row, "StartDateTime"),
            "end": _str(row, "EndDateTime"),
        }
        # Only include main_guest when the attendee is a companion (not the host)
        main = _str(row, "MainGuestFormalName")
        own = _str(row, "FormalName")
        if main and main != own:
            entry["main_guest"] = main
        entries.append(entry)
    return entries


def _build_activity_schedule(df: pd.DataFrame) -> list[dict[str, Any]]:
    entries = []
    for _, row in df.iterrows():
        start = _str(row, "StartDateTime") or _str(row, "RoleStartDateTime")
        end = _str(row, "EndDateTime") or _str(row, "RoleEndDateTime")
        if start or end:
            entries.append({"start": start, "end": end})
    return entries


def _build_air_travel(df: pd.DataFrame) -> list[dict[str, Any]]:
    legs = []
    for _, row in df.iterrows():
        from_code = _str(row, "ToFromAirportCode")
        from_name = _str(row, "ToFromAirportName")
        from_city = _str(row, "EMS1_OriginatingCity")
        if from_code and from_name:
            from_str: str | None = f"{from_code} {from_name}"
        elif from_city:
            from_str = from_city
        else:
            from_str = None

        to_code = _str(row, "AirportCode")
        to_name = _str(row, "AirportName")
        to_str: str | None = f"{to_code} {to_name}" if to_code and to_name else to_name

        leg: dict[str, Any] = {
            "direction": _str(row, "TravelRecordTypeName"),
            "method": _str(row, "TravelMethodAirName"),
            "date": _str(row, "TravelDate"),
            "time": _str(row, "TravelTime"),
            "from": from_str,
            "to": to_str,
            "airline": _str(row, "AirlineName"),
            "flight": _str(row, "FlightOrTail"),
            "passengers": _get(row, "NumberOfPassengers"),
        }

        notes = _join_notes(_str(row, "RSVPComments"), _str(row, "CoordinatorComments"))
        if notes:
            leg["notes"] = notes

        flags = []
        if _get(row, "IsAllenPlane"):
            flags.append("Allen Plane")
        if _get(row, "IsDepartureLetterNeeded"):
            flags.append("Departure Letter Needed")
        if _get(row, "IsSpouseTravelSeparate"):
            flags.append("Spouse Travels Separately")
        if flags:
            leg["flags"] = flags

        legs.append(leg)
    return legs


def _build_ground_travel(df: pd.DataFrame) -> list[dict[str, Any]]:
    legs = []
    for _, row in df.iterrows():
        date = _str(row, "OverridePickupDate") or _str(row, "TravelDate")
        time_ = _str(row, "OverridePickupTime") or _str(row, "TravelTime")

        leg: dict[str, Any] = {
            "direction": _str(row, "TravelRecordTypeName"),
            "method": _str(row, "TravelMethodGroundName"),
            "car_service": _str(row, "CarServiceTypeName"),
            "date": date,
            "time": time_,
            "pickup": _str(row, "PickUpLocationName"),
            "dropoff": _str(row, "DropOffLocationName"),
            "passengers": _get(row, "NumberOfPassengers"),
            "bags": _get(row, "NumberOfBags"),
        }

        rideshare = _str(row, "DriveShareInfo")
        if rideshare:
            leg["rideshare"] = rideshare

        comments = _join_notes(
            _str(row, "Comments"),
            _str(row, "RSVPComments"),
            _str(row, "CoordinatorComments"),
        )
        if comments:
            leg["comments"] = comments

        child_seats: dict[str, int] = {}
        for seat_col, key in [
            ("CarSeats", "car"),
            ("InfantSeats", "infant"),
            ("ToddlerSeats", "toddler"),
            ("BoosterSeats", "booster"),
        ]:
            val = _get(row, seat_col)
            if val is not None and int(val) > 0:
                child_seats[key] = int(val)
        if child_seats:
            leg["child_seats"] = child_seats

        flags = []
        if _get(row, "IsBagPullNeeded"):
            flags.append("Bag Pull Needed")
        if _get(row, "IsBagPull"):
            flags.append("Bag Pull Done")
        if _get(row, "IsDriverPickup"):
            flags.append("Driver Pickup")
        if _get(row, "IsDriveShare"):
            flags.append("Rideshare")
        if flags:
            leg["flags"] = flags

        legs.append(leg)
    return legs


def _build_payload(
    reg_row: Any,
    name: str,
    catering_df: pd.DataFrame,
    activities_df: pd.DataFrame,
    air_df: pd.DataFrame,
    ground_df: pd.DataFrame,
) -> dict[str, Any]:
    company = _str(reg_row, "CompanyName") or _str(reg_row, "PreferredCompany") or ""
    title = _str(reg_row, "Title") or ""
    preferred_title = _str(reg_row, "PreferredTitle")
    if preferred_title == title:
        preferred_title = None

    attendee_code = _str(reg_row, "AttendeeCode") or ""
    attendee_sub = _str(reg_row, "AttendeeCodeTypeSub") or ""
    attendee_type = f"{attendee_code} – {attendee_sub}".strip(" –")

    age = _get(reg_row, "AgeAtConf")
    event_cost = _get(reg_row, "EventCost")

    comments: dict[str, str] = {
        k: v
        for k, v in {
            "rsvp": _str(reg_row, "RSVPComments"),
            "dietary": _str(reg_row, "RSVPDietaryAllergyComments"),
            "activities": _str(reg_row, "RSVPActivityComments"),
        }.items()
        if v
    }

    payload: dict[str, Any] = {
        "attendee_id": int(_get(reg_row, "AttendeeID")),
        "event_instance_id": int(_get(reg_row, "EventInstanceID")),
        "name": name,
        "company": company,
        "title": title,
        "attendee_type": attendee_type,
        "is_first_time": bool(_get(reg_row, "IsFirstTimeAttendee")),
        "is_allen_watchlist": bool(_get(reg_row, "IsAllenWatchlist")),
        "party_size": _get(reg_row, "RSVPNumberInParty"),
        "flags": _build_flags(reg_row),
        "catering": _build_catering(catering_df),
        "activity_schedule": _build_activity_schedule(activities_df),
        "air_travel": _build_air_travel(air_df),
        "ground_travel": _build_ground_travel(ground_df),
    }

    if preferred_title:
        payload["preferred_title"] = preferred_title
    if _str(reg_row, "CompanyCategory"):
        payload["company_category"] = _str(reg_row, "CompanyCategory")
    if age is not None:
        payload["age_at_conference"] = int(age)
    if event_cost:
        payload["event_cost"] = float(event_cost)
    if comments:
        payload["comments"] = comments

    return payload


# ── Public builder ────────────────────────────────────────────────────────────


def build_conference_attendance_documents(
    df_attendee: pd.DataFrame,
    df_catering: pd.DataFrame,
    df_activities: pd.DataFrame,
    df_air: pd.DataFrame,
    df_ground: pd.DataFrame,
    *,
    datasource: str,
    allowed_users: Iterable[UserReferenceDefinition] | None = None,
    view_url: str = "",
) -> list[DocumentDefinition]:
    """One DocumentDefinition per (AttendeeID, EventInstanceID).

    Aggregates all 5 EMS views. Deleted/inactive attendee rows are skipped.
    Person names are resolved from catering across all events (cross-event lookup).
    """
    if df_attendee.empty:
        logger.warning("build_conference_attendance_documents: no attendee rows.")
        return []

    # Drop deleted/inactive registration records
    for col in ("IsDeleted", "IsInactive"):
        if col in df_attendee.columns:
            df_attendee = df_attendee[~df_attendee[col].eq(True)]

    name_lookup = _build_name_lookup(df_catering)

    # Pre-index secondary views by (AttendeeID, EventInstanceID) for O(1) lookup
    def _index(df: pd.DataFrame) -> dict[tuple, pd.DataFrame]:
        if df.empty or "AttendeeID" not in df.columns or "EventInstanceID" not in df.columns:
            return {}
        return {k: g for k, g in df.groupby(["AttendeeID", "EventInstanceID"])}

    catering_idx = _index(df_catering)
    activities_idx = _index(df_activities)
    air_idx = _index(df_air)
    ground_idx = _index(df_ground)

    allowed = list(allowed_users or [])
    documents: list[DocumentDefinition] = []

    for (attendee_id, event_id), group in df_attendee.groupby(
        ["AttendeeID", "EventInstanceID"]
    ):
        reg_row = group.iloc[0]
        key = (attendee_id, event_id)

        name = name_lookup.get(int(attendee_id), f"Attendee #{attendee_id}")
        doc_title = f"{name} – Conference #{event_id}"

        payload = _build_payload(
            reg_row,
            name,
            catering_idx.get(key, pd.DataFrame()),
            activities_idx.get(key, pd.DataFrame()),
            air_idx.get(key, pd.DataFrame()),
            ground_idx.get(key, pd.DataFrame()),
        )

        company = payload.get("company", "")
        attendee_code = payload.get("attendee_type", "").split(" –")[0].strip()

        custom_props = [
            CustomProperty(name="attendeeName", value=name),
            CustomProperty(name="eventInstanceId", value=str(event_id)),
        ]
        if company:
            custom_props.append(CustomProperty(name="company", value=company))
        if attendee_code:
            custom_props.append(CustomProperty(name="attendeeCode", value=attendee_code))

        documents.append(
            build_document(
                object_type=_OBJECT_TYPE,
                datasource=datasource,
                document_id=f"{attendee_id}::{event_id}",
                title=doc_title,
                view_url=view_url or None,
                body_payload=payload,
                allowed_users=allowed or None,
                custom_properties=custom_props,
            )
        )

    logger.info(
        "build_conference_attendance_documents: built %s documents.", len(documents)
    )
    return documents
