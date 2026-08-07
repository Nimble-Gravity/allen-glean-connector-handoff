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

    def fetch(self, conn: pyodbc.Connection, *, since: str | None = None) -> pd.DataFrame:
        """Read the view. Incremental (``[watermark] > since``) when a watermark
        column is set and ``since`` is provided; otherwise a full read."""
        base = f"SELECT * FROM [{self.schema}].[{self.view_name}]"
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
) -> tuple[ViewSpec, ...]:
    """Build one ViewSpec per catalog entry.

    An entry's ``schema`` overrides ``default_schema`` (from DB_SCHEMA); an entry's
    ``build`` overrides the generic row→document mapping.
    """
    return tuple(
        ViewSpec(
            view_name=entry.view_name,
            build=builder_for(entry),
            watermark_column=entry.watermark_column,
            schema=entry.schema or default_schema,
        )
        for entry in catalog
    )
