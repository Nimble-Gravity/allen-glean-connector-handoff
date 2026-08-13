import os
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from itertools import islice

from glean.api_client import Glean
from glean.api_client.utils.retries import BackoffStrategy, RetryConfig

MAX_INDEX_DOCUMENTS_PAGE_SIZE = 500


def _normalize_instance(value: str) -> str:
    """Return the bare Glean instance name, tolerating a pasted full URL.

    The SDK builds the server URL from the instance NAME (``https://<name>-be.glean.com``),
    so a full URL must be reduced first, e.g.
    ``https://ed1d9232-be.glean.com/api/index/v1/`` -> ``ed1d9232``. A bare name is
    returned unchanged.
    """
    v = (value or "").strip()
    if "://" in v:
        v = v.split("://", 1)[1]
    v = v.split("/", 1)[0]  # host only, drop any path
    for suffix in ("-be.glean.com", ".glean.com"):
        if v.endswith(suffix):
            return v[: -len(suffix)]
    return v


@dataclass(frozen=True)
class GleanConfig:
    """Configuration required to call the Glean Indexing API."""

    instance: str
    indexing_api_key: str

    def __post_init__(self) -> None:
        # Tolerate a full URL pasted into GLEAN_INSTANCE — reduce it to the name.
        object.__setattr__(self, "instance", _normalize_instance(self.instance))

    @staticmethod
    def from_env() -> "GleanConfig":
        instance = (os.environ.get("GLEAN_INSTANCE") or "").strip()
        api_key = (os.environ.get("GLEAN_INDEXING_API_KEY") or "").strip()
        if not instance or not api_key:
            raise ValueError(
                "Missing Glean configuration. "
                "Set GLEAN_INSTANCE and GLEAN_INDEXING_API_KEY in .env."
            )
        return GleanConfig(instance=instance, indexing_api_key=api_key)


_client: Glean | None = None


def default_indexing_retry_config() -> RetryConfig:
    """Backoff retries for transient Glean Indexing API failures (429, 5xx, etc.).

    retry_connection_errors=False: DNS failures and TCP errors are not transient;
    retrying them for up to an hour wastes time and produces confusing logs.
    """
    return RetryConfig(
        strategy="backoff",
        backoff=BackoffStrategy(
            initial_interval=2_000,
            max_interval=120_000,
            exponent=1.5,
            max_elapsed_time=3_600_000,
        ),
        retry_connection_errors=False,
    )


def iter_chunks[T](items: Iterable[T], *, chunk_size: int) -> Iterator[list[T]]:
    """Yield list chunks from an iterable without materializing it fully."""
    size = max(1, int(chunk_size))
    it = iter(items)
    while True:
        chunk = list(islice(it, size))
        if not chunk:
            return
        yield chunk


def get_glean_client(config: GleanConfig | None = None) -> Glean:
    """Return a singleton Glean SDK client (Indexing API)."""
    global _client
    if _client is not None:
        return _client
    cfg = config or GleanConfig.from_env()
    _client = Glean(
        api_token=cfg.indexing_api_key,
        instance=cfg.instance,
        retry_config=default_indexing_retry_config(),
    )
    return _client
