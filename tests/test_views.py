"""Tests for the generic EMS row→document builder (skeleton mapping)."""

import json

import pandas as pd

from allenco_connector.views._common import _jsonable, rows_to_documents
from glean_index.index_documents import dedupe_documents_by_id


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


def test_dedupe_documents_by_id_collapses_duplicates():
    # two rows share AttendeeID=1 → same document id "attendee:1"
    df = pd.DataFrame([{"AttendeeID": 1}, {"AttendeeID": 1}, {"AttendeeID": 2}])
    docs = rows_to_documents(
        df, object_type="attendee", datasource="ds", id_column="AttendeeID", title_columns=()
    )
    deduped, dropped = dedupe_documents_by_id(docs)
    assert dropped == 1
    assert sorted(d.id for d in deduped) == ["attendee:1", "attendee:2"]


def test_exclude_columns_dropped_from_body_case_insensitive():
    df = pd.DataFrame([{"AttendeeID": 1, "DOB": "1990-01-01", "FirstName": "Ada"}])
    docs = rows_to_documents(
        df,
        object_type="attendee",
        datasource="ds",
        id_column="AttendeeID",
        title_columns=("FirstName",),
        exclude_columns=("dob",),  # case-insensitive
    )
    body = json.loads(docs[0].body.text_content)
    assert "DOB" not in body  # sensitive column redacted
    assert body["FirstName"] == "Ada"
    assert body["AttendeeID"] == 1
