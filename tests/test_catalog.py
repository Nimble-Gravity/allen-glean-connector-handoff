"""Tests for the declarative view catalog and the catalog-driven registry."""

import pandas as pd

from allenco_connector.views import registry as reg
from allenco_connector.views.catalog import VIEW_CATALOG, ViewCatalogEntry
from allenco_connector.views.registry import build_view_specs


def test_default_schema_inherited_when_entry_unset():
    entry = ViewCatalogEntry(view_name="v_X")  # schema=None
    (spec,) = build_view_specs([entry], default_schema="Conference")
    assert spec.schema == "Conference"


def test_real_catalog_all_rpt_schema():
    assert all(e.schema == "rpt" for e in VIEW_CATALOG)


def test_real_catalog_enabled_views():
    enabled = [e for e in VIEW_CATALOG if e.enabled]
    assert {e.view_name for e in enabled} == {
        "v_EventInstance_Attendee",
        "v_Catering_TableAssignment",
        "v_Activity_Attendee_TimeRange",
        "v_TravelAir",
        "v_TravelGround",
    }


def test_real_catalog_disabled_views_need_conference_image():
    disabled = [e for e in VIEW_CATALOG if not e.enabled]
    assert {e.view_name for e in disabled} == {
        "v_Attendee_Global",
        "v_Invitation_CurrentStatus",
    }


def test_real_catalog_enabled_specs_use_rpt():
    specs = build_view_specs(VIEW_CATALOG, default_schema="dbo")
    assert all(s.schema == "rpt" for s in specs)
    enabled = [e for e in VIEW_CATALOG if e.enabled]
    assert len(specs) == len(enabled)


def test_build_view_specs_skips_disabled_entries():
    on = ViewCatalogEntry(view_name="v_on")
    off = ViewCatalogEntry(view_name="v_off", enabled=False)
    specs = build_view_specs([on, off], default_schema="cnf")
    assert [s.view_name for s in specs] == ["v_on"]


def test_entry_schema_overrides_default():
    entry = ViewCatalogEntry(view_name="v_X", schema="dbo")
    (spec,) = build_view_specs([entry], default_schema="Conference")
    assert spec.schema == "dbo"


def test_fetch_uses_schema_qualified_name(monkeypatch):
    cap = {}

    def _fake(sql, conn, params=None):
        cap["sql"] = sql
        return pd.DataFrame({"CompanyID": [1]})

    monkeypatch.setattr(pd, "read_sql", _fake)
    entry = ViewCatalogEntry(view_name="v_Company", schema="Conference")
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
    entry = ViewCatalogEntry(view_name="v_Company")
    (spec,) = build_view_specs([entry], default_schema="cnf", row_limit=100)
    spec.fetch(conn=None)
    assert cap["sql"].startswith("SELECT TOP (100) *")
    # no limit → no TOP
    (spec2,) = build_view_specs([entry], default_schema="cnf", row_limit=0)
    spec2.fetch(conn=None)
    assert "TOP" not in cap["sql"]


def test_watermark_column_propagated():
    entry = ViewCatalogEntry(view_name="v_X", watermark_column="UpdatedOn")
    (spec,) = build_view_specs([entry], default_schema="dbo")
    assert spec.watermark_column == "UpdatedOn"


def test_primary_view_declares_custom_property_columns():
    """v_EventInstance_Attendee must declare all props emitted by document_builder."""
    primary = next(e for e in VIEW_CATALOG if e.view_name == "v_EventInstance_Attendee")
    assert set(primary.property_columns) == {"attendeeName", "eventInstanceId", "company", "attendeeCode"}


def test_secondary_views_have_no_property_columns():
    """Detail views aggregate into the same document; they don't declare extra props."""
    secondary = [e for e in VIEW_CATALOG if e.view_name != "v_EventInstance_Attendee"]
    assert all(e.property_columns == () for e in secondary)
