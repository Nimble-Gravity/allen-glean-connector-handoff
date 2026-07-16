"""GET /aggregate — run a grouped aggregation against a named view."""

import logging

import pyodbc
from db import get_connection
from dependencies import (
    get_db_settings,
    get_notifier,
    get_superuser_emails,
    get_view_perm_cache,
)
from fastapi import APIRouter, Depends, HTTPException
from notifications_setup import Notifier, notify_db_error
from permissions import PERMISSION_DENIED_MESSAGE, check_user_has_view_access
from schemas import QueryResponse
from settings import DbSettings
from validators import SAFE_IDENTIFIER, _coerce

logger = logging.getLogger(__name__)
router = APIRouter(tags=["aggregate"])

_VALID_AGGREGATIONS = {"count", "sum", "avg", "min", "max"}


@router.get("/aggregate", response_model=QueryResponse)
def get_aggregate(
    user_email: str,
    view_name: str,
    aggregation: str,
    agg_column: str | None = None,
    group_by_column: str | None = None,
    filter_by_column: str | None = None,
    filter_value: str | None = None,
    settings: DbSettings = Depends(get_db_settings),
    notifier: Notifier = Depends(get_notifier),
    view_perm_cache: dict[str, str] = Depends(get_view_perm_cache),
    superuser_emails: frozenset[str] = Depends(get_superuser_emails),
) -> QueryResponse:

    agg = aggregation.lower()
    if agg not in _VALID_AGGREGATIONS:
        raise HTTPException(
            status_code=400,
            detail="aggregation must be one of: count, sum, avg, min, max.",
        )
    if agg != "count" and agg_column is None:
        raise HTTPException(
            status_code=400,
            detail="agg_column is required when aggregation is sum, avg, min, or max.",
        )
    if not SAFE_IDENTIFIER.match(view_name):
        raise HTTPException(
            status_code=400,
            detail="view_name must contain only letters, digits, and underscores.",
        )
    if agg_column is not None and not SAFE_IDENTIFIER.match(agg_column):
        raise HTTPException(
            status_code=400,
            detail="agg_column must contain only letters, digits, and underscores.",
        )
    if group_by_column is not None and not SAFE_IDENTIFIER.match(group_by_column):
        raise HTTPException(
            status_code=400,
            detail="group_by_column must contain only letters, digits, and underscores.",
        )
    if filter_by_column is not None and not SAFE_IDENTIFIER.match(filter_by_column):
        raise HTTPException(
            status_code=400,
            detail="filter_by_column must contain only letters, digits, and underscores.",
        )

    agg_expr = (
        "COUNT(*) AS [count]" if agg == "count" else f"{agg.upper()}([{agg_column}]) AS [{agg}]"
    )
    select_clause = f"[{group_by_column}], {agg_expr}" if group_by_column else agg_expr

    try:
        conn = get_connection(settings)
    except pyodbc.Error as exc:
        logger.exception("DB connection error in GET /aggregate")
        notify_db_error(notifier, "GET /aggregate", exc)
        raise HTTPException(
            status_code=500, detail="Database error. Please try again later."
        ) from exc

    try:
        if not check_user_has_view_access(user_email, view_name, view_perm_cache, superuser_emails):
            raise HTTPException(status_code=403, detail=PERMISSION_DENIED_MESSAGE)

        cursor = conn.cursor()

        cursor.execute(
            "SELECT COUNT(*) FROM INFORMATION_SCHEMA.VIEWS WHERE TABLE_NAME = ?",
            view_name,
        )
        if cursor.fetchone()[0] == 0:
            raise HTTPException(status_code=404, detail=f"View '{view_name}' not found.")

        parts = [f"SELECT {select_clause} FROM [{view_name}]"]
        params: list = []

        if filter_by_column is not None and filter_value is not None:
            parts.append(f"WHERE [{filter_by_column}] = ?")
            params.append(filter_value)

        if group_by_column is not None:
            parts.append(f"GROUP BY [{group_by_column}]")
            parts.append(f"ORDER BY [{group_by_column}]")

        cursor.execute(" ".join(parts), tuple(params))
        col_names = [col[0] for col in cursor.description]
        rows = [
            {col: _coerce(val) for col, val in zip(col_names, row, strict=False)}
            for row in cursor.fetchall()
        ]
        return QueryResponse(data=rows, row_count=len(rows))

    except HTTPException:
        raise
    except pyodbc.Error as exc:
        logger.exception("DB error in GET /aggregate")
        notify_db_error(notifier, "GET /aggregate", exc)
        raise HTTPException(
            status_code=500, detail="Database error. Please try again later."
        ) from exc
    finally:
        conn.close()
