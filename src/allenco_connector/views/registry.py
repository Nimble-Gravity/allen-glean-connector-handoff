"""Registry that turns the declarative view catalog into runnable ViewSpecs.

The in-scope views are listed once in ``catalog.py`` (VIEW_CATALOG). ``main.py``
calls ``build_view_specs(VIEW_CATALOG, default_schema=...)`` and iterates the
result — add or remove a view by editing the catalog, not this module.

Each view may declare a ``watermark_column`` (a change-tracking column such as
ModifiedDate) so the indexer can fetch **incrementally** (only rows newer than the
last persisted watermark). When it is None, or the sync-state backend is off, the
view is always fetched in full.
"""

from collections.abc import Callable, Iterable
from dataclasses import dataclass

import pandas as pd
import pyodbc
from glean.api_client.models.documentdefinition import DocumentDefinition
from glean.api_client.models.userreferencedefinition import UserReferenceDefinition

from allenco_connector.views.catalog import ViewCatalogEntry, builder_for

BuildFn = Callable[..., list[DocumentDefinition]]


@dataclass(frozen=True)
class ViewSpec:
    """One EMS view: its schema, name, how to build documents, and its watermark."""

    view_name: str
    build: BuildFn
    watermark_column: str | None = None
    schema: str = "dbo"
    row_limit: int = 0  # 0 = no limit; >0 → SELECT TOP (N) (dry-run sample / hard cap)

    def fetch(self, conn: pyodbc.Connection, *, since: str | None = None) -> pd.DataFrame:
        """Read the view. Incremental (``[watermark] > since``) when a watermark
        column is set and ``since`` is provided; otherwise a full read. When
        ``row_limit`` > 0, only the first N rows are read (``SELECT TOP (N)``) — a
        dry-run sample or a cap for very large views."""
        top = f"TOP ({self.row_limit}) " if self.row_limit > 0 else ""
        base = f"SELECT {top}* FROM [{self.schema}].[{self.view_name}]"
        if since is not None and self.watermark_column:
            sql = f"{base} WHERE [{self.watermark_column}] > ? ORDER BY [{self.watermark_column}]"
            return pd.read_sql(sql, conn, params=[since])
        return pd.read_sql(base, conn)

    def build_documents(
        self,
        conn: pyodbc.Connection,
        *,
        datasource: str,
        allowed_users: list[UserReferenceDefinition] | None = None,
        since: str | None = None,
    ) -> tuple[list[DocumentDefinition], str | None]:
        """Fetch + build. Returns (documents, new_watermark).

        new_watermark is the max value of the watermark column in the fetched rows
        (None if the view has no watermark column or returned no rows).
        """
        df = self.fetch(conn, since=since)
        docs = self.build(df, datasource=datasource, allowed_users=allowed_users)
        new_watermark: str | None = None
        if self.watermark_column and self.watermark_column in df.columns and not df.empty:
            new_watermark = str(df[self.watermark_column].max())
        return docs, new_watermark


def build_view_specs(
    catalog: Iterable[ViewCatalogEntry],
    *,
    default_schema: str = "dbo",
    row_limit: int = 0,
    exclude_columns: tuple[str, ...] = (),
    view_url_base: str = "",
) -> tuple[ViewSpec, ...]:
    """Build one ViewSpec per catalog entry.

    An entry's ``schema`` overrides ``default_schema`` (from DB_SCHEMA); an entry's
    ``build`` overrides the generic row→document mapping. ``row_limit`` (from
    FETCH_ROW_LIMIT) applies to every view's fetch — 0 means no limit.
    ``exclude_columns`` (EXCLUDE_COLUMNS) are dropped from every document body;
    ``view_url_base`` (VIEW_URL_BASE) stamps a per-row viewURL. Entries with
    ``enabled=False`` are skipped.
    """
    return tuple(
        ViewSpec(
            view_name=entry.view_name,
            build=builder_for(entry, exclude_columns, view_url_base),
            watermark_column=entry.watermark_column,
            schema=entry.schema or default_schema,
            row_limit=row_limit,
        )
        for entry in catalog
        if entry.enabled
    )
