"""Tests for build_conference_documents."""

import pandas as pd
import pytest

from allenco_connector.views.conference_builder import build_conference_documents

_DS = "allenco-ems"


def _event_row(**kwargs) -> dict:
    defaults = {
        "EventInstanceID": 100,
        "EventInstanceShort": "SV26",
        "EventInstance": "Allen & Co Conference 2026",
        "EventMaster": "Allen & Co",
        "EventYear": 2026,
        "EventStartDate": "2026-07-07 00:00:00",
        "EndEndDate": "2026-07-11 00:00:00",
        "BagPullStartDateTime": None,
        "BagPullEndDateTime": None,
        "IsCurrentByMaster": 1,
        "EventInstanceShortPrev": "SV25",
        "EventInstanceShortNext": None,
    }
    defaults.update(kwargs)
    return defaults


def _attendee_rows(event_id: int, n: int = 3) -> list[dict]:
    return [
        {
            "AttendeeID": i,
            "EventInstanceID": event_id,
            "CompanyName": "Acme" if i % 2 == 0 else "Beta Corp",
            "IsAllenWatchlist": i == 1,
            "IsFirstTimeAttendee": i == 2,
            "IsLodgingRequired": True,
            "IsTravelRequired": True,
        }
        for i in range(1, n + 1)
    ]


def _travel_rows(event_id: int) -> list[dict]:
    return [
        {
            "EventInstanceID": event_id,
            "TravelRecordTypeName": "Arrival",
            "IsAllenPlane": 1,
            "AirTravelDate": "2026-07-07",
            "IsDeleted": False,
        },
        {
            "EventInstanceID": event_id,
            "TravelRecordTypeName": "Arrival",
            "IsAllenPlane": 0,
            "AirTravelDate": "2026-07-06",
            "IsDeleted": False,
        },
        {
            "EventInstanceID": event_id,
            "TravelRecordTypeName": "Departure",
            "IsAllenPlane": 0,
            "AirTravelDate": "2026-07-11",
            "IsDeleted": False,
        },
    ]


# ── Basic contract ─────────────────────────────────────────────────────────────


def test_empty_event_df_returns_empty_list():
    docs = build_conference_documents(
        df_event=pd.DataFrame(),
        df_attendee=pd.DataFrame(_attendee_rows(100)),
        df_travel=pd.DataFrame(_travel_rows(100)),
        datasource=_DS,
    )
    assert docs == []


def test_document_id_pattern():
    df_event = pd.DataFrame([_event_row(EventInstanceID=42)])
    docs = build_conference_documents(
        df_event=df_event,
        df_attendee=pd.DataFrame(),
        df_travel=pd.DataFrame(),
        datasource=_DS,
    )
    assert len(docs) == 1
    assert docs[0].id == "conference::42"


def test_object_type():
    df_event = pd.DataFrame([_event_row()])
    (doc,) = build_conference_documents(
        df_event=df_event, df_attendee=pd.DataFrame(), df_travel=pd.DataFrame(), datasource=_DS
    )
    assert doc.object_type == "conference"


# ── Title formatting ───────────────────────────────────────────────────────────


def test_current_conference_title_has_prefix():
    df_event = pd.DataFrame([_event_row(IsCurrentByMaster=1)])
    (doc,) = build_conference_documents(
        df_event=df_event, df_attendee=pd.DataFrame(), df_travel=pd.DataFrame(), datasource=_DS
    )
    assert doc.title.startswith("[Current]")
    assert "SV26" in doc.title


def test_non_current_conference_no_prefix():
    df_event = pd.DataFrame([_event_row(IsCurrentByMaster=0)])
    (doc,) = build_conference_documents(
        df_event=df_event, df_attendee=pd.DataFrame(), df_travel=pd.DataFrame(), datasource=_DS
    )
    assert not doc.title.startswith("[Current]")
    assert "SV26" in doc.title


# ── Custom properties ──────────────────────────────────────────────────────────


def test_is_current_custom_property_true():
    df_event = pd.DataFrame([_event_row(IsCurrentByMaster=1)])
    (doc,) = build_conference_documents(
        df_event=df_event, df_attendee=pd.DataFrame(), df_travel=pd.DataFrame(), datasource=_DS
    )
    props = {p.name: p.value for p in (doc.custom_properties or [])}
    assert props.get("isCurrent") == "true"


