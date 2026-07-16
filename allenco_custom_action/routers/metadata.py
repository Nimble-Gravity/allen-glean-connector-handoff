"""GET /metadata — explore DB schema (views and columns)."""

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
from schemas import ColumnInfo, MetadataResponse
from settings import DbSettings
from validators import SAFE_IDENTIFIER

logger = logging.getLogger(__name__)
router = APIRouter(tags=["metadata"])


@router.get("/metadata", response_model=MetadataResponse)
def get_metadata(
    user_email: str,
    show_all_views: bool = False,
    show_view_columns: str | None = None,
    settings: DbSettings = Depends(get_db_settings),
    notifier: Notifier = Depends(get_notifier),
    view_perm_cache: dict[str, str] = Depends(get_view_perm_cache),
    superuser_emails: frozenset[str] = Depends(get_superuser_emails),
) -> MetadataResponse:
    if show_all_views and show_view_columns is not None:
        raise HTTPException(
            status_code=400,
            detail=(
                "show_all_views and show_view_columns are mutually exclusive — provide only one."
            ),
        )
    if not show_all_views and show_view_columns is None:
        raise HTTPException(
            status_code=400,
            detail=(
                "Provide show_all_views=true to list views, or "
                "show_view_columns=<view_name> to list columns."
            ),
        )
    if show_view_columns is not None and not SAFE_IDENTIFIER.match(show_view_columns):
        raise HTTPException(
            status_code=400,
            detail="show_view_columns must contain only letters, digits, and underscores.",
        )

    try:
        conn = get_connection(settings)
    except pyodbc.Error as exc:
        logger.exception("DB connection error in GET /metadata")
        notify_db_error(notifier, "GET /metadata", exc)
        raise HTTPException(
            status_code=500, detail="Database error. Please try again later."
        ) from exc

    try:
        if show_view_columns is not None and not check_user_has_view_access(
            user_email, show_view_columns, view_perm_cache, superuser_emails
        ):
            raise HTTPException(status_code=403, detail=PERMISSION_DENIED_MESSAGE)

        cursor = conn.cursor()

        if show_all_views:
            cursor.execute("SELECT TABLE_NAME FROM INFORMATION_SCHEMA.VIEWS ORDER BY TABLE_NAME")
            views = [row[0] for row in cursor.fetchall()]
            return MetadataResponse(user_email=user_email, views=views)

        cursor.execute(
            "SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE "
            "FROM INFORMATION_SCHEMA.COLUMNS "
            "WHERE TABLE_NAME = ? "
            "ORDER BY ORDINAL_POSITION",
            show_view_columns,
        )
        rows = cursor.fetchall()
        if not rows:
            raise HTTPException(
                status_code=404,
                detail=f"View '{show_view_columns}' not found or has no columns.",
            )
        columns = [ColumnInfo(column_name=r[0], data_type=r[1], is_nullable=r[2]) for r in rows]
        return MetadataResponse(user_email=user_email, view=show_view_columns, columns=columns)

    except HTTPException:
        raise
    except pyodbc.Error as exc:
        logger.exception("DB error in GET /metadata")
        notify_db_error(notifier, "GET /metadata", exc)
        raise HTTPException(
            status_code=500, detail="Database error. Please try again later."
        ) from exc
    finally:
        conn.close()
