"""Tests for the Conference Attendance Profile document builder."""

import json

import pandas as pd

from allenco_connector.views.document_builder import (
    _build_flags,
    _build_name_lookup,
    build_conference_attendance_documents,
)
from glean_index.index_documents import dedupe_documents_by_id, set_anonymous_access_where_missing

# ── Fixtures ──────────────────────────────────────────────────────────────────


def _attendee_row(**kwargs) -> dict:
    defaults = {
        "AttendeeID": 1,
        "EventInstanceID": 10,
        "Display": 1,
        "Title": "Managing Partner",
        "CompanyName": "Acme Capital",
        "CompanyCategory": "Hedge Fund",
        "AttendeeCode": "Institutional",
        "AttendeeCodeType": "Adult",
        "AttendeeCodeTypeSub": "Main Guest",
        "AgeAtConf": 40,
        "IsFirstTimeAttendee": "",
        "IsAllenWatchlist": False,
        "IsDeleted": False,
        "IsInactive": False,
        "EventCost": 0.0,
        "RSVPNumberInParty": 1,
        "RSVPComments": "",
        "RSVPDietaryAllergyComments": "",
        "RSVPActivityComments": "",
        "PreferredCompany": "Acme Capital",
        "PreferredTitle": "Managing Partner",
        # flags all off by default
        "IsLodgingRequired": False,
        "IsTravelRequired": False,
        "IsGiftBagRequired": False,
        "IsCarRentalRequired": None,
        "isDepartureLetterNeeded": False,
        "IsSitterAllocated": False,
        "HasOwnGolfBag": False,
        "IsAccompaniedByServiceDog": None,
        "IsVaccinated": False,
        "IsCovidPreTest": None,
        "IsWaiverRequired": False,
        "IsWaiverSigned": None,
        "IsWaiverOnFile": False,
        "IsBackgroundCheckRequired": None,
        "IsBackgroundCheckDone": None,
        "IsReserveCompanion": False,
        "IsReserveBabysitter": False,
        "IsConfirmedDinnerArrangements": False,
        "IsConfirmedActivityArrangements": None,
    }
    defaults.update(kwargs)
    return defaults


def _catering_row(**kwargs) -> dict:
    defaults = {
        "AttendeeID": 1,
        "EventInstanceID": 10,
        "FormalName": "Doe, Jane",
        "InformalName": "Jane Doe",
        "MainGuestFormalName": "Doe, Jane",
        "MainGuestInformalName": "Jane Doe",
        "Activity": "Welcome Dinner",
        "EventInstanceActivity": "Monday Welcome Dinner",
        "EventInstanceActivityShort": "Welcome Dinner",
        "TableNumber": 3,
        "SeatNumber": 5,
        "StartDateTime": "2024-07-01T19:00:00",
        "EndDateTime": "2024-07-01T21:00:00",
        "AttendeeCode": "Institutional",
        "AttendeeCodeType": "Adult",
        "AttendeeCodeTypeSub": "Main Guest",
        "Company": "Acme Capital",
    }
    defaults.update(kwargs)
    return defaults


# ── Name lookup ───────────────────────────────────────────────────────────────


def test_name_lookup_built_from_catering():
    df = pd.DataFrame([
        _catering_row(AttendeeID=1, FormalName="Ainslie, Lee"),
        _catering_row(AttendeeID=2, FormalName="Smith, John"),
    ])
    lookup = _build_name_lookup(df)
    assert lookup == {1: "Ainslie, Lee", 2: "Smith, John"}


def test_name_lookup_uses_first_non_empty():
    df = pd.DataFrame([
        _catering_row(AttendeeID=1, EventInstanceID=10, FormalName="Doe, Jane"),
        _catering_row(AttendeeID=1, EventInstanceID=20, FormalName="Doe, Janet"),  # first wins
    ])
    lookup = _build_name_lookup(df)
    assert lookup[1] == "Doe, Jane"


def test_name_lookup_skips_empty_names():
    df = pd.DataFrame([_catering_row(AttendeeID=1, FormalName="")])
    lookup = _build_name_lookup(df)
    assert 1 not in lookup


