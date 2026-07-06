"""Simulation snapshot system — capture-and-replay for paper trading.

Snapshots capture full engine state at each save point, enabling
deterministic replay from any historical date with full feature
and model state reconstruction.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
from dataclasses import asdict, dataclass, field

import pandas as pd

from eigencapital.domain.encoding import EigenCapitalJSONEncoder

logger = logging.getLogger("eigencapital.simulation_snapshot")

SNAPSHOT_DIR = "data/live/snapshots"
SNAPSHOT_FILE = "simulation_history.parquet"
COLD_STATE_FILE = "cold_state.json"
CHECKSUM_EXT = ".sha256"


def _write_checksum(path: str) -> None:
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(65536)
            if not block:
                break
            sha.update(block)
    checksum_path = path + CHECKSUM_EXT
    with open(checksum_path, "w") as f:
        f.write(sha.hexdigest())


def _coerce_json_list(value) -> list:
    """Read-side adapter for ``trade_log`` / ``prob_history``.

    Captured snapshots now persist these columns as JSON strings (so
    pyarrow round-trips them safely without spurious type inference).
    On read we deserialize; on bad data we fall back to an empty list.
    """
    if value is None or value is pd.NA:
        return []
    if isinstance(value, list):
        return value
    if isinstance(value, str):
        if not value:
            return []
        try:
            parsed = json.loads(value)
        except (ValueError, TypeError):
            return []
        return parsed if isinstance(parsed, list) else []
    return []


def _verify_checksum(path: str) -> bool:
    checksum_path = path + CHECKSUM_EXT
    if not os.path.exists(checksum_path):
        logger.warning("no checksum sidecar at %s — tamper detection unavailable", checksum_path)
        return True
    sha = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            block = f.read(65536)
            if not block:
                break
            sha.update(block)
    with open(checksum_path) as f:
        expected = f.read().strip()
    if sha.hexdigest() != expected:
        logger.warning("cold_state.json checksum MISMATCH — possible tampering")
        return False
    return True


@dataclass
class AssetSnapshot:
    asset: str
    timestamp: str
    current_value: float
    peak_value: float
    initial_capital: float
    position_side: str | None
    position_entry: float | None
    position_sl: float | None
    position_tp: float | None
    position_entry_date: str | None
    position_vol: float | None
    n_trades: int
    n_signals: int
    trade_log: list = field(default_factory=list)
    prob_history: list = field(default_factory=list)
    last_signal: str | None = None
    last_confidence: float | None = None
    last_close_price: float | None = None
    last_prob_long: float | None = None
    last_prob_short: float | None = None
    validity_state: str = "YELLOW"
    validity_exposure: float = 1.0
    meta_confidence: float | None = None
    meta_decision: str | None = None
    feature_stability_jaccard: float | None = None
    feature_stability_spearman: float | None = None


@dataclass
class PortfolioSnapshot:
    timestamp: str
    portfolio_value: float
    total_return: float
    cash_buffer: float
    assets: dict[str, AssetSnapshot] = field(default_factory=dict)


class SimulationStore:
    """Manages simulation snapshot persistence and replay."""

    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.snapshot_dir = os.path.join(base_dir, SNAPSHOT_DIR)
        self.snapshot_path = os.path.join(self.snapshot_dir, SNAPSHOT_FILE)
        self.cold_state_path = os.path.join(self.snapshot_dir, COLD_STATE_FILE)
        os.makedirs(self.snapshot_dir, exist_ok=True)

    def capture(
        self,
        portfolio_value: float,
        total_return: float,
        cash_buffer: float,
        asset_snapshots: list[AssetSnapshot],
        cold_state: dict | None = None,
    ) -> None:
        """Save a simulation snapshot row for each asset."""
        if not asset_snapshots:
            return
        ts = asset_snapshots[0].timestamp
        rows = []
        for a in asset_snapshots:
            rows.append(asdict(a))

        ps = PortfolioSnapshot(
            timestamp=ts,
            portfolio_value=portfolio_value,
            total_return=total_return,
            cash_buffer=cash_buffer,
        )
        rows.append(
            {
                "_meta": "portfolio",
                "asset": "__portfolio__",
                "timestamp": ps.timestamp,
                "portfolio_value": ps.portfolio_value,
                "total_return": ps.total_return,
                "cash_buffer": ps.cash_buffer,
                "satellite_value": 0.0,
                "current_value": 0.0,
                "peak_value": 0.0,
                "initial_capital": 0.0,
                "position_side": None,
                "position_entry": None,
                "position_sl": None,
                "position_tp": None,
                "position_entry_date": None,
                "position_vol": None,
                "n_trades": 0,
                "n_signals": 0,
                "trade_log": [],
                "prob_history": [],
            }
        )

        df = pd.DataFrame(rows)
        # Stringify object-typed list columns to JSON for pyarrow compatibility.
        # `trade_log` and `prob_history` are lists with mixed scalar/object nesting
        # — pyarrow's strict object inference mis-classifies them as bytes at
        # round-trip time. JSON strings are the safest representation.
        for col in ("trade_log", "prob_history"):
            df[col] = df[col].apply(lambda v: json.dumps(v, cls=EigenCapitalJSONEncoder) if not isinstance(v, str) else v)
        if os.path.exists(self.snapshot_path) and os.path.getsize(self.snapshot_path) > 0:
            try:
                existing = pd.read_parquet(self.snapshot_path)
                # Deduplicate: remove any existing row for same timestamp + asset
                mask = ~(
                    (existing["timestamp"] == ts)
                    & (existing["asset"].isin([a.asset for a in asset_snapshots] + ["__portfolio__"]))
                )
                existing = existing[mask]
                df = pd.concat([existing, df], ignore_index=True)
            except (ValueError, TypeError, OSError, pd.errors.EmptyDataError):
                logger.debug("snapshot dedup failed — starting fresh")
        df.to_parquet(self.snapshot_path)
        logger.debug("snapshot captured: %s, %d assets", ts, len(asset_snapshots))

        # Persist cold state (model paths, etc.)
        if cold_state is not None:
            try:
                with open(self.cold_state_path, "w") as f:
                    json.dump(cold_state, f, cls=EigenCapitalJSONEncoder)
                _write_checksum(self.cold_state_path)
            except (OSError, TypeError, json.JSONDecodeError) as e:
                logger.warning("failed to persist cold state: %s", e)

    def load_cold_state(self) -> dict | None:
        if not os.path.exists(self.cold_state_path):
            return None
        _verify_checksum(self.cold_state_path)
        try:
            with open(self.cold_state_path) as f:
                return json.load(f)
        except (OSError, json.JSONDecodeError) as e:
            logger.warning("failed to load cold state: %s", e)
            return None

    def load_snapshot(self, timestamp: str) -> PortfolioSnapshot | None:
        """Load a complete portfolio snapshot for a given date."""
        if not os.path.exists(self.snapshot_path):
            return None
        try:
            df = pd.read_parquet(self.snapshot_path)
        except (ValueError, TypeError, OSError, pd.errors.EmptyDataError) as e:
            logger.warning("failed to read snapshot history: %s", e)
            return None

        rows = df[df["timestamp"] == timestamp]
        if rows.empty:
            return None

        portfolio_row = rows[rows["asset"] == "__portfolio__"]
        asset_rows = rows[rows["asset"] != "__portfolio__"]

        ps = PortfolioSnapshot(
            timestamp=timestamp,
            portfolio_value=float(portfolio_row.iloc[0]["portfolio_value"]) if not portfolio_row.empty else 0.0,
            total_return=float(portfolio_row.iloc[0]["total_return"]) if not portfolio_row.empty else 0.0,
            cash_buffer=float(portfolio_row.iloc[0]["cash_buffer"]) if not portfolio_row.empty else 0.0,
        )

        for _, row in asset_rows.iterrows():
            a = AssetSnapshot(
                asset=str(row["asset"]),
                timestamp=str(row["timestamp"]),
                current_value=float(row["current_value"]),
                peak_value=float(row["peak_value"]),
                initial_capital=float(row["initial_capital"]),
                position_side=str(row["position_side"]) if pd.notna(row.get("position_side")) else None,
                position_entry=float(row["position_entry"]) if pd.notna(row.get("position_entry")) else None,
                position_sl=float(row["position_sl"]) if pd.notna(row.get("position_sl")) else None,
                position_tp=float(row["position_tp"]) if pd.notna(row.get("position_tp")) else None,
                position_entry_date=str(row["position_entry_date"])
                if pd.notna(row.get("position_entry_date"))
                else None,
                position_vol=float(row["position_vol"]) if pd.notna(row.get("position_vol")) else None,
                n_trades=int(row["n_trades"]),
                n_signals=int(row["n_signals"]),
                trade_log=_coerce_json_list(row.get("trade_log")),
                prob_history=_coerce_json_list(row.get("prob_history")),
                last_signal=str(row["last_signal"]) if pd.notna(row.get("last_signal")) else None,
                last_confidence=float(row["last_confidence"]) if pd.notna(row.get("last_confidence")) else None,
                last_close_price=float(row["last_close_price"]) if pd.notna(row.get("last_close_price")) else None,
                last_prob_long=float(row["last_prob_long"]) if pd.notna(row.get("last_prob_long")) else None,
                last_prob_short=float(row["last_prob_short"]) if pd.notna(row.get("last_prob_short")) else None,
                validity_state=str(row["validity_state"]) if pd.notna(row.get("validity_state")) else "YELLOW",
                validity_exposure=float(row["validity_exposure"]) if pd.notna(row.get("validity_exposure")) else 1.0,
                meta_confidence=float(row["meta_confidence"]) if pd.notna(row.get("meta_confidence")) else None,
                meta_decision=str(row["meta_decision"]) if pd.notna(row.get("meta_decision")) else None,
                feature_stability_jaccard=float(row["feature_stability_jaccard"])
                if pd.notna(row.get("feature_stability_jaccard"))
                else None,
                feature_stability_spearman=float(row["feature_stability_spearman"])
                if pd.notna(row.get("feature_stability_spearman"))
                else None,
            )
            ps.assets[a.asset] = a

        return ps

    def load_snapshot_by_date(self, date_str: str) -> PortfolioSnapshot | None:
        """Load the latest snapshot for a given date (YYYY-MM-DD)."""
        if not os.path.exists(self.snapshot_path):
            return None
        try:
            df = pd.read_parquet(self.snapshot_path)
        except (ValueError, TypeError, pd.errors.EmptyDataError):
            return None

        matching = df[df["timestamp"].str.startswith(date_str)]
        if matching.empty:
            return None
        # Get the latest timestamp for this date
        latest_ts = sorted(matching["timestamp"].unique())[-1]
        return self.load_snapshot(latest_ts)

    def list_snapshot_dates(self) -> list[str]:
        """Return all unique snapshot dates, sorted."""
        if not os.path.exists(self.snapshot_path):
            return []
        try:
            df = pd.read_parquet(self.snapshot_path)
            if df.empty:
                return []
            return sorted(df["timestamp"].unique())
        except (ValueError, TypeError, pd.errors.EmptyDataError):
            return []


def build_asset_snapshot(
    asset_name: str,
    metrics: dict,
    validity_state: str,
    validity_exposure: float,
    meta_inference: dict | None,
    feature_stability: dict | None,
    timestamp: str,
) -> AssetSnapshot:
    """Build an AssetSnapshot from an asset's runtime state."""
    position = metrics.get("position")
    prob = metrics.get("prob_history", [])
    last_sig = prob[-1] if prob else None
    return AssetSnapshot(
        asset=asset_name,
        timestamp=timestamp,
        current_value=metrics.get("current_value", 0.0),
        peak_value=metrics.get("peak_value", 0.0),
        initial_capital=metrics.get("initial_capital", metrics.get("current_value", 0.0)),
        position_side=position.get("side") if position else None,
        position_entry=position.get("entry") if position else None,
        position_sl=position.get("sl") if position else None,
        position_tp=position.get("tp") if position else None,
        position_entry_date=position.get("entry_date") if position else None,
        position_vol=position.get("current_vol") if position else None,
        n_trades=metrics.get("n_trades", 0),
        n_signals=metrics.get("n_signals", 0),
        trade_log=metrics.get("trade_log", []),
        prob_history=prob,
        last_signal=last_sig.get("signal") if last_sig else None,
        last_confidence=last_sig.get("confidence") if last_sig else None,
        last_close_price=last_sig.get("close_price") if last_sig else None,
        last_prob_long=last_sig.get("prob_long") if last_sig else None,
        last_prob_short=last_sig.get("prob_short") if last_sig else None,
        validity_state=validity_state,
        validity_exposure=validity_exposure,
        meta_confidence=meta_inference.get("meta_confidence") if meta_inference else None,
        meta_decision=meta_inference.get("meta_decision") if meta_inference else None,
        feature_stability_jaccard=feature_stability.get("jaccard_top_10") if feature_stability else None,
        feature_stability_spearman=feature_stability.get("spearman_rank_corr") if feature_stability else None,
    )
