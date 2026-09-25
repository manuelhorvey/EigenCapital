"""Merged D1 dataset loader with manifest verification (data contract).

Never writes to data/mt5/. Frozen R5 files are read-only; supplement and
candidate files carry their own frozen manifests. All loads fail loudly on
manifest mismatch — no silent data substitution.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from pathlib import Path

import pandas as pd

from research.volatility import config as C

OHLC = ["open", "high", "low", "close"]


class DataIntegrityError(RuntimeError):
    """Raised when a data-contract invariant is violated."""


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        h.update(fh.read())
    return h.hexdigest()


def _combined_hash(paths: list[Path]) -> str:
    h = hashlib.sha256()
    for p in sorted(paths, key=lambda x: x.name):
        h.update(_sha256_file(p).encode())
    return h.hexdigest()


def verify_manifest(manifest_path: Path) -> dict:
    """Recompute a frozen manifest's combined hash; raise on mismatch."""
    with open(manifest_path) as fh:
        m = json.load(fh)
    paths = [manifest_path.parent / name for name in m["per_file"]]
    missing = [p.name for p in paths if not p.is_file()]
    if missing:
        raise DataIntegrityError(f"{manifest_path.name}: missing files {missing}")
    recomputed = _combined_hash(paths)
    if recomputed != m["combined_sha256"]:
        raise DataIntegrityError(
            f"{manifest_path.name}: combined hash mismatch (frozen {m['combined_sha256'][:16]} != {recomputed[:16]})"
        )
    return m


def verify_r5_frozen_snapshot() -> None:
    """Byte-verify data/mt5 against the frozen R5 pre-registration manifest."""
    with open(C.FROZEN_MANIFEST) as fh:
        frozen = json.load(fh)
    paths = [C.FROZEN_DIR / n for n in frozen["per_file_prefixes"]]
    missing = [p.name for p in paths if not p.is_file()]
    if missing:
        raise DataIntegrityError(f"R5 snapshot missing files: {missing}")
    # Per-file prefixes (cheap tamper check on every frozen file).
    for p in paths:
        prefix = _sha256_file(p)[:12]
        expected = frozen["per_file_prefixes"][p.name]
        if prefix != expected:
            raise DataIntegrityError(f"R5 file hash prefix mismatch: {p.name}")
    # Full combined hash over ALL *_D1.csv in the directory (r5_executor rule).
    h = hashlib.sha256()
    for name in sorted(C.FROZEN_DIR.iterdir(), key=lambda x: x.name):
        if name.name.endswith("_D1.csv"):
            h.update(_sha256_file(name).encode())
    if h.hexdigest() != frozen["combined_sha256"]:
        raise DataIntegrityError("R5 combined_sha256 mismatch (extra/changed files in data/mt5)")


def _validate_frame(df: pd.DataFrame, stem: str) -> pd.DataFrame:
    if not df.index.is_monotonic_increasing:
        raise DataIntegrityError(f"{stem}: timestamps not monotonic")
    if df.index.has_duplicates:
        raise DataIntegrityError(f"{stem}: duplicate timestamps")
    if (df[OHLC] <= 0).any().any():
        raise DataIntegrityError(f"{stem}: non-positive prices")
    hi_ok = df["high"] >= df[OHLC].max(axis=1) - 1e-12
    lo_ok = df["low"] <= df[OHLC].min(axis=1) + 1e-12
    if not (hi_ok.all() and lo_ok.all()):
        raise DataIntegrityError(f"{stem}: OHLC invariant violated")
    if df[OHLC].isna().any().any():
        raise DataIntegrityError(f"{stem}: NaN prices")
    return df


def _load_stem(stem: str) -> pd.DataFrame | None:
    for directory in (C.FROZEN_DIR, C.SUPPLEMENT_DIR, C.CANDIDATE_DIR):
        path = directory / f"{stem}_D1.csv"
        if path.is_file():
            df = pd.read_csv(path, parse_dates=["time"])
            df = df.rename(columns={df.columns[0]: "time"}).set_index("time").sort_index()
            # Declared-UTC convention: files are tz-naive daily dates (documented).
            df.index.name = "time"
            keep = [c for c in OHLC + ["tick_volume", "spread", "real_volume"] if c in df.columns]
            return _validate_frame(df[keep], stem)
    return None


@dataclass(frozen=True)
class DatasetBundle:
    """Verified OHLCV frames keyed by baseline asset name (+ candidates)."""

    baseline: dict[str, pd.DataFrame]
    candidates: dict[str, pd.DataFrame]
    manifest_hashes: dict[str, str]
    load_warnings: tuple[str, ...]

    @property
    def combined_window(self) -> tuple[pd.Timestamp, pd.Timestamp]:
        starts = [df.index.min() for df in self.baseline.values()]
        ends = [df.index.max() for df in self.baseline.values()]
        return max(starts), min(ends)


def load_dataset(verify: bool = True) -> DatasetBundle:
    """Load and verify the full research dataset.

    Order of trust:
      1. data/mt5 frozen R5 files (12 baseline + USOIL candidate)
      2. data/taxonomy_d1 supplement (22 baseline) — own frozen manifest
      3. data/candidates (Copper) — own frozen manifest, separate provider
    """
    if verify:
        verify_r5_frozen_snapshot()
        verify_manifest(C.SUPPLEMENT_MANIFEST)
        verify_manifest(C.CANDIDATE_MANIFEST)

    warnings: list[str] = []
    baseline: dict[str, pd.DataFrame] = {}
    for asset in C.BASELINE_ASSETS:
        df = _load_stem(C.CSV_STEMS[asset])
        if df is None:
            raise DataIntegrityError(f"baseline asset missing local D1 data: {asset}")
        baseline[asset] = df

    candidates: dict[str, pd.DataFrame] = {}
    for asset in C.CANDIDATE_ASSETS:
        df = _load_stem(C.CSV_STEMS[asset])
        if df is None:
            warnings.append(f"candidate missing local D1 data: {asset}")
            continue
        candidates[asset] = df

    manifest_hashes = {
        "r5": json.load(open(C.FROZEN_MANIFEST))["combined_sha256"],
        "supplement": json.load(open(C.SUPPLEMENT_MANIFEST))["combined_sha256"],
        "candidates": json.load(open(C.CANDIDATE_MANIFEST))["combined_sha256"],
    }

    # Documented coverage caveats (explicit, not silent).
    for asset, df in baseline.items():
        if df.index.min() > pd.Timestamp(C.PRIMARY_START):
            warnings.append(f"{asset}: history starts {df.index.min().date()} after primary window start")

    return DatasetBundle(
        baseline=baseline,
        candidates=candidates,
        manifest_hashes=manifest_hashes,
        load_warnings=tuple(warnings),
    )


def window(df: pd.DataFrame, start: str, end: str) -> pd.DataFrame:
    return df.loc[pd.Timestamp(start) : pd.Timestamp(end)]


def integrity_report(bundle: DatasetBundle) -> dict:
    rows = {}
    for name, df in {**bundle.baseline, **bundle.candidates}.items():
        rows[name] = {
            "rows": int(len(df)),
            "first": str(df.index.min().date()),
            "last": str(df.index.max().date()),
            "n_missing_dates_vs_union": None,
            "dupes": int(df.index.duplicated().sum()),
            "ohlc_ok": True,  # enforced at load
            "stale_flat_bars": int((df["high"] == df["low"]).sum()),
        }
    return {"assets": rows, "warnings": list(bundle.load_warnings)}
