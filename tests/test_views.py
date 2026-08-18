"""Tests for the generic EMS row→document builder (skeleton mapping)."""

import json

import pandas as pd

from allenco_connector.views._common import _jsonable, rows_to_documents
from glean_index.index_documents import (
    dedupe_documents_by_id,
    set_anonymous_access_where_missing,
)
from helpers.json_export import _document_summary


def test_builds_one_document_per_row():
    df = pd.DataFrame(
        [
            {"AttendeeID": 1, "FirstName": "Ada", "LastName": "Lovelace"},
            {"AttendeeID": 2, "FirstName": "Alan", "LastName": "Turing"},
        ]
    )
    docs = rows_to_documents(
        df,
        object_type="attendee",
        datasource="allencoems",
        id_column="AttendeeID",
        title_columns=("FirstName", "LastName"),
    )
    assert len(docs) == 2
    assert docs[0].id == "attendee:1"  # id is namespaced by object_type
    assert docs[0].title == "Ada – Lovelace"
    assert docs[0].datasource == "allencoems"


def test_missing_id_column_falls_back_to_position():
    df = pd.DataFrame([{"FirstName": "NoId"}])
    docs = rows_to_documents(
        df,
        object_type="attendee",
        datasource="ds",
        id_column="AttendeeID",
        title_columns=("FirstName",),
    )
    assert docs[0].id == "attendee:0"


def test_document_body_is_json_serialisable_with_coercion():
    df = pd.DataFrame([{"AttendeeID": 1, "When": pd.Timestamp("2025-01-01"), "Score": 3.5}])
    docs = rows_to_documents(
        df,
        object_type="attendee",
        datasource="ds",
        id_column="AttendeeID",
        title_columns=(),
    )
    body = json.loads(docs[0].body.text_content)
    assert body["When"] == "2025-01-01T00:00:00"
    assert body["Score"] == 3.5


def test_jsonable_coerces_timestamp_nan_and_none():
    assert _jsonable(pd.Timestamp("2025-01-02T03:04:05")) == "2025-01-02T03:04:05"
    assert _jsonable(float("nan")) is None
    assert _jsonable(None) is None
    assert _jsonable("plain") == "plain"


def test_set_anonymous_access_where_missing():
    # a document built without allowed_users has no permissions
    docs = rows_to_documents(
        pd.DataFrame([{"AttendeeID": 1}]),
        object_type="attendee",
        datasource="ds",
        id_column="AttendeeID",
        title_columns=(),
    )
    assert docs[0].permissions is None
    updated = set_anonymous_access_where_missing(docs)
    assert updated == 1
    assert docs[0].permissions is not None
    assert docs[0].permissions.allow_anonymous_access is True


def test_view_url_base_stamps_per_row_url():
    df = pd.DataFrame([{"AttendeeID": 7}])
    docs = rows_to_documents(
        df,
        object_type="attendee",
        datasource="ds",
        id_column="AttendeeID",
        title_columns=(),
        view_url_base="https://ems.allenco.com/",
    )
    assert docs[0].view_url == "https://ems.allenco.com/attendee/7"


def test_dedupe_documents_by_id_collapses_duplicates():
    # two rows share AttendeeID=1 → same document id "attendee:1"
    df = pd.DataFrame([{"AttendeeID": 1}, {"AttendeeID": 1}, {"AttendeeID": 2}])
    docs = rows_to_documents(
        df, object_type="attendee", datasource="ds", id_column="AttendeeID", title_columns=()
    )
    deduped, dropped = dedupe_documents_by_id(docs)
    assert dropped == 1
    assert sorted(d.id for d in deduped) == ["attendee:1", "attendee:2"]


def test_id_columns_builds_composite_key_unique_per_row():
    # Two flights for the same attendee: a single AttendeeID key would collide and be
    # deduped away; the composite (AttendeeID, EventInstanceID, FlightNo) stays unique.
    df = pd.DataFrame(
        [
            {"AttendeeID": 1, "EventInstanceID": "SV26", "FlightNo": "AA100"},
            {"AttendeeID": 1, "EventInstanceID": "SV26", "FlightNo": "AA200"},
        ]
    )
    docs = rows_to_documents(
        df,
        object_type="travelAir",
        datasource="ds",
        id_column="AttendeeID",
        id_columns=("AttendeeID", "EventInstanceID", "FlightNo"),
        title_columns=(),
    )
    ids = [d.id for d in docs]
    assert ids == ["travelAir:1:SV26:AA100", "travelAir:1:SV26:AA200"]
    deduped, dropped = dedupe_documents_by_id(docs)
    assert dropped == 0  # composite key prevents the collision