def test_name_lookup_empty_df():
    assert _build_name_lookup(pd.DataFrame()) == {}


# ── Flag consolidation ────────────────────────────────────────────────────────


def test_flags_only_true_values():
    row = pd.Series({
        "IsLodgingRequired": True,
        "IsTravelRequired": False,
        "IsVaccinated": True,
        "IsFirstTimeAttendee": "",
    })
    flags = _build_flags(row)
    assert "Lodging Required" in flags
    assert "Vaccinated" in flags
    assert "Travel Required" not in flags


def test_first_time_flag_from_string_marker():
    row = pd.Series({"IsFirstTimeAttendee": "***"})
    assert "First Time Attendee" in _build_flags(row)


def test_flags_null_treated_as_false():
    row = pd.Series({"IsCarRentalRequired": None, "IsFirstTimeAttendee": None})
    flags = _build_flags(row)
    assert "Car Rental Required" not in flags
    assert "First Time Attendee" not in flags


# ── Document builder ──────────────────────────────────────────────────────────


def test_one_doc_per_attendee():
    # (1,10), (1,20), (2,10) → 2 docs: one per unique AttendeeID
    df_att = pd.DataFrame([
        _attendee_row(AttendeeID=1, EventInstanceID=10),
        _attendee_row(AttendeeID=1, EventInstanceID=20),
        _attendee_row(AttendeeID=2, EventInstanceID=10),
    ])
    docs = build_conference_attendance_documents(
        df_att,
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        datasource="ds",
    )
    assert len(docs) == 2
    ids = {d.id for d in docs}
    assert ids == {"attendee::1", "attendee::2"}
    doc1 = next(d for d in docs if d.id == "attendee::1")
    body = json.loads(doc1.body.text_content)
    assert len(body["events"]) == 2


def test_name_in_title_from_catering():
    df_att = pd.DataFrame([_attendee_row(AttendeeID=1, EventInstanceID=10)])
    df_cat = pd.DataFrame([_catering_row(AttendeeID=1, FormalName="Ainslie, Lee")])
    docs = build_conference_attendance_documents(
        df_att, df_cat, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), datasource="ds"
    )
    assert docs[0].title == "Ainslie, Lee"


def test_fallback_title_when_no_catering():
    df_att = pd.DataFrame([_attendee_row(AttendeeID=99, EventInstanceID=5)])
    docs = build_conference_attendance_documents(
        df_att,
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        datasource="ds",
    )
    assert docs[0].title == "Attendee #99"


def test_cross_event_name_lookup():
    # AttendeeID=1 has catering only for event 20; name resolves cross-event → 1 doc with 2 events
    df_att = pd.DataFrame([
        _attendee_row(AttendeeID=1, EventInstanceID=10),
        _attendee_row(AttendeeID=1, EventInstanceID=20),
    ])
    df_cat = pd.DataFrame([
        _catering_row(AttendeeID=1, EventInstanceID=20, FormalName="Lee, Ainslie"),
    ])
    docs = build_conference_attendance_documents(
        df_att, df_cat, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), datasource="ds"
    )
    assert len(docs) == 1
    assert docs[0].title == "Lee, Ainslie"
    body = json.loads(docs[0].body.text_content)
    assert len(body["events"]) == 2


def test_deleted_rows_skipped():
    df_att = pd.DataFrame([
        _attendee_row(AttendeeID=1, EventInstanceID=10, IsDeleted=True),
        _attendee_row(AttendeeID=2, EventInstanceID=10, IsDeleted=False),
    ])
    docs = build_conference_attendance_documents(
        df_att,
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        datasource="ds",
    )
    assert len(docs) == 1
    assert docs[0].id == "attendee::2"


def test_inactive_rows_skipped():
    df_att = pd.DataFrame([
        _attendee_row(AttendeeID=1, EventInstanceID=10, IsInactive=True),
    ])
    docs = build_conference_attendance_documents(
        df_att,
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        datasource="ds",
    )
    assert docs == []


