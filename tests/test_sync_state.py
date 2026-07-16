"""Tests for the incremental sync-state store and ViewSpec incremental fetch."""

import pandas as pd

from allenco_connector.sync_state import (
    BlobSyncStateStore,
    FileSyncStateStore,
    NullSyncStateStore,
    SyncState,
    build_sync_state_store,
)
from allenco_connector.views.registry import ViewSpec

# --- SyncState ---


def test_sync_state_set_get_and_roundtrip():
    st = SyncState()
    assert st.watermark_for("v_Attendee") is None
    st.set_watermark("v_Attendee", "2026-05-09T10:00:00", count=5)
    assert st.watermark_for("v_Attendee") == "2026-05-09T10:00:00"
    restored = SyncState.from_dict(st.to_dict())
    assert restored.watermark_for("v_Attendee") == "2026-05-09T10:00:00"
    assert restored.views["v_Attendee"]["count"] == 5


def test_sync_state_from_dict_tolerates_empty():
    assert SyncState.from_dict(None).views == {}
    assert SyncState.from_dict({}).views == {}


# --- stores ---


def test_file_store_roundtrip(tmp_path):
    store = FileSyncStateStore(tmp_path / "state.json")
    assert store.load().views == {}  # missing file → empty
    st = SyncState()
    st.set_watermark("v_Company", "2026-05-04T09:00:00", count=4)
    store.save(st)
    assert store.load().watermark_for("v_Company") == "2026-05-04T09:00:00"


def test_file_store_bad_json_starts_fresh(tmp_path):
    p = tmp_path / "state.json"
    p.write_text("{ not json", encoding="utf-8")
    assert FileSyncStateStore(p).load().views == {}


def test_null_store_is_not_incremental():
    store = NullSyncStateStore()
    assert store.incremental is False
    assert store.load().views == {}
    store.save(SyncState())  # no-op, must not raise


# --- factory ---


def test_build_store_defaults_to_null(monkeypatch):
    monkeypatch.delenv("SYNC_STATE_BACKEND", raising=False)
    assert isinstance(build_sync_state_store(), NullSyncStateStore)


def test_build_store_file(monkeypatch, tmp_path):
    monkeypatch.setenv("SYNC_STATE_BACKEND", "file")
    monkeypatch.setenv("SYNC_STATE_FILE", str(tmp_path / "s.json"))
    assert isinstance(build_sync_state_store(), FileSyncStateStore)


def test_build_store_blob(monkeypatch):
    monkeypatch.setenv("SYNC_STATE_BACKEND", "blob")
    monkeypatch.setenv("SYNC_STATE_BLOB_ACCOUNT_URL", "https://acct.blob.core.windows.net")
    assert isinstance(build_sync_state_store(), BlobSyncStateStore)


def test_build_store_blob_without_url_falls_back_to_null(monkeypatch):
    monkeypatch.setenv("SYNC_STATE_BACKEND", "blob")
    monkeypatch.delenv("SYNC_STATE_BLOB_ACCOUNT_URL", raising=False)
    assert isinstance(build_sync_state_store(), NullSyncStateStore)


def test_build_store_blob_reads_client_id(monkeypatch):
    monkeypatch.setenv("SYNC_STATE_BACKEND", "blob")
    monkeypatch.setenv("SYNC_STATE_BLOB_ACCOUNT_URL", "https://acct.blob.core.windows.net")
    monkeypatch.setenv("AZURE_CLIENT_ID", "mi-client-999")
    store = build_sync_state_store()
    assert isinstance(store, BlobSyncStateStore)
    assert store._client_id == "mi-client-999"


def test_blob_store_credential_selection(monkeypatch):
    """client_id present → ManagedIdentityCredential; absent → DefaultAzureCredential."""
    import sys
    import types

    calls = {}

    fake_identity = types.ModuleType("azure.identity")

    def _mic(*, client_id):
        calls["managed"] = client_id
        return "managed-cred"

    def _dac():
        calls["default"] = True
        return "default-cred"

    fake_identity.ManagedIdentityCredential = _mic
    fake_identity.DefaultAzureCredential = _dac
    monkeypatch.setitem(sys.modules, "azure", types.ModuleType("azure"))
    monkeypatch.setitem(sys.modules, "azure.identity", fake_identity)

    with_id = BlobSyncStateStore("u", "c", "b", client_id="cid-1")
    assert with_id._credential() == "managed-cred"
    assert calls["managed"] == "cid-1"

    without_id = BlobSyncStateStore("u", "c", "b")
    assert without_id._credential() == "default-cred"
    assert calls.get("default") is True


# --- ViewSpec incremental fetch ---


def _patch_read_sql(monkeypatch, df, captured):
    def _fake(sql, conn, params=None):
        captured["sql"] = sql
        captured["params"] = params
        return df

    monkeypatch.setattr(pd, "read_sql", _fake)


def test_viewspec_full_fetch_omits_watermark(monkeypatch):
    cap = {}
    _patch_read_sql(monkeypatch, pd.DataFrame({"CompanyID": [1]}), cap)
    spec = ViewSpec(
        view_name="v_Company", build=lambda df, **k: [], watermark_column="ModifiedDate"
    )
    spec.fetch(conn=None, since=None)
    assert "WHERE" not in cap["sql"]
    assert cap["params"] is None


def test_viewspec_incremental_fetch_uses_watermark(monkeypatch):
    cap = {}
    _patch_read_sql(monkeypatch, pd.DataFrame({"CompanyID": [1]}), cap)
    spec = ViewSpec(
        view_name="v_Company", build=lambda df, **k: [], watermark_column="ModifiedDate"
    )
    spec.fetch(conn=None, since="2026-05-01T00:00:00")
    assert "WHERE [ModifiedDate] > ?" in cap["sql"]
    assert "ORDER BY [ModifiedDate]" in cap["sql"]
    assert cap["params"] == ["2026-05-01T00:00:00"]


def test_viewspec_build_documents_returns_max_watermark(monkeypatch):
    df = pd.DataFrame(
        {"CompanyID": [1, 2], "ModifiedDate": ["2026-05-01T09:00:00", "2026-05-04T09:00:00"]}
    )
    _patch_read_sql(monkeypatch, df, {})
    spec = ViewSpec(
        view_name="v_Company",
        build=lambda df, *, datasource, allowed_users=None: list(range(len(df))),
        watermark_column="ModifiedDate",
    )
    docs, watermark = spec.build_documents(conn=None, datasource="ds")
    assert len(docs) == 2
    assert watermark == "2026-05-04T09:00:00"


def test_viewspec_no_watermark_column_returns_none(monkeypatch):
    _patch_read_sql(monkeypatch, pd.DataFrame({"CompanyID": [1]}), {})
    spec = ViewSpec(view_name="v_Company", build=lambda df, **k: [1], watermark_column=None)
    _docs, watermark = spec.build_documents(conn=None, datasource="ds")
    assert watermark is None
