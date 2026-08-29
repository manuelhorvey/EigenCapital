"""Common schemas — shared response models for the dashboard API."""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class DataFreshness(str, Enum):
    """Data freshness indicator."""

    LIVE = "LIVE"
    STALE = "STALE"
    UNKNOWN = "UNKNOWN"


class ResponseMeta(BaseModel):
    """Metadata for all API responses."""

    timestamp: datetime = Field(description="Response generation timestamp")
    freshness: DataFreshness = Field(description="Data freshness indicator")
    source: str = Field(description="Data source identifier")
    latency_ms: float | None = Field(default=None, description="Source query latency in ms")


class PaginatedResponse(BaseModel):
    """Paginated list response."""

    items: list[Any] = Field(description="List of items")
    total: int = Field(description="Total number of items")
    page: int = Field(description="Current page number")
    page_size: int = Field(description="Items per page")
    has_more: bool = Field(description="Whether more pages exist")


class ErrorResponse(BaseModel):
    """Error response."""

    error: str = Field(description="Error message")
    detail: str | None = Field(default=None, description="Error detail")
    timestamp: datetime = Field(description="Error timestamp")
