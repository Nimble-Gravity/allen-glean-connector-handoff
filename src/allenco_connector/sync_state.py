"""Durable sync-state store — lets the indexer index incrementally.

The architecture ("Persist sync metadata to avoid re-processing") calls for the
connector to remember what it has already indexed. The EMS Replica is read-only,
so the state lives in a separate store, chosen by ``SYNC_STATE_BACKEND``:

- ``none`` (default) — no persistence; every run is a full fetch. Safe on ANY
  schema because no watermark column is ever referenced.
- ``file`` — a local JSON file (dev / docker-compose).
- ``blob`` — Azure Blob Storage (prod), authenticated via the workload's managed
  identity (DefaultAzureCredential). Requires the optional ``azure`` extra.

Per view we store the max value of its watermark column seen on the last run;
the next run only fetches rows with ``[watermark] > <stored>``.
"""

import json
import logging
import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class SyncState:
    """Per-view sync watermarks, persisted between runs."""

    # view_name -> {"watermark": str|None, "count": int, "last_run": iso8601}
    views: dict[str, dict] = field(default_factory=dict)

    def watermark_for(self, view_name: str) -> str | None:
        return (self.views.get(view_name) or {}).get("watermark")

    def set_watermark(self, view_name: str, watermark: str | None, *, count: int) -> None:
        self.views[view_name] = {
            "watermark": watermark,
            "count": count,
            "last_run": datetime.now(tz=UTC).isoformat(),
        }

    def to_dict(self) -> dict:
        return {"views": self.views}

    @staticmethod
    def from_dict(data: dict | None) -> "SyncState":
        return SyncState(views=dict((data or {}).get("views") or {}))


class SyncStateStore(ABC):
    """A place to load/save the SyncState. ``incremental`` gates watermark use."""

    incremental: bool = True

    @abstractmethod
    def load(self) -> SyncState: ...

    @abstractmethod
    def save(self, state: SyncState) -> None: ...


class NullSyncStateStore(SyncStateStore):
    """No persistence — every run is a full fetch."""

    incremental = False

    def load(self) -> SyncState:
        return SyncState()

    def save(self, state: SyncState) -> None:
        return None


class FileSyncStateStore(SyncStateStore):
    """Persist the SyncState to a local JSON file (dev)."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)

    def load(self) -> SyncState:
        if not self._path.is_file():
            return SyncState()
        try:
            return SyncState.from_dict(json.loads(self._path.read_text(encoding="utf-8")))
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Sync state at %s unreadable (%s); starting fresh.", self._path, exc)
            return SyncState()

    def save(self, state: SyncState) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        self._path.write_text(json.dumps(state.to_dict(), indent=2), encoding="utf-8")
        logger.info("Persisted sync state to %s", self._path)


class BlobSyncStateStore(SyncStateStore):
    """Persist the SyncState to an Azure Blob (prod, managed identity).

    Lazy-imports the azure SDK so the core stays dependency-light; install the
    ``azure`` extra (azure-storage-blob, azure-identity) where this is used.
    """

    def __init__(
        self, account_url: str, container: str, blob_name: str, *, client_id: str = ""
    ) -> None:
        self._account_url = account_url
        self._container = container
        self._blob_name = blob_name
        self._client_id = client_id

    def _credential(self):
        # Production (Azure-hosted): use the workload's managed identity directly —
        # ManagedIdentityCredential is deterministic (no fallback chain). A
        # user-assigned identity must be selected by its client id. Fall back to
        # DefaultAzureCredential only for local dev (az login / VS Code creds).
        if self._client_id:
            from azure.identity import ManagedIdentityCredential

            return ManagedIdentityCredential(client_id=self._client_id)
        from azure.identity import DefaultAzureCredential

        return DefaultAzureCredential()

    def _client(self):
        from azure.storage.blob import BlobClient

        return BlobClient(
            account_url=self._account_url,
            container_name=self._container,
            blob_name=self._blob_name,
            credential=self._credential(),
        )

    def load(self) -> SyncState:
        from azure.core.exceptions import ResourceNotFoundError

        try:
            data = self._client().download_blob().readall()
        except ResourceNotFoundError:
            return SyncState()
        return SyncState.from_dict(json.loads(data))

    def save(self, state: SyncState) -> None:
        payload = json.dumps(state.to_dict(), indent=2).encode("utf-8")
        self._client().upload_blob(payload, overwrite=True)
        logger.info("Persisted sync state to blob %s/%s", self._container, self._blob_name)


def build_sync_state_store() -> SyncStateStore:
    """Build the sync-state store from the environment. Defaults to no-op."""
    backend = (os.environ.get("SYNC_STATE_BACKEND") or "none").strip().lower()
    if backend == "file":
        return FileSyncStateStore(
            (os.environ.get("SYNC_STATE_FILE") or ".sync-state/state.json").strip()
        )
    if backend == "blob":
        account_url = (os.environ.get("SYNC_STATE_BLOB_ACCOUNT_URL") or "").strip()
        container = (os.environ.get("SYNC_STATE_BLOB_CONTAINER") or "sync-state").strip()
        blob_name = (
            os.environ.get("SYNC_STATE_BLOB_NAME") or "allenco-connector-state.json"
        ).strip()
        if not account_url:
            logger.warning(
                "SYNC_STATE_BACKEND=blob but SYNC_STATE_BLOB_ACCOUNT_URL is unset; "
                "sync state disabled (full fetch each run)."
            )
            return NullSyncStateStore()
        # AZURE_CLIENT_ID selects the user-assigned managed identity in prod; empty
        # locally so BlobSyncStateStore falls back to DefaultAzureCredential.
        client_id = (os.environ.get("AZURE_CLIENT_ID") or "").strip()
        return BlobSyncStateStore(account_url, container, blob_name, client_id=client_id)
    return NullSyncStateStore()
