"""Entry point for the Allen & Co → Glean connector (indexer).

One-shot batch job: read the four read-only EMS views from the Azure SQL MI, build
Glean documents with AD/Entra-derived ACLs, and push them via the Glean Indexing
API. Set GLEAN_ENABLE_INDEXING=false to dump documents to .outputs/ instead of
pushing (a dry run also tolerates an unreachable DB, producing zero documents).
"""

import logging
import time
import traceback
import uuid
from collections.abc import Callable
from dataclasses import dataclass

import pyodbc
from dotenv import load_dotenv

from allenco_connector.db_connection import get_connection
from allenco_connector.groups import load_users_with_groups
from allenco_connector.sync_state import build_sync_state_store
from allenco_connector.views.catalog import VIEW_CATALOG
from allenco_connector.views.registry import build_view_specs
from config.config import (
    ConnectorSettings,
    GroupsSettings,
    configure_logging,
    load_connector_settings,
    load_db_settings,
    load_groups_settings,
)
from glean_index.env_superusers import (
    extend_permissions_users_for_superusers,
    load_indexing_superusers_from_json,
    merge_allowed_user_references,
)
from glean_index.index_documents import (
    bulk_index_documents_paged,
    dedupe_documents_by_id,
    index_documents_paged,
)
from glean_index.index_users import bulk_index_users_paged
from glean_index.types.users import (
    GlobalUser,
    build_allowed_user_references,
    build_users_for_permissions_indexing,
)
from helpers.json_export import export_documents_to_json
from notifications.config import NotificationSettings
from notifications.events import ErrorEvent, ErrorType
from notifications.factory import build_notifier
from notifications.resolutions import resolution_for

logger = logging.getLogger(__name__)


@dataclass
class RunState:
    """Counts produced in the current run."""

    records_fetched: int = 0
    documents_indexed: int = 0


class _AlreadyNotified(Exception):
    """Wraps a fatal error already reported, so the top-level net doesn't double-report."""

    def __init__(self, cause: BaseException) -> None:
        super().__init__(str(cause))
        self.cause = cause


def load_source_users(
    conn: pyodbc.Connection | None,
    groups_settings: GroupsSettings,
) -> list[GlobalUser]:
    """Load users + their AD/Entra group memberships from the SQL groups view.

    Allen & Co's decided source is a read-only SQL view mirroring directory groups
    (config.GroupsSettings / DB_GROUPS_VIEW). Each GlobalUser's ``groups`` gate
    document access (glean_index.permission_policies). Returns [] when the view is
    unconfigured or the DB is unreachable (dry run) — the run then relies on
    superuser ACLs only.
    """
    return load_users_with_groups(conn, groups_settings)


def main() -> int:
    load_dotenv(override=True)
    settings = load_connector_settings()
    configure_logging(settings)

    notification_settings = NotificationSettings.from_env()
    notifier = build_notifier(notification_settings)

    run_id = str(uuid.uuid4())
    start = time.perf_counter()
    logger.info("Run started. run_id=%s", run_id)

    def notify(error_type: ErrorType, message: str, *, detail: str | None = None) -> None:
        """Report a connector failure (never raises)."""
        notifier.send(
            ErrorEvent(
                connector_name=notification_settings.connector_name,
                error_type=error_type,
                message=message,
                recommended_resolution=resolution_for(error_type),
                run_id=run_id,
                detail=detail,
            )
        )

    try:
        return _run(settings, notify, run_id, start)
    except _AlreadyNotified as wrapped:
        raise wrapped.cause from None
    except Exception as exc:
        notify(ErrorType.UNEXPECTED, str(exc), detail=traceback.format_exc())
        raise


