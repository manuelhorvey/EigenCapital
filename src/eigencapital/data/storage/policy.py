"""Dataset storage — format selection and optional-engine adapters.

Storage guidance (Jansen 2020, Ch. 2 "Efficient data storage"):
- Pure numeric series are fastest in HDF5.
- Mixed numeric/text datasets read/write best as Parquet.
- CSV is the universal fallback.

EigenCapital keeps its runtime dependency-free: the policy layer is pure
standard library, and engine-backed writers (Parquet via pyarrow or
fastparquet, HDF5 via PyTables) activate only when the corresponding
packages are importable. A requested-but-unavailable engine raises
StorageEngineUnavailableError with install guidance — never a silent
downgrade to CSV.

Usage:
    store = DatasetStore("data/normalized")          # auto format
    path = store.save("es_bars", records)
    records = store.load("es_bars")
"""

from __future__ import annotations

import csv
import json
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Dict, List, Sequence

from eigencapital.data.loaders.base import RawRecord


class StorageFormat(str, Enum):
    """Supported on-disk dataset formats."""

    CSV = "csv"
    PARQUET = "parquet"
    HDF5 = "hdf5"


class StorageEngineUnavailableError(RuntimeError):
    """Raised when a requested format lacks its optional engine."""

    def __init__(self, fmt: StorageFormat) -> None:
        guidance = {
            StorageFormat.PARQUET: ("pip install pandas pyarrow  (or fastparquet)"),
            StorageFormat.HDF5: "pip install pandas tables",
        }[fmt]
        super().__init__(
            f"Storage engine unavailable for {fmt.value}. Install it with: "
            f"{guidance}. EigenCapital keeps these engines optional; the "
            f"policy layer recommends formats independently of availability."
        )
        self.format = fmt


def _importable(module: str) -> bool:
    """Return True if `module` can be imported."""
    try:
        __import__(module)
        return True
    except ImportError:
        return False


def detect_engines() -> Dict[str, bool]:
    """Probe optional storage engines without importing them eagerly.

    Returns:
        Mapping of engine name → availability:
        pandas, pyarrow, fastparquet (Parquet); tables (HDF5)
    """
    return {
        "pandas": _importable("pandas"),
        "pyarrow": _importable("pyarrow"),
        "fastparquet": _importable("fastparquet"),
        "tables": _importable("tables"),
    }


@dataclass(frozen=True)
class StorageRecommendation:
    """A format choice with rationale and ordered fallbacks.

    Attributes:
        preferred: Recommended format given profile and engines
        fallbacks: Ordered alternatives if preferred write fails
        reason: Why this format was chosen (auditable provenance)
    """

    preferred: StorageFormat
    fallbacks: tuple = ()
    reason: str = ""

    def to_dict(self) -> Dict[str, Any]:
        """Deterministic serialization."""
        return {
            "preferred": StorageFormat(self.preferred).value,
            "fallbacks": [StorageFormat(f).value for f in self.fallbacks],
            "reason": self.reason,
        }


def recommend_format(
    numeric_only: bool,
    engines: Dict[str, bool] | None = None,
) -> StorageRecommendation:
    """Select the storage format for a dataset profile.

    Policy (book guidance, dependency-aware):
        numeric-only → HDF5 preferred, Parquet then CSV behind it
        mixed types  → Parquet preferred, HDF5 then CSV behind it
        missing engines degrade to the next candidate that is fully
        available; CSV is always available (stdlib).

    Args:
        numeric_only: Whether every column is purely numeric
        engines: Availability map (defaults to detect_engines())

    Returns:
        StorageRecommendation with preferred format and rationale
    """
    if engines is None:
        engines = detect_engines()
    parquet_ok = engines.get("pandas", False) and (engines.get("pyarrow", False) or engines.get("fastparquet", False))
    hdf5_ok = engines.get("pandas", False) and engines.get("tables", False)

    if numeric_only:
        ranked = [
            (StorageFormat.HDF5, hdf5_ok),
            (StorageFormat.PARQUET, parquet_ok),
            (StorageFormat.CSV, True),
        ]
        base_reason = "pure numeric series: HDF5 fastest per ML4T Ch.2"
    else:
        ranked = [
            (StorageFormat.PARQUET, parquet_ok),
            (StorageFormat.HDF5, hdf5_ok),
            (StorageFormat.CSV, True),
        ]
        base_reason = "mixed numeric/text columns: Parquet best per ML4T Ch.2"

    available = [(fmt, ok) for fmt, ok in ranked]
    preferred_index = next(i for i, (_, ok) in enumerate(available) if ok)
    preferred = available[preferred_index][0]
    fallbacks = tuple(fmt for fmt, ok in available[preferred_index + 1 :] if ok)
    degraded = preferred_index != 0
    reason = base_reason + ("" if not degraded else "; degraded because higher-ranked engines are unavailable")
    return StorageRecommendation(
        preferred=preferred,
        fallbacks=fallbacks,
        reason=reason,
    )


def profile_columns(records: Sequence[Dict[str, Any]]) -> Dict[str, bool]:
    """Classify each column as numeric-only.

    None/missing values are ignored for classification. A column is
    numeric-only when every observed value is int/float (bool excluded).
    Columns with no observations classify as numeric (vacuous).

    Args:
        records: Row dicts

    Returns:
        Mapping column name → numeric_only flag
    """
    observed_numeric: Dict[str, bool] = {}
    for record in records:
        for key, value in record.items():
            if value is None:
                continue
            is_num = isinstance(value, (int, float)) and not isinstance(value, bool)
            if key not in observed_numeric:
                observed_numeric[key] = is_num
            else:
                observed_numeric[key] = observed_numeric[key] and is_num
    return observed_numeric


