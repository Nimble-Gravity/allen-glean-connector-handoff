"""GET /query — run a SELECT against a named view."""

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
router = APIRouter(tags=["query"])


@router.get("/query", response_model=QueryResponse)
def get_query(
    user_email: str,
    view_name: str,
    filter_by_column: str | None = None,
    filter_value: str | None = None,
    limit: int = 500,
    sort_by_column: str | None = None,
    sort_order: str | None = None,
    select_columns: str | None = None,
    distinct_column: str | None = None,
    settings: DbSettings = Depends(get_db_settings),
    notifier: Notifier = Depends(get_notifier),
    view_perm_cache: dict[str, str] = Depends(get_view_perm_cache),
    superuser_emails: frozenset[str] = Depends(get_superuser_emails),
) -> QueryResponse:

    if not SAFE_IDENTIFIER.match(view_name):
        raise HTTPException(
            status_code=400,
            detail="view_name must contain only letters, digits, and underscores.",
        )
    if filter_by_column is not None and not SAFE_IDENTIFIER.match(filter_by_column):
        raise HTTPException(
            status_code=400,
            detail="filter_by_column must contain only letters, digits, and underscores.",
        )
    if distinct_column is not None and not SAFE_IDENTIFIER.match(distinct_column):
        raise HTTPException(
            status_code=400,
            detail="distinct_column must contain only letters, digits, and underscores.",
        )
    if sort_by_column is not None and not SAFE_IDENTIFIER.match(sort_by_column):
        raise HTTPException(
            status_code=400,
            detail="sort_by_column must contain only letters, digits, and underscores.",
        )
    if sort_order is not None and sort_order.upper() not in {"ASC", "DESC"}:
        raise HTTPException(status_code=400, detail="sort_order must be 'asc' or 'desc'.")
    if sort_order is not None and sort_by_column is None:
        raise HTTPException(
            status_code=400,
            detail="sort_order requires sort_by_column to be specified.",
        )
    if limit < 1:
        raise HTTPException(status_code=400, detail="limit must be at least 1.")

    parsed_columns: list[str] = []
    if select_columns is not None:
        parsed_columns = [c.strip() for c in select_columns.split(",") if c.strip()]
        if not parsed_columns:
            raise HTTPException(status_code=400, detail="select_columns cannot be empty.")
        for col in parsed_columns:
            if not SAFE_IDENTIFIER.match(col):
                raise HTTPException(
                    status_code=400,
                    detail=f"Column '{col}' in select_columns contains invalid characters.",
                )

    effective_limit = limit

    try:
        conn = get_connection(settings)
    except pyodbc.Error as exc:
        logger.exception("DB connection error in GET /query")
        notify_db_error(notifier, "GET /query", exc)
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

        if distinct_column is not None:
            parts = [
                f"SELECT DISTINCT TOP (?) [{distinct_column}]",
                f"FROM [{view_name}]",
                f"WHERE [{distinct_column}] IS NOT NULL",
            ]
            params: list = [effective_limit]
            if filter_by_column is not None and filter_value is not None:
                parts.append(f"AND [{filter_by_column}] = ?")
                params.append(filter_value)
            parts.append(f"ORDER BY [{distinct_column}]")
        else:
            col_clause = ", ".join(f"[{c}]" for c in parsed_columns) if parsed_columns else "*"
            parts = [f"SELECT TOP (?) {col_clause} FROM [{view_name}]"]
            params = [effective_limit]
            if filter_by_column is not None and filter_value is not None:
                parts.append(f"WHERE [{filter_by_column}] = ?")
                params.append(filter_value)
            if sort_by_column is not None:
                order = (sort_order or "ASC").upper()
                parts.append(f"ORDER BY [{sort_by_column}] {order}")
            else:
                # Without ORDER BY, SQL Server can return rows in a different
                # scan order on repeated calls. ORDER BY (SELECT NULL) forces a
                # stable order so Glean gets consistent results across pages.
                parts.append("ORDER BY (SELECT NULL)")

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
        logger.exception("DB error in GET /query")
        notify_db_error(notifier, "GET /query", exc)
        raise HTTPException(
            status_code=500, detail="Database error. Please try again later."
        ) from exc
    finally:
        conn.close()
