"""Registry that turns the declarative view catalog into runnable ViewSpecs.

The in-scope views are listed once in ``catalog.py`` (VIEW_CATALOG). ``main.py``
calls ``build_view_specs(VIEW_CATALOG, ...)`` and iterates the result to fetch
each view as a DataFrame; document building happens separately in
``document_builder.build_conference_attendance_documents``.

Each view may declare a ``watermark_column`` (a change-tracking column such as
UpdatedOn) — stored here for future incremental sync support. Currently all
views are fetched in full because multi-view grouping makes per-view watermarking
complex (a catering change doesn't bump the attendee row's UpdatedOn).
"""

from dataclasses import dataclass

import pandas as pd
import pyodbc

from allenco_connector.views.catalog import ViewCatalogEntry


@dataclass(frozen=True)
class ViewSpec:
    """One EMS view: its schema, name, and watermark column."""

    view_name: str
    schema: str = "dbo"
    row_limit: int = 0  # 0 = no limit; >0 → SELECT TOP (N)
    watermark_column: str | None = None

    def fetch(self, conn: pyodbc.Connection, *, since: str | None = None) -> pd.DataFrame:
        """Read the view as a DataFrame.

        Incremental (``[watermark] > since``) when a watermark column is set
        and ``since`` is provided; otherwise a full read. When ``row_limit`` > 0,
        only the first N rows are read (``SELECT TOP (N)``) — a dry-run sample
        or a cap for very large views.
        """
        top = f"TOP ({self.row_limit}) " if self.row_limit > 0 else ""
        base = f"SELECT {top}* FROM [{self.schema}].[{self.view_name}]"
        if since is not None and self.watermark_column:
            sql = f"{base} WHERE [{self.watermark_column}] > ? ORDER BY [{self.watermark_column}]"
            return pd.read_sql(sql, conn, params=[since])
        return pd.read_sql(base, conn)


def build_view_specs(
    catalog: list[ViewCatalogEntry] | tuple[ViewCatalogEntry, ...],
    *,
    default_schema: str = "dbo",
    row_limit: int = 0,
) -> tuple[ViewSpec, ...]:
    """Build one ViewSpec per enabled catalog entry.

    An entry's ``schema`` overrides ``default_schema`` (from DB_SCHEMA).
    ``row_limit`` (from FETCH_ROW_LIMIT) applies to every view's fetch — 0 means
    no limit. Entries with ``enabled=False`` are skipped.
    """
    return tuple(
        ViewSpec(
            view_name=entry.view_name,
            schema=entry.schema or default_schema,
            row_limit=row_limit,
            watermark_column=entry.watermark_column,
        )
        for entry in catalog
        if entry.enabled
    )