def _run(
    settings: ConnectorSettings,
    notify: Callable[..., None],
    run_id: str,
    start: float,
) -> int:
    """Run the connector pipeline. Raises on fatal errors (see main())."""
    state = RunState()
    glean_enabled = settings.glean_enable_indexing
    full_refresh = settings.glean_full_refresh
    sync_ok = True

    # Durable sync state ("persist sync metadata to avoid re-processing"). No-op by
    # default; file/blob backends enable incremental fetch per view watermark.
    sync_store = build_sync_state_store()
    sync_state = sync_store.load()
    # full_refresh forces a complete re-index and resets watermarks to the new max.
    use_incremental = sync_store.incremental and not full_refresh

    # Glean prerequisites (only strictly required when actually indexing).
    datasource = settings.glean_datasource.strip()
    glean_cfg = None
    if glean_enabled:
        try:
            datasource, glean_cfg = settings.require_glean_indexing_prereqs()
        except ValueError as exc:
            notify(ErrorType.GLEAN_PREREQS, str(exc), detail=traceback.format_exc())
            raise _AlreadyNotified(exc) from exc

    # Connect to the Azure SQL MI. A dry run (indexing disabled) tolerates an
    # unreachable DB so the doc-building/export wiring can be validated offline.
    db_settings = load_db_settings()
    groups_settings = load_groups_settings()
    try:
        conn = get_connection(db_settings)
    except pyodbc.Error as exc:
        if glean_enabled:
            notify(ErrorType.DB_CONNECTION, str(exc), detail=traceback.format_exc())
            raise _AlreadyNotified(exc) from exc
        logger.warning(
            "DB connection failed during dry run (indexing disabled): %s. "
            "Continuing with 0 documents.",
            exc,
        )
        conn = None

    # Users + permissions (AD/Entra). Source users come from the SQL groups view
    # (config.GroupsSettings); superusers come from env. This needs the DB
    # connection, so it runs after connect — [] when the groups view is
    # unconfigured or the DB is unreachable (dry run), leaving superuser ACLs only.
    global_users = load_source_users(conn, groups_settings)
    indexing_superusers = load_indexing_superusers_from_json(
        settings.glean_indexing_superuser_allowed_users_json
    )
    allowed_refs = merge_allowed_user_references(
        build_allowed_user_references(global_users),
        [s.as_user_reference() for s in indexing_superusers],
    )
    users_for_permissions = extend_permissions_users_for_superusers(
        build_users_for_permissions_indexing(global_users),
        global_datasource_user_ids={u.datasource_user_id for u in global_users},
        superusers=indexing_superusers,
    )

    if settings.fetch_row_limit:
        logger.info(
            "FETCH_ROW_LIMIT=%d — sampling up to %d row(s) per view (SELECT TOP).",
            settings.fetch_row_limit,
            settings.fetch_row_limit,
        )
    elif glean_enabled:
        logger.warning(
            "GLEAN_ENABLE_INDEXING=true with NO FETCH_ROW_LIMIT — this will push EVERY "
            "row of every view (potentially millions). Set FETCH_ROW_LIMIT for a bounded run."
        )
    if settings.exclude_columns:
        logger.info(
            "EXCLUDE_COLUMNS — dropping %d column(s) from document bodies: %s",
            len(settings.exclude_columns),
            ", ".join(settings.exclude_columns),
        )

    documents: list = []
    if conn is not None:
        try:
            for spec in build_view_specs(
                VIEW_CATALOG,
                default_schema=db_settings.schema,
                row_limit=settings.fetch_row_limit,
                exclude_columns=settings.exclude_columns,
                view_url_base=settings.view_url_base,
            ):
                since = sync_state.watermark_for(spec.view_name) if use_incremental else None
                logger.info(
                    "Fetching %s (%s).",
                    spec.view_name,
                    f"incremental since {since}" if since else "full",
                )
                docs, new_watermark = spec.build_documents(
                    conn,
                    datasource=datasource,
                    allowed_users=allowed_refs or None,
                    since=since,
                )
                documents.extend(docs)
                state.records_fetched += len(docs)
                if sync_store.incremental and new_watermark is not None:
                    sync_state.set_watermark(spec.view_name, new_watermark, count=len(docs))
        finally:
            conn.close()

    # Glean rejects a bulk upload with duplicate document ids. Some views lack a
    # unique per-row key (see catalog TODOs), so collapse duplicates (last wins).
    documents, dropped_dupes = dedupe_documents_by_id(documents)
    if dropped_dupes:
        logger.warning(
            "Dropped %d document(s) with duplicate ids before indexing "
            "(views without a unique per-row key — see catalog TODOs).",
            dropped_dupes,
        )

    if not glean_enabled:
        export_documents_to_json(documents, "ems_documents")
        logger.info(
            "Glean indexing disabled (GLEAN_ENABLE_INDEXING=false). "
            "Exported %d document(s) to .outputs/. Exiting.",
            len(documents),
        )
        return 0

    def iter_documents():
        for doc in documents:
            state.documents_indexed += 1
            yield doc

    logger.info(
        "Starting Glean indexing. datasource=%s mode=%s superusers=%s documents=%s",
        datasource,
        "full_refresh" if full_refresh else "incremental",
        len(indexing_superusers),
        len(documents),
    )

    if users_for_permissions:
        try:
            bulk_index_users_paged(
                datasource=datasource,
                upload_id=f"{run_id}:users",
                users=users_for_permissions,
                page_size=1000,
                force_restart_upload_first_page=True,
                disable_stale_data_deletion_check=True,
                timeout_ms=120_000,
                config=glean_cfg,
            )
        except Exception as exc:
            sync_ok = False
            logger.exception("Glean user indexing failed; continuing with documents.")
            notify(ErrorType.USER_INDEXING, str(exc), detail=traceback.format_exc())

    try:
        if full_refresh:
            bulk_index_documents_paged(
                datasource=datasource,
                upload_id=f"{run_id}:documents",
                documents=iter_documents(),
                force_restart_upload_first_page=True,
                disable_stale_document_deletion_check=True,
                timeout_ms=120_000,
                config=glean_cfg,
            )
        else:
            index_documents_paged(
                datasource=datasource,
                upload_id=f"{run_id}:documents",
                documents=iter_documents(),
                timeout_ms=120_000,
                config=glean_cfg,
            )
    except Exception as exc:
        sync_ok = False
        logger.exception("Glean document indexing failed.")
        notify(ErrorType.DOCUMENT_INDEXING, str(exc), detail=traceback.format_exc())

    # Persist watermarks only after a successful index, so a failed run re-fetches.
    if sync_ok and sync_store.incremental:
        try:
            sync_store.save(sync_state)
        except Exception:
            logger.exception("Failed to persist sync state (indexing succeeded).")

    elapsed_s = time.perf_counter() - start
    logger.info(
        "Finished. run_id=%s records=%s documents=%s elapsed=%.2fs ok=%s",
        run_id,
        state.records_fetched,
        state.documents_indexed,
        elapsed_s,
        sync_ok,
    )
    return 0 if sync_ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
