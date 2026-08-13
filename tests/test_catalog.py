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


def test_real_catalog_pins_cnf_schema():
    specs = build_view_specs(VIEW_CATALOG, default_schema="dbo")
    assert len(specs) == len(VIEW_CATALOG)
    # the Conference catalog pins schema="cnf" on every entry, so DB_SCHEMA is moot.
    assert all(s.schema == "cnf" for s in specs)


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
    docs = build(df, datasource="allenco_ems")
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
