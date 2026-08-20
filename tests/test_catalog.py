"""Tests for the declarative view catalog and the catalog-driven registry."""

import json

import pandas as pd

from allenco_connector.views import registry as reg
from allenco_connector.views.catalog import VIEW_CATALOG, ViewCatalogEntry, builder_for
from allenco_connector.views.registry import build_view_specs


def test_default_schema_inherited_when_entry_unset():
    entry = ViewCatalogEntry(view_name="v_X", object_type="x", id_column="XID")  # schema=None
    (spec,) = build_view_specs([entry], default_schema="Conference")
    assert spec.schema == "Conference"


def test_real_catalog_pins_rpt_schema_and_layered_model():
    # every entry pins schema="rpt", so DB_SCHEMA is moot.
    assert all(e.schema == "rpt" for e in VIEW_CATALOG)
    specs = build_view_specs(VIEW_CATALOG, default_schema="dbo")
    enabled = [e for e in VIEW_CATALOG if e.enabled]
    assert len(specs) == len(enabled)
    assert all(s.schema == "rpt" for s in specs)

    by_type = {e.object_type: e for e in VIEW_CATALOG}
    enabled_types = {e.object_type for e in enabled}
    # The enabled set is the "binds today" group (no ConferenceImage dependency).
    assert enabled_types == {
        "attendeeConf",
        "catering",
        "activityAttendee",
        "travelAir",
        "travelGround",
    }
    # The name-bearing views transitively read ConferenceImage → shipped DISABLED until
    # the client grants replica read access to that database.
    assert not by_type["attendee"].enabled
    assert not by_type["attendeeStatus"].enabled

    # Tier 2 (attendeeConf) is keyed by the composite (AttendeeID, EventInstanceID) and
    # carries EventInstanceID as a filterable custom property (per-conference scoping).
    t2 = by_type["attendeeConf"]
    assert t2.view_name == "v_EventInstance_Attendee"
    assert t2.id_columns == ("AttendeeID", "EventInstanceID")
    assert "EventInstanceID" in t2.property_columns
    # every enabled conference-scoped view carries EventInstanceID as a property
    assert all("EventInstanceID" in e.property_columns for e in enabled)


def test_build_view_specs_skips_disabled_entries():
    on = ViewCatalogEntry(view_name="v_on", object_type="on", id_column="ID")
    off = ViewCatalogEntry(view_name="v_off", object_type="off", id_column="ID", enabled=False)
    specs = build_view_specs([on, off], default_schema="cnf")
    assert [s.view_name for s in specs] == ["v_on"]


def test_entry_schema_overrides_default():
    entry = ViewCatalogEntry(view_name="v_X", object_type="x", id_column="XID", schema="dbo")
    (spec,) = build_view_specs([entry], default_schema="Conference")
    assert spec.schema == "dbo"


def test_generic_builder_maps_rows():
    entry = ViewCatalogEntry(
        view_name="v_Company",
        object_type="company",
        id_column="CompanyID",
        title_columns=("CompanyName",),
    )
    build = builder_for(entry)
    df = pd.DataFrame([{"CompanyID": 7, "CompanyName": "Acme"}])
    docs = build(df, datasource="allencoems")
    assert len(docs) == 1
    assert docs[0].id == "company:7"  # id namespaced by object_type
    assert docs[0].title == "Acme"


def test_custom_build_overrides_generic():
    sentinel = ["custom"]
    entry = ViewCatalogEntry(
        view_name="v_X",
        object_type="x",
        id_column="XID",
        build=lambda df, *, datasource, allowed_users=None: sentinel,
    )
    (spec,) = build_view_specs([entry], default_schema="dbo")
    assert spec.build(pd.DataFrame(), datasource="ds") is sentinel


def test_fetch_uses_schema_qualified_name(monkeypatch):
    cap = {}

    def _fake(sql, conn, params=None):
        cap["sql"] = sql
        return pd.DataFrame({"CompanyID": [1]})

    monkeypatch.setattr(pd, "read_sql", _fake)
    entry = ViewCatalogEntry(
        view_name="v_Company", object_type="company", id_column="CompanyID", schema="Conference"
    )
    (spec,) = build_view_specs([entry], default_schema="dbo")
    spec.fetch(conn=None)
    assert "[Conference].[v_Company]" in cap["sql"]
    assert reg  # registry module import kept for clarity


def test_row_limit_adds_select_top(monkeypatch):
    cap = {}

    def _fake(sql, conn, params=None):
        cap["sql"] = sql
        return pd.DataFrame({"CompanyID": [1]})

    monkeypatch.setattr(pd, "read_sql", _fake)
    entry = ViewCatalogEntry(view_name="v_Company", object_type="company", id_column="CompanyID")
    (spec,) = build_view_specs([entry], default_schema="cnf", row_limit=100)
    spec.fetch(conn=None)
    assert cap["sql"].startswith("SELECT TOP (100) *")
    # no limit → no TOP
    (spec2,) = build_view_specs([entry], default_schema="cnf", row_limit=0)
    spec2.fetch(conn=None)
    assert "TOP" not in cap["sql"]


def test_build_view_specs_propagates_exclude_columns():
    entry = ViewCatalogEntry(view_name="v_Company", object_type="company", id_column="CompanyID")
    (spec,) = build_view_specs([entry], default_schema="cnf", exclude_columns=("Secret",))
    df = pd.DataFrame([{"CompanyID": 1, "Secret": "x", "CompanyName": "Acme"}])
    body = json.loads(spec.build(df, datasource="ds")[0].body.text_content)
    assert "Secret" not in body
    assert body["CompanyName"] == "Acme"


def test_build_view_specs_propagates_fixed_view_url():
    # VIEW_URL (single fixed landing) flows through the catalog to every document.
    entry = ViewCatalogEntry(view_name="v_Company", object_type="company", id_column="CompanyID")
    (spec,) = build_view_specs([entry], default_schema="cnf", view_url="http://ems3/#/home")
    df = pd.DataFrame([{"CompanyID": 1}, {"CompanyID": 2}])
    docs = spec.build(df, datasource="ds")
    assert [d.view_url for d in docs] == ["http://ems3/#/home", "http://ems3/#/home"]
