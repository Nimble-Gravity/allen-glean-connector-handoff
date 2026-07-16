"""Pydantic response models for the Custom Action API."""

from typing import Any

from pydantic import BaseModel


class ColumnInfo(BaseModel):
    column_name: str
    data_type: str
    is_nullable: str


class MetadataResponse(BaseModel):
    user_email: str
    views: list[str] | None = None
    view: str | None = None
    columns: list[ColumnInfo] | None = None


class QueryResponse(BaseModel):
    data: list[dict[str, Any]]
    row_count: int
