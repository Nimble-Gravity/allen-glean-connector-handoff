"""Tests for the declarative view catalog and the catalog-driven registry."""

import pandas as pd

from allenco_connector.views import registry as reg
from allenco_connector.views.catalog import VIEW_CATALOG, ViewCatalogEntry, builder_for
from allenco_connector.views.registry import build_view_specs


def test_build_view_specs_applies_default_schema():
    specs = build_view_specs(VIEW_CATALOG, default_schema="Conference")
    assert len(specs) == len(VIEW_CATALOG)
    assert all(s.schema == "Conference" for s in specs)


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
    assert docs[0].id == "7"
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
