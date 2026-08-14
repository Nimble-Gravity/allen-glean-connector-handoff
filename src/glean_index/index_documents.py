import logging
from collections.abc import Iterable

from glean.api_client.models.documentdefinition import DocumentDefinition

from glean_index.client import (
    MAX_INDEX_DOCUMENTS_PAGE_SIZE,
    GleanConfig,
    get_glean_client,
    iter_chunks,
)

logger = logging.getLogger(__name__)


def dedupe_documents_by_id(
    documents: list[DocumentDefinition],
) -> tuple[list[DocumentDefinition], int]:
    """Drop documents whose id already appeared (last one wins).

    Glean rejects a bulk upload that contains duplicate document ids, and some views
    lack a unique per-row key (e.g. v_TravelAir keyed by AttendeeID → one attendee has
    several flights). Returns (deduped_documents, number_dropped).
    """
    by_id: dict[str, DocumentDefinition] = {}
    for doc in documents:
        by_id[doc.id] = doc
    return list(by_id.values()), len(documents) - len(by_id)


def bulk_index_documents(
    *,
    datasource: str,
    upload_id: str,
    documents: Iterable[DocumentDefinition],
    is_first_page: bool,
    is_last_page: bool,
    force_restart_upload: bool,
    disable_stale_document_deletion_check: bool | None = None,
    timeout_ms: int | None = None,
    config: GleanConfig | None = None,
) -> None:
    """Bulk index documents in Glean (full upload / replace semantics per upload_id)."""
    client = get_glean_client(config)
    docs = list(documents)
    logger.debug(
        "bulk_index_documents datasource=%s upload_id=%s count=%s first=%s last=%s",
        datasource,
        upload_id,
        len(docs),
        is_first_page,
        is_last_page,
    )
    effective_disable_stale = disable_stale_document_deletion_check if is_last_page else None
    client.indexing.documents.bulk_index(
        upload_id=upload_id,
        datasource=datasource,
        documents=docs,
        is_first_page=is_first_page,
        is_last_page=is_last_page,
        force_restart_upload=force_restart_upload,
        disable_stale_document_deletion_check=effective_disable_stale,
        timeout_ms=timeout_ms,
    )


def bulk_index_documents_paged(
    *,
    datasource: str,
    upload_id: str,
    documents: Iterable[DocumentDefinition],
    page_size: int = 1000,
    force_restart_upload_first_page: bool = True,
    disable_stale_document_deletion_check: bool | None = None,
    timeout_ms: int | None = None,
    config: GleanConfig | None = None,
) -> None:
    """Bulk index documents in Glean, splitting into multiple pages."""
    page_size = max(1, int(page_size))
    chunks = iter_chunks(documents, chunk_size=page_size)
    try:
        current = next(chunks)
    except StopIteration:
        return

    page_idx = 0
    for next_chunk in chunks:
        bulk_index_documents(
            datasource=datasource,
            upload_id=upload_id,
            documents=current,
            is_first_page=page_idx == 0,
            is_last_page=False,
            force_restart_upload=force_restart_upload_first_page and page_idx == 0,
            disable_stale_document_deletion_check=None,
            timeout_ms=timeout_ms,
            config=config,
        )
        current = next_chunk
        page_idx += 1

    bulk_index_documents(
        datasource=datasource,
        upload_id=upload_id,
        documents=current,
        is_first_page=page_idx == 0,
        is_last_page=True,
        force_restart_upload=force_restart_upload_first_page and page_idx == 0,
        disable_stale_document_deletion_check=disable_stale_document_deletion_check,
        timeout_ms=timeout_ms,
        config=config,
    )


def index_documents(
    *,
    datasource: str,
    documents: Iterable[DocumentDefinition],
    upload_id: str | None = None,
    timeout_ms: int | None = None,
    config: GleanConfig | None = None,
) -> None:
    """Incrementally add/update documents (IndexDocuments API)."""
    client = get_glean_client(config)
    docs = list(documents)
    logger.debug("index_documents datasource=%s count=%s", datasource, len(docs))
    client.indexing.documents.index(
        datasource=datasource,
        documents=docs,
        upload_id=upload_id,
        timeout_ms=timeout_ms,
    )


def index_documents_paged(
    *,
    datasource: str,
    documents: Iterable[DocumentDefinition],
    upload_id: str | None = None,
    page_size: int = MAX_INDEX_DOCUMENTS_PAGE_SIZE,
    timeout_ms: int | None = None,
    config: GleanConfig | None = None,
) -> None:
    """Incrementally add/update documents in multiple pages (max page size capped at 500)."""
    page_size = min(MAX_INDEX_DOCUMENTS_PAGE_SIZE, max(1, int(page_size)))
    for chunk in iter_chunks(documents, chunk_size=page_size):
        index_documents(
            datasource=datasource,
            documents=chunk,
            upload_id=upload_id,
            timeout_ms=timeout_ms,
            config=config,
        )


def index_document(
    *,
    document: DocumentDefinition,
    timeout_ms: int | None = None,
    config: GleanConfig | None = None,
) -> None:
    """Add or update a single document in Glean."""
    client = get_glean_client(config)
    client.indexing.documents.add_or_update(document=document, timeout_ms=timeout_ms)
