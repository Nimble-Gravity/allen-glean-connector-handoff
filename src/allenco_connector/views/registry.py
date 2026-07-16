"""Registry of the EMS views the indexer snapshots into Glean.

The four read-only views in scope (SELECT only): v_Attendee, v_Attendee_Event,
v_Company, v_Participation. ``main.py`` iterates ``EMS_VIEWS`` — add or remove a
view here in one place.

Each view may declare a ``watermark_column`` (a change-tracking column such as
ModifiedDate) so the indexer can fetch **incrementally** (only rows newer than the
last persisted watermark). When it is None, or the sync-state backend is off, the
view is always fetched in full.
"""

from collections.abc import Callable
from dataclasses import dataclass

import pandas as pd
import pyodbc
from glean.api_client.models.documentdefinition import DocumentDefinition
from glean.api_client.models.userreferencedefinition import UserReferenceDefinition

from allenco_connector.views.v_attendee.document_builder import build_v_attendee_documents
from allenco_connector.views.v_attendee.query import (
    VIEW_NAME as V_ATTENDEE,
)
from allenco_connector.views.v_attendee.query import (
    WATERMARK_COLUMN as WM_ATTENDEE,
)
from allenco_connector.views.v_attendee_event.document_builder import (
    build_v_attendee_event_documents,
)
from allenco_connector.views.v_attendee_event.query import (
    VIEW_NAME as V_ATTENDEE_EVENT,
)
from allenco_connector.views.v_attendee_event.query import (
    WATERMARK_COLUMN as WM_ATTENDEE_EVENT,
)
from allenco_connector.views.v_company.document_builder import build_v_company_documents
from allenco_connector.views.v_company.query import (
    VIEW_NAME as V_COMPANY,
)
from allenco_connector.views.v_company.query import (
    WATERMARK_COLUMN as WM_COMPANY,
)
from allenco_connector.views.v_participation.document_builder import (
    build_v_participation_documents,
)
from allenco_connector.views.v_participation.query import (
    VIEW_NAME as V_PARTICIPATION,
)
from allenco_connector.views.v_participation.query import (
    WATERMARK_COLUMN as WM_PARTICIPATION,
)

BuildFn = Callable[..., list[DocumentDefinition]]


@dataclass(frozen=True)
class ViewSpec:
    """One EMS view: its name, how to build documents, and its watermark column."""

    view_name: str
    build: BuildFn
    watermark_column: str | None = None

    def fetch(self, conn: pyodbc.Connection, *, since: str | None = None) -> pd.DataFrame:
        """Read the view. Incremental (``[watermark] > since``) when a watermark
        column is set and ``since`` is provided; otherwise a full read."""
        base = f"SELECT * FROM [dbo].[{self.view_name}]"
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


EMS_VIEWS: tuple[ViewSpec, ...] = (
    ViewSpec(V_ATTENDEE, build_v_attendee_documents, WM_ATTENDEE),
    ViewSpec(V_ATTENDEE_EVENT, build_v_attendee_event_documents, WM_ATTENDEE_EVENT),
    ViewSpec(V_COMPANY, build_v_company_documents, WM_COMPANY),
    ViewSpec(V_PARTICIPATION, build_v_participation_documents, WM_PARTICIPATION),
)