def test_is_current_custom_property_false():
    df_event = pd.DataFrame([_event_row(IsCurrentByMaster=0)])
    (doc,) = build_conference_documents(
        df_event=df_event, df_attendee=pd.DataFrame(), df_travel=pd.DataFrame(), datasource=_DS
    )
    props = {p.name: p.value for p in (doc.custom_properties or [])}
    assert props.get("isCurrent") == "false"


def test_event_year_custom_property():
    df_event = pd.DataFrame([_event_row(EventYear=2026)])
    (doc,) = build_conference_documents(
        df_event=df_event, df_attendee=pd.DataFrame(), df_travel=pd.DataFrame(), datasource=_DS
    )
    props = {p.name: p.value for p in (doc.custom_properties or [])}
    assert props.get("eventYear") == "2026"


# ── KPIs ──────────────────────────────────────────────────────────────────────


def test_attendee_kpis_total():
    df_event = pd.DataFrame([_event_row(EventInstanceID=100)])
    df_att = pd.DataFrame(_attendee_rows(100, n=3))
    (doc,) = build_conference_documents(
        df_event=df_event, df_attendee=df_att, df_travel=pd.DataFrame(), datasource=_DS
    )
    import json

    body = json.loads(doc.body.text_content)
    assert body["attendee_kpis"]["total_attendees"] == 3


def test_attendee_kpis_watchlist_and_first_time():
    df_event = pd.DataFrame([_event_row(EventInstanceID=100)])
    df_att = pd.DataFrame(_attendee_rows(100, n=3))
    (doc,) = build_conference_documents(
        df_event=df_event, df_attendee=df_att, df_travel=pd.DataFrame(), datasource=_DS
    )
    import json

    body = json.loads(doc.body.text_content)
    kpis = body["attendee_kpis"]
    assert kpis["allen_watchlist_count"] == 1
    assert kpis["first_time_count"] == 1


def test_travel_kpis_allen_plane():
    df_event = pd.DataFrame([_event_row(EventInstanceID=100)])
    df_trv = pd.DataFrame(_travel_rows(100))
    (doc,) = build_conference_documents(
        df_event=df_event, df_attendee=pd.DataFrame(), df_travel=df_trv, datasource=_DS
    )
    import json

    body = json.loads(doc.body.text_content)
    kpis = body["travel_kpis"]
    assert kpis["allen_plane_arrivals"] == 1
    assert kpis["commercial_arrivals"] == 1


def test_travel_kpis_arrival_date_range():
    df_event = pd.DataFrame([_event_row(EventInstanceID=100)])
    df_trv = pd.DataFrame(_travel_rows(100))
    (doc,) = build_conference_documents(
        df_event=df_event, df_attendee=pd.DataFrame(), df_travel=df_trv, datasource=_DS
    )
    import json

    body = json.loads(doc.body.text_content)
    arr_range = body["travel_kpis"]["arrival_date_range"]
    assert arr_range["first"] == "2026-07-06"
    assert arr_range["last"] == "2026-07-07"


def test_kpis_empty_when_no_matching_rows():
    """KPIs for a conference with no attendees or travel rows are empty dicts."""
    df_event = pd.DataFrame([_event_row(EventInstanceID=999)])
    df_att = pd.DataFrame(_attendee_rows(100))  # different event
    df_trv = pd.DataFrame(_travel_rows(100))    # different event
    (doc,) = build_conference_documents(
        df_event=df_event, df_attendee=df_att, df_travel=df_trv, datasource=_DS
    )
    import json

    body = json.loads(doc.body.text_content)
    assert body["attendee_kpis"] == {}
    assert body["travel_kpis"] == {}


# ── Multiple conferences ───────────────────────────────────────────────────────


def test_produces_one_doc_per_event_instance():
    rows = [
        _event_row(EventInstanceID=1, IsCurrentByMaster=0, EventInstanceShort="SV24"),
        _event_row(EventInstanceID=2, IsCurrentByMaster=1, EventInstanceShort="SV26"),
    ]
    df_event = pd.DataFrame(rows)
    docs = build_conference_documents(
        df_event=df_event, df_attendee=pd.DataFrame(), df_travel=pd.DataFrame(), datasource=_DS
    )
    assert len(docs) == 2
    ids = {d.id for d in docs}
    assert ids == {"conference::1", "conference::2"}