def test_id_columns_skips_null_parts_and_falls_back_to_position():
    df = pd.DataFrame([{"AttendeeID": None, "EventInstanceID": None}])
    docs = rows_to_documents(
        df,
        object_type="attendeeConf",
        datasource="ds",
        id_column="AttendeeID",
        id_columns=("AttendeeID", "EventInstanceID"),
        title_columns=(),
    )
    assert docs[0].id == "attendeeConf:0"  # all key parts null → row position


def test_property_columns_emit_custom_properties_and_stay_in_body():
    df = pd.DataFrame([{"AttendeeID": 1, "EventInstanceID": "SV26", "FirstName": "Ada"}])
    docs = rows_to_documents(
        df,
        object_type="attendeeConf",
        datasource="ds",
        id_column="AttendeeID",
        title_columns=("FirstName",),
        property_columns=("EventInstanceID", "AttendeeID"),
    )
    props = {p.name: p.value for p in docs[0].custom_properties}
    assert props == {"EventInstanceID": "SV26", "AttendeeID": 1}  # filterable metadata
    body = json.loads(docs[0].body.text_content)
    assert body["EventInstanceID"] == "SV26"  # also still in the body


def test_property_columns_skip_missing_and_null():
    df = pd.DataFrame([{"AttendeeID": 1, "EventInstanceID": None}])
    docs = rows_to_documents(
        df,
        object_type="attendeeConf",
        datasource="ds",
        id_column="AttendeeID",
        title_columns=(),
        property_columns=("EventInstanceID", "MissingCol"),
    )
    # null EventInstanceID and absent MissingCol both skipped → no custom properties
    assert docs[0].custom_properties == []


def test_exclude_columns_dropped_from_body_case_insensitive():
    df = pd.DataFrame([{"AttendeeID": 1, "DOB": "1990-01-01", "FirstName": "Ada"}])
    docs = rows_to_documents(
        df,
        object_type="attendee",
        datasource="ds",
        id_column="AttendeeID",
        title_columns=("FirstName",),
        exclude_columns=("dob",),  # exact, case-insensitive
    )
    body = json.loads(docs[0].body.text_content)
    assert "DOB" not in body  # sensitive column redacted
    assert body["FirstName"] == "Ada"
    assert body["AttendeeID"] == 1


def test_exclude_columns_glob_drops_all_license_variants():
    # A wildcard pattern must catch every license column, incl. ones an exact list misses.
    df = pd.DataFrame(
        [
            {
                "AttendeeID": 1,
                "LicenseName": "X",
                "LicenseState": "CA",
                "LicenseCountryName": "US",
                "DietaryAllergyComments": "peanuts",
                "FirstName": "Ada",
            }
        ]
    )
    docs = rows_to_documents(
        df,
        object_type="travelGround",
        datasource="ds",
        id_column="AttendeeID",
        title_columns=(),
        exclude_columns=("License*", "DOB"),
    )
    body = json.loads(docs[0].body.text_content)
    assert "LicenseName" not in body
    assert "LicenseState" not in body
    assert "LicenseCountryName" not in body  # glob catches the variant an exact list would miss
    assert body["DietaryAllergyComments"] == "peanuts"  # dietary/allergy kept (must-have)
    assert body["FirstName"] == "Ada"


def test_document_summary_includes_viewurl_and_custom_properties():
    docs = rows_to_documents(
        pd.DataFrame([{"AttendeeID": 1, "EventInstanceID": "SV26"}]),
        object_type="attendeeConf",
        datasource="ds",
        id_column="AttendeeID",
        id_columns=("AttendeeID", "EventInstanceID"),
        title_columns=(),
        property_columns=("EventInstanceID",),
        view_url_base="https://ems.allenco.com",
    )
    summary = _document_summary(docs[0])
    assert summary["id"] == "attendeeConf:1:SV26"
    assert summary["viewUrl"] == "https://ems.allenco.com/attendeeConf/1:SV26"
    assert summary["customProperties"] == [{"name": "EventInstanceID", "value": "SV26"}]
