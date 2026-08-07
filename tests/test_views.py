"""Tests for the generic EMS row→document builder (skeleton mapping)."""

import json

import pandas as pd

from allenco_connector.views._common import _jsonable, rows_to_documents


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
        datasource="allenco_ems",
        id_column="AttendeeID",
        title_columns=("FirstName", "LastName"),
    )
    assert len(docs) == 2
    assert docs[0].id == "attendee:1"  # id is namespaced by object_type
    assert docs[0].title == "Ada – Lovelace"
    assert docs[0].datasource == "allenco_ems"


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
