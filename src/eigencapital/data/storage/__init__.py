"""Storage package — format policy and dataset persistence."""

from eigencapital.data.storage.policy import (
    DatasetStore,
    StorageEngineUnavailableError,
    StorageFormat,
    StorageRecommendation,
    dataset_is_numeric_only,
    detect_engines,
    profile_columns,
    raw_records_to_rows,
    recommend_format,
)

__all__ = [
    "DatasetStore",
    "StorageEngineUnavailableError",
    "StorageFormat",
    "StorageRecommendation",
    "dataset_is_numeric_only",
    "detect_engines",
    "profile_columns",
    "raw_records_to_rows",
    "recommend_format",
]
