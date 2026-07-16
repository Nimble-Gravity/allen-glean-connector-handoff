"""Build Glean documents from EMS v_Company rows (skeleton).

TODO Allen & Co: confirm the real PK / title columns and shape the body/ACLs.
"""

from collections.abc import Iterable

import pandas as pd
from glean.api_client.models.documentdefinition import DocumentDefinition
from glean.api_client.models.userreferencedefinition import UserReferenceDefinition

from allenco_connector.views._common import rows_to_documents

OBJECT_TYPE = "company"


def build_v_company_documents(
    df: pd.DataFrame,
    *,
    datasource: str,
    allowed_users: Iterable[UserReferenceDefinition] | None = None,
) -> list[DocumentDefinition]:
    """Convert v_Company rows into Glean documents (one per company, skeleton)."""
    return rows_to_documents(
        df,
        object_type=OBJECT_TYPE,
        datasource=datasource,
        id_column="CompanyID",  # TODO: confirm real PK column
        title_columns=("CompanyName",),  # TODO: confirm real column
        allowed_users=allowed_users,
    )
