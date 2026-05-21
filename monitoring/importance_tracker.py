from __future__ import annotations

import logging
import os
from dataclasses import dataclass, asdict
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
from scipy.stats import spearmanr

logger = logging.getLogger("quantforge.importance_tracker")

STABILITY_PENALTIES = {
    "jaccard_soft": (0.6, -0.10),
    "jaccard_hard": (0.4, -0.25),
    "spearman_soft": (0.7, -0.08),
    "spearman_hard": (0.5, -0.20),
}


@dataclass
class FeatureImportanceRecord:
    window_id: str
    asset: str
    train_start: str
    train_end: str
    feature: str
    importance_score: float
    rank: int
    model_type: str = "xgboost"
    logged_at: str = ""


@dataclass
class StabilityResult:
    asset: str
    window_id: str
    previous_window_id: str
    jaccard_top_10: float
    spearman_rank_corr: float
    n_union: int
    n_current_top10: int
    penalty: float
    timestamp: str


def compute_jaccard_top_n(
    current_features: list[dict],
    previous_features: list[dict],
    n: int = 10,
) -> float:
    current_top = {f["feature"] for f in sorted(current_features, key=lambda x: -x["importance_score"])[:n]}
    previous_top = {f["feature"] for f in sorted(previous_features, key=lambda x: -x["importance_score"])[:n]}
    union = current_top | previous_top
    if not union:
        return 1.0
    return len(current_top & previous_top) / len(union)


def compute_spearman_rank_corr(
    current_features: list[dict],
    previous_features: list[dict],
) -> float:
    current_map = {f["feature"]: f["rank"] for f in current_features}
    previous_map = {f["feature"]: f["rank"] for f in previous_features}
    common = set(current_map) & set(previous_map)
    if len(common) < 3:
        return 0.0
    cur_ranks = [current_map[f] for f in common]
    prev_ranks = [previous_map[f] for f in common]
    corr, _ = spearmanr(cur_ranks, prev_ranks)
    return float(corr) if not np.isnan(corr) else 0.0


def compute_stability_penalty(jaccard: float, spearman: float) -> float:
    penalty = 0.0
    thresholds = [
        ("jaccard_hard", jaccard, STABILITY_PENALTIES["jaccard_hard"]),
        ("jaccard_soft", jaccard, STABILITY_PENALTIES["jaccard_soft"]),
        ("spearman_hard", spearman, STABILITY_PENALTIES["spearman_hard"]),
        ("spearman_soft", spearman, STABILITY_PENALTIES["spearman_soft"]),
    ]
    for name, value, (threshold, p) in thresholds:
        if value < threshold:
            penalty = min(penalty, p)
            logger.debug("stability penalty triggered: %s (%.3f < %.2f, penalty=%.2f)", name, value, threshold, p)
    return penalty


class ImportanceStore:
    def __init__(self, base_dir: str):
        self.base_dir = base_dir
        self.path = os.path.join(base_dir, "data", "live", "importance_history.parquet")
        os.makedirs(os.path.dirname(self.path), exist_ok=True)

    def log_snapshot(
        self,
        asset: str,
        feature_names: list[str],
        importances: np.ndarray,
        window_id: str = "",
        train_start: str = "",
        train_end: str = "",
        model_type: str = "xgboost",
    ) -> None:
        if len(feature_names) != len(importances):
            logger.error("feature_names (%d) and importances (%d) length mismatch", len(feature_names), len(importances))
            return
        if len(feature_names) == 0:
            return
        ranked_idx = np.argsort(importances)[::-1]
        records = []
        now = datetime.utcnow().isoformat()
        for rank, idx in enumerate(ranked_idx):
            records.append(FeatureImportanceRecord(
                window_id=window_id,
                asset=asset,
                train_start=train_start,
                train_end=train_end,
                feature=feature_names[idx],
                importance_score=float(importances[idx]),
                rank=rank + 1,
                model_type=model_type,
                logged_at=now,
            ))
        df = pd.DataFrame([asdict(r) for r in records])
        if os.path.exists(self.path) and os.path.getsize(self.path) > 0:
            try:
                existing = pd.read_parquet(self.path)
                df = pd.concat([existing, df], ignore_index=True)
            except Exception:
                logger.warning("could not read existing importance history, overwriting")
        df.to_parquet(self.path)
        logger.info("logged %d feature importances for %s (window=%s)", len(records), asset, window_id)

    def load_history(self, asset: Optional[str] = None) -> pd.DataFrame:
        if not os.path.exists(self.path):
            return pd.DataFrame()
        try:
            df = pd.read_parquet(self.path)
            if asset is not None:
                df = df[df["asset"] == asset]
            return df
        except Exception as e:
            logger.warning("failed to load importance history: %s", e)
            return pd.DataFrame()

    def get_latest_two_snapshots(self, asset: str) -> tuple[Optional[pd.DataFrame], Optional[pd.DataFrame]]:
        """Return (latest_snapshot_df, previous_snapshot_df) for the given asset."""
        df = self.load_history(asset)
        if df.empty:
            return None, None
        window_ids = df["window_id"].dropna().unique()
        if len(window_ids) < 1:
            return None, None
        sorted_windows = sorted(window_ids)
        latest_wid = sorted_windows[-1]
        latest = df[df["window_id"] == latest_wid]
        if len(sorted_windows) < 2:
            return latest, None
        prev_wid = sorted_windows[-2]
        prev = df[df["window_id"] == prev_wid]
        return latest, prev

    def compute_stability(self, asset: str) -> Optional[StabilityResult]:
        latest_df, prev_df = self.get_latest_two_snapshots(asset)
        if latest_df is None or prev_df is None:
            return None
        latest_records = latest_df.to_dict("records")
        prev_records = prev_df.to_dict("records")
        latest_wid = latest_df["window_id"].iloc[0]
        prev_wid = prev_df["window_id"].iloc[0]
        jaccard = compute_jaccard_top_n(latest_records, prev_records, n=10)
        spearman = compute_spearman_rank_corr(latest_records, prev_records)
        penalty = compute_stability_penalty(jaccard, spearman)
        n_union = len(set(f["feature"] for f in latest_records) | set(f["feature"] for f in prev_records))
        return StabilityResult(
            asset=asset,
            window_id=str(latest_wid),
            previous_window_id=str(prev_wid),
            jaccard_top_10=round(jaccard, 4),
            spearman_rank_corr=round(spearman, 4),
            n_union=n_union,
            n_current_top10=10,
            penalty=round(penalty, 4),
            timestamp=datetime.utcnow().isoformat(),
        )
