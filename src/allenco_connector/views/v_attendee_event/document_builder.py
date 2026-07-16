"""Build Glean documents from EMS v_Attendee_Event rows (skeleton).

TODO Allen & Co: confirm the real key / title columns and shape the body/ACLs.
"""

from collections.abc import Iterable

import pandas as pd
from glean.api_client.models.documentdefinition import DocumentDefinition
from glean.api_client.models.userreferencedefinition import UserReferenceDefinition

from allenco_connector.views._common import rows_to_documents

OBJECT_TYPE = "attendeeEvent"


def build_v_attendee_event_documents(
    df: pd.DataFrame,
    *,
    datasource: str,
    allowed_users: Iterable[UserReferenceDefinition] | None = None,
) -> list[DocumentDefinition]:
    """Convert v_Attendee_Event rows into Glean documents (one per row, skeleton)."""
    return rows_to_documents(
        df,
        object_type=OBJECT_TYPE,
        datasource=datasource,
        id_column="AttendeeEventID",  # TODO: confirm real key column
        title_columns=("EventName", "AttendeeID"),  # TODO: confirm real columns
        allowed_users=allowed_users,
    )