def test_body_has_no_raw_boolean_keys():
    df_att = pd.DataFrame([_attendee_row(AttendeeID=1, EventInstanceID=10, IsTravelRequired=True)])
    docs = build_conference_attendance_documents(
        df_att,
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        datasource="ds",
    )
    body = json.loads(docs[0].body.text_content)
    event = body["events"][0]
    # None of the raw boolean column names should appear in the event entry
    assert "IsTravelRequired" not in event
    assert "IsLodgingRequired" not in event
    assert "isDepartureLetterNeeded" not in event
    # But the flags list should be present
    assert "flags" in event
    assert "Travel Required" in event["flags"]


def test_body_contains_catering_section():
    df_att = pd.DataFrame([_attendee_row(AttendeeID=1, EventInstanceID=10)])
    df_cat = pd.DataFrame([
        _catering_row(AttendeeID=1, EventInstanceID=10, TableNumber=7, SeatNumber=2),
    ])
    docs = build_conference_attendance_documents(
        df_att, df_cat, pd.DataFrame(), pd.DataFrame(), pd.DataFrame(), datasource="ds"
    )
    body = json.loads(docs[0].body.text_content)
    assert len(body["events"][0]["catering"]) == 1
    assert body["events"][0]["catering"][0]["table"] == 7
    assert body["events"][0]["catering"][0]["seat"] == 2


def test_body_catering_empty_list_when_no_rows():
    df_att = pd.DataFrame([_attendee_row(AttendeeID=1, EventInstanceID=10)])
    docs = build_conference_attendance_documents(
        df_att,
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        datasource="ds",
    )
    body = json.loads(docs[0].body.text_content)
    assert body["events"][0]["catering"] == []


def test_custom_properties():
    df_att = pd.DataFrame([_attendee_row(AttendeeID=5, EventInstanceID=12)])
    df_cat = pd.DataFrame([_catering_row(AttendeeID=5, EventInstanceID=12, FormalName="Ainslie, Lee")])
    docs = build_conference_attendance_documents(
        df_att,
        df_cat,
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        datasource="ds",
    )
    props = {p.name: p.value for p in docs[0].custom_properties}
    assert props["attendeeName"] == "Ainslie, Lee"
    assert "eventInstanceId" not in props


def test_object_type_is_conference_attendance():
    df_att = pd.DataFrame([_attendee_row()])
    docs = build_conference_attendance_documents(
        df_att,
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        datasource="ds",
    )
    assert docs[0].object_type == "conferenceAttendance"


def test_empty_attendee_df_returns_no_docs():
    docs = build_conference_attendance_documents(
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        datasource="ds",
    )
    assert docs == []


def test_no_duplicate_ids():
    df_att = pd.DataFrame([
        _attendee_row(AttendeeID=1, EventInstanceID=10),
        _attendee_row(AttendeeID=1, EventInstanceID=10),  # duplicate input row
        _attendee_row(AttendeeID=2, EventInstanceID=10),
    ])
    docs = build_conference_attendance_documents(
        df_att,
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        datasource="ds",
    )
    assert len(docs) == 2
    ids = {d.id for d in docs}
    assert ids == {"attendee::1", "attendee::2"}
    _, dropped = dedupe_documents_by_id(docs)
    assert dropped == 0


def test_set_anonymous_access_when_no_allowed_users():
    df_att = pd.DataFrame([_attendee_row()])
    docs = build_conference_attendance_documents(
        df_att,
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        datasource="ds",
    )
    assert docs[0].permissions is None
    updated = set_anonymous_access_where_missing(docs)
    assert updated == 1
    assert docs[0].permissions.allow_anonymous_access is True


def test_view_url_stamped_on_document():
    df_att = pd.DataFrame([_attendee_row()])
    docs = build_conference_attendance_documents(
        df_att,
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        pd.DataFrame(),
        datasource="ds",
        view_url="http://ems3/#/home",
    )
    assert docs[0].view_url == "http://ems3/#/home"
