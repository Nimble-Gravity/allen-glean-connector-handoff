import logging
from collections.abc import Iterable

from glean.api_client.models.datasourceuserdefinition import DatasourceUserDefinition

from glean_index.client import GleanConfig, get_glean_client, iter_chunks

logger = logging.getLogger(__name__)


def bulk_index_users(
    *,
    datasource: str,
    upload_id: str,
    users: Iterable[DatasourceUserDefinition],
    is_first_page: bool,
    is_last_page: bool,
    force_restart_upload: bool,
    disable_stale_data_deletion_check: bool = True,
    timeout_ms: int | None = None,
    config: GleanConfig | None = None,
) -> None:
    """Bulk index users in Glean (permissions API)."""
    client = get_glean_client(config)
    users_list = list(users)
    logger.debug(
        "bulk_index_users datasource=%s upload_id=%s count=%s first=%s last=%s",
        datasource,
        upload_id,
        len(users_list),
        is_first_page,
        is_last_page,
    )
    client.indexing.permissions.bulk_index_users(
        upload_id=upload_id,
        datasource=datasource,
        users=users_list,
        is_first_page=is_first_page,
        is_last_page=is_last_page,
        force_restart_upload=force_restart_upload,
        disable_stale_data_deletion_check=disable_stale_data_deletion_check,
        timeout_ms=timeout_ms,
    )


def bulk_index_users_paged(
    *,
    datasource: str,
    upload_id: str,
    users: Iterable[DatasourceUserDefinition],
    page_size: int = 1000,
    force_restart_upload_first_page: bool = True,
    disable_stale_data_deletion_check: bool = True,
    timeout_ms: int | None = None,
    config: GleanConfig | None = None,
) -> None:
    """Bulk index users to Glean in multiple pages."""
    page_size = max(1, int(page_size))
    chunks = iter_chunks(users, chunk_size=page_size)
    try:
        current = next(chunks)
    except StopIteration:
        return

    page_idx = 0
    for next_chunk in chunks:
        bulk_index_users(
            datasource=datasource,
            upload_id=upload_id,
            users=current,
            is_first_page=page_idx == 0,
            is_last_page=False,
            force_restart_upload=force_restart_upload_first_page and page_idx == 0,
            disable_stale_data_deletion_check=disable_stale_data_deletion_check,
            timeout_ms=timeout_ms,
            config=config,
        )
        current = next_chunk
        page_idx += 1

    bulk_index_users(
        datasource=datasource,
        upload_id=upload_id,
        users=current,
        is_first_page=page_idx == 0,
        is_last_page=True,
        force_restart_upload=force_restart_upload_first_page and page_idx == 0,
        disable_stale_data_deletion_check=disable_stale_data_deletion_check,
        timeout_ms=timeout_ms,
        config=config,
    )