def dataset_is_numeric_only(records: Sequence[Dict[str, Any]]) -> bool:
    """True when all columns of the dataset are numeric-only."""
    return all(profile_columns(records).values())


class DatasetStore:
    """Save/load row-dict datasets under a managed directory.

    Format selection follows recommend_format(); an explicit format may
    be forced, in which case an unavailable engine raises rather than
    silently degrading.
    """

    def __init__(self, base_path: str | Path, fmt: StorageFormat | None = None) -> None:
        self.base_path = Path(base_path)
        self.base_path.mkdir(parents=True, exist_ok=True)
        self._forced_format = fmt

    def _path(self, name: str, fmt: StorageFormat) -> Path:
        suffix = {"csv": ".csv", "parquet": ".parquet", "hdf5": ".h5"}[fmt.value]
        return self.base_path / f"{name}{suffix}"

    def select_format(self, records: Sequence[Dict[str, Any]]) -> StorageRecommendation:
        """Resolve the format for a dataset, honoring any forced choice."""
        recommendation = recommend_format(dataset_is_numeric_only(records))
        if self._forced_format is None:
            return recommendation
        if self._forced_format == recommendation.preferred:
            return recommendation
        forced_reason = f"forced by caller (policy would choose {recommendation.preferred.value})"
        return StorageRecommendation(
            preferred=self._forced_format,
            fallbacks=(recommendation.preferred,) + recommendation.fallbacks,
            reason=forced_reason,
        )

    def save(
        self,
        name: str,
        records: Sequence[Dict[str, Any]],
        metadata: Dict[str, Any] | None = None,
    ) -> Path:
        """Persist rows under the resolved format; returns the file path.

        Sidecar JSON metadata (<name>.meta.json) records format,
        rationale, row count, and caller-supplied metadata for lineage.
        """
        if not records:
            raise ValueError("refusing to save empty dataset")
        recommendation = self.select_format(records)
        fmt = recommendation.preferred
        path = self._path(name, fmt)

        if fmt == StorageFormat.CSV:
            self._save_csv(path, records)
        elif fmt == StorageFormat.PARQUET:
            self._save_parquet(path, records)
        elif fmt == StorageFormat.HDF5:
            self._save_hdf5(path, name, records)

        meta = {
            "dataset": name,
            "format": fmt.value,
            "reason": recommendation.reason,
            "rows": len(records),
            "columns": sorted({k for r in records for k in r}),
            "metadata": metadata or {},
        }
        with open(
            self.base_path / f"{name}.meta.json",
            "w",
            encoding="utf-8",
        ) as f:
            json.dump(meta, f, sort_keys=True, indent=2)
        return path

    def load(self, name: str) -> List[Dict[str, Any]]:
        """Load rows from whichever supported file exists for `name`."""
        for fmt in StorageFormat:
            path = self._path(name, fmt)
            if path.exists():
                if fmt == StorageFormat.CSV:
                    return self._load_csv(path)
                if fmt == StorageFormat.PARQUET:
                    return self._load_parquet(path)
                return self._load_hdf5(path)
        raise FileNotFoundError(f"No stored dataset named '{name}' in {self.base_path}")

    @staticmethod
    def _save_csv(path: Path, records: Sequence[Dict[str, Any]]) -> None:
        columns: List[str] = []
        for r in records:
            for k in r:
                if k not in columns:
                    columns.append(k)
        with open(path, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=columns)
            writer.writeheader()
            for r in records:
                writer.writerow({k: r.get(k, "") for k in columns})

    @staticmethod
    def _load_csv(path: Path) -> List[Dict[str, Any]]:
        with open(path, newline="", encoding="utf-8") as f:
            return list(csv.DictReader(f))

    @staticmethod
    def _require_pandas() -> Any:
        try:
            import pandas  # type: ignore[import-untyped]
        except ImportError as e:
            raise StorageEngineUnavailableError(StorageFormat.PARQUET) from e
        return pandas

    @classmethod
    def _save_parquet(cls, path: Path, records: Sequence[Dict[str, Any]]) -> None:
        engines = detect_engines()
        if not engines["pandas"] or not (engines["pyarrow"] or engines["fastparquet"]):
            raise StorageEngineUnavailableError(StorageFormat.PARQUET)
        cls._require_pandas().DataFrame(list(records)).to_parquet(path)

    @classmethod
    def _load_parquet(cls, path: Path) -> List[Dict[str, Any]]:
        cls._require_pandas()
        df = cls._require_pandas().read_parquet(path)
        return df.to_dict(orient="records")

    @classmethod
    def _save_hdf5(cls, path: Path, key: str, records: Sequence[Dict[str, Any]]) -> None:
        engines = detect_engines()
        if not engines["pandas"] or not engines["tables"]:
            raise StorageEngineUnavailableError(StorageFormat.HDF5)
        cls._require_pandas().DataFrame(list(records)).to_hdf(path, key=key, mode="w")

    @classmethod
    def _load_hdf5(cls, path: Path) -> List[Dict[str, Any]]:
        engines = detect_engines()
        if not engines["pandas"] or not engines["tables"]:
            raise StorageEngineUnavailableError(StorageFormat.HDF5)
        df = cls._require_pandas().read_hdf(path)
        return df.to_dict(orient="records")


def raw_records_to_rows(records: Sequence[RawRecord]) -> List[Dict[str, Any]]:
    """Flatten RawRecords into row dicts for storage."""
    return [
        {
            "source": r.source,
            "instrument_id": r.instrument_id,
            "timestamp": r.timestamp,
            **r.data,
        }
        for r in records
    ]
