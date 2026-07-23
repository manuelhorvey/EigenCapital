"""LabelForensicsEngine — orchestrate per-asset label forensic analysis."""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path
from typing import Any

import pandas as pd
import yaml

from labels.triple_barrier import apply_triple_barrier
from shared.volatility import VolatilityPrimitive
from research.label_forensics.distribution import LabelDistributionAnalyzer
from research.label_forensics.barriers import BarrierMechanicsAnalyzer
from research.label_forensics.drift import LabelDriftAnalyzer
from research.label_forensics.reporting import ForensicsReportBuilder

logger = logging.getLogger("eigencapital.label_forensics")

DATA_DIR = Path("data/yfinance_10yr")
CONFIG_PATH = Path("configs/domains/ml/triple_barrier.yaml")
VERTICAL_BARRIER = 20

ASSET_NAME_MAP: dict[str, str] = {
    "DJI": "^DJI",
    "BTC": "BTCUSD",
}

ACTIVE_ASSETS_20260723: set[str] = {
    "AUDJPY", "AUDUSD", "CADCHF", "EURAUD", "EURCAD", "EURCHF",
    "GBPCAD", "GBPCHF", "GBPUSD", "GC", "NZDCAD", "NZDCHF",
    "NZDUSD", "USDCAD", "USDCHF", "USDJPY", "DJI",
}


def _resolve_parquet_name(asset_key: str) -> str:
    return ASSET_NAME_MAP.get(asset_key, asset_key)


def _load_label_config() -> dict[str, Any]:
    with open(CONFIG_PATH) as f:
        cfg = yaml.safe_load(f)
    return cfg.get("assets", {})


def _load_ohlcv(asset_key: str) -> pd.DataFrame:
    parquet_name = _resolve_parquet_name(asset_key)
    path = DATA_DIR / f"{parquet_name}_ohlcv.parquet"
    if not path.exists():
        raise FileNotFoundError(f"OHLCV data not found: {path}")
    df = pd.read_parquet(path)
    df.index = pd.DatetimeIndex(df.index)
    df.index.name = "Date"
    required = {"close", "high", "low", "open"}
    missing = required - set(df.columns)
    if missing:
        raise ValueError(f"Missing columns {missing} in {path}")
    return df


def _build_vol_primitive(params: dict) -> VolatilityPrimitive | None:
    if params.get("vol_method") == "atr":
        period = int(params.get("atr_period", 14))
        return VolatilityPrimitive(period=period)
    return None


def apply_labels_and_compute_details(
    df: pd.DataFrame, pt_sl: list[float], vertical_barrier: int,
    vol_primitive: VolatilityPrimitive | None = None,
) -> pd.DataFrame:
    """Apply triple-barrier labels and augment with detailed hit mechanics.

    Returns a DataFrame with columns:
        close, label, hit_side, hit_bar, upper_dist_pct, lower_dist_pct,
        vol_at_label, forward_return
    where hit_side is 'upper' | 'lower' | 'timeout' | 'incomplete'.
    """
    import numpy as np
    from labels.triple_barrier import _ewm_vol
    from shared.volatility import compute_atr_pct

    # Compute target ONCE and align df — avoids length mismatch when
    # apply_triple_barrier re-computes EWM vol and drops NaN a second time.
    if vol_primitive is not None:
        target = compute_atr_pct(df, period=vol_primitive.period)
    else:
        target = _ewm_vol(df["close"])

    df = df.loc[target.index].copy()
    close = df["close"].values
    vol = target.values
    n = len(close)
    vb = vertical_barrier

    # Pass the pre-computed target so apply_triple_barrier does not recompute it
    labeled = apply_triple_barrier(
        df, pt_sl=list(pt_sl), target=target,
        vertical_barrier=vb, vol_primitive=vol_primitive,
    )
    labels = labeled["label"].values

    hit_side = np.full(n, "incomplete", dtype=object)
    hit_bar = np.full(n, -1, dtype=int)
    upper_dist_pct = np.zeros(n, dtype=float)
    lower_dist_pct = np.zeros(n, dtype=float)
    vol_at = np.zeros(n, dtype=float)
    fwd_return = np.zeros(n, dtype=float)

    if n <= vb:
        df_out = labeled.copy()
        df_out["hit_side"] = hit_side
        df_out["hit_bar"] = hit_bar
        df_out["upper_dist_pct"] = upper_dist_pct
        df_out["lower_dist_pct"] = lower_dist_pct
        df_out["vol_at_label"] = vol_at
        df_out["forward_return"] = fwd_return
        return df_out

    windows = np.lib.stride_tricks.sliding_window_view(close, vb + 1)
    curr = windows[:, 0]
    vol_slice = vol[: n - vb]
    upper = curr * (1.0 + vol_slice * pt_sl[0])
    lower = curr * (1.0 - vol_slice * pt_sl[1])
    future = windows[:, 1:]

    upper_dist_pct[: n - vb] = (upper - curr) / curr
    lower_dist_pct[: n - vb] = (curr - lower) / curr
    vol_at[: n - vb] = vol_slice
    fwd_return[: n - vb] = (future[:, -1] - curr) / curr  # return at vertical barrier

    hit_upper = np.argmax(future >= upper[:, None], axis=1)
    hit_lower = np.argmax(future <= lower[:, None], axis=1)

    no_upper = ~np.any(future >= upper[:, None], axis=1)
    no_lower = ~np.any(future <= lower[:, None], axis=1)
    hit_upper[no_upper] = vb
    hit_lower[no_lower] = vb

    upper_first = hit_upper < hit_lower
    lower_first = hit_lower < hit_upper

    hit_side[: n - vb] = "timeout"
    hit_bar[: n - vb] = vb
    hit_side[: n - vb][upper_first] = "upper"
    hit_bar[: n - vb][upper_first] = hit_upper[upper_first]
    hit_side[: n - vb][lower_first] = "lower"
    hit_bar[: n - vb][lower_first] = hit_lower[lower_first]

    hit_bar_f = hit_bar[: n - vb].copy()
    hit_bar_f[hit_bar_f >= vb] = -1
    fwd_return[: n - vb] = np.where(
        hit_side[: n - vb] == "upper",
        upper[: n - vb] / curr[: n - vb] - 1.0,
        np.where(
            hit_side[: n - vb] == "lower",
            lower[: n - vb] / curr[: n - vb] - 1.0,
            fwd_return[: n - vb],
        ),
    )

    df_out = labeled.copy()
    df_out["hit_side"] = pd.Series(hit_side, index=df_out.index)
    df_out["hit_bar"] = pd.Series(hit_bar, index=df_out.index)
    df_out["upper_dist_pct"] = pd.Series(upper_dist_pct, index=df_out.index)
    df_out["lower_dist_pct"] = pd.Series(lower_dist_pct, index=df_out.index)
    df_out["vol_at_label"] = pd.Series(vol_at, index=df_out.index)
    df_out["forward_return"] = pd.Series(fwd_return, index=df_out.index)
    return df_out


class LabelForensicsEngine:
    """Orchestrate per-asset label forensics analysis.

    Usage::

        engine = LabelForensicsEngine()
        report = engine.analyze_asset("EURCHF")
        portfolio = engine.analyze_all()
    """

    def __init__(self, config_path: str | Path = CONFIG_PATH, data_dir: str | Path = DATA_DIR):
        self.config_path = Path(config_path)
        self.data_dir = Path(data_dir)
        self._label_config = _load_label_config()
        self._analyzers = [
            ("label_distribution", LabelDistributionAnalyzer()),
            ("barrier_statistics", BarrierMechanicsAnalyzer()),
            ("label_drift", LabelDriftAnalyzer()),
        ]

    def analyze_asset(
        self, asset_key: str, run_counterfactual: bool = False,
    ) -> dict[str, Any]:
        """Run full forensic analysis for a single asset.

        Parameters
        ----------
        asset_key:
            Asset key from triple_barrier.yaml (e.g. ``"EURCHF"``, ``"DJI"``).
        run_counterfactual:
            If True, run counterfactual parameter sweeps (expensive).

        Returns
        -------
        dict
            Structured forensic report.
        """
        params = self._label_config.get(asset_key)
        if params is None:
            raise ValueError(f"Asset '{asset_key}' not found in label config")

        logger.info("Loading data for %s ...", asset_key)
        df = _load_ohlcv(asset_key)
        pt_sl = [float(params["pt"]), float(params["sl"])]
        vol_primitive = _build_vol_primitive(params)

        logger.info(
            "Labeling %s (pt_sl=%s, vb=%d, vol=%s) ...",
            asset_key, pt_sl, VERTICAL_BARRIER,
            params.get("vol_method", "ewm_100"),
        )
        labeled = apply_labels_and_compute_details(
            df, pt_sl=pt_sl, vertical_barrier=VERTICAL_BARRIER,
            vol_primitive=vol_primitive,
        )

        # Filter to rows with complete lookahead
        complete = labeled[labeled["hit_side"] != "incomplete"].copy()
        logger.info("  %s: %d bars, %d complete labels", asset_key, len(df), len(complete))

        report: dict[str, Any] = {
            "asset": asset_key,
            "parquet_name": _resolve_parquet_name(asset_key),
            "metadata": {
                "analysis_timestamp": datetime.utcnow().isoformat() + "Z",
                "total_bars": len(df),
                "complete_labels": len(complete),
                "date_range": {
                    "start": str(df.index[0].date()),
                    "end": str(df.index[-1].date()),
                },
                "label_params": {
                    "pt_sl": pt_sl,
                    "vertical_barrier": VERTICAL_BARRIER,
                    "vol_method": params.get("vol_method", "ewm_100"),
                    "atr_period": params.get("atr_period", 14),
                },
            },
        }

        for name, analyzer in self._analyzers:
            logger.info("  Running %s ...", name)
            try:
                result = analyzer.analyze(complete, params=params)
                report[name] = result
            except Exception:
                logger.exception("  %s failed for %s", name, asset_key)
                report[name] = {"error": str(e)}  # noqa: F821

        if run_counterfactual:
            logger.info("  Running counterfactual sweeps ...")
            from research.label_forensics.counterfactual import CounterfactualLabelingEngine
            try:
                cf = CounterfactualLabelingEngine()
                report["counterfactual"] = cf.analyze(df, pt_sl=tuple(pt_sl), vol_primitive=vol_primitive)
            except Exception:
                logger.exception("  counterfactual failed for %s", asset_key)
                report["counterfactual"] = {"error": "counterfactual sweep failed"}

        return report

    def analyze_all(self, assets: list[str] | None = None, run_counterfactual: bool = False) -> dict[str, Any]:
        """Run forensic analysis on every asset in the active portfolio.

        Parameters
        ----------
        assets:
            Subset to analyze. Defaults to ACTIVE_ASSETS_20260723.
        run_counterfactual:
            If True, run counterfactual sweeps.

        Returns
        -------
        dict with keys:

            ``per_asset`` : dict[str, dict]
                Map of asset key to individual report.
            ``portfolio`` : dict
                Aggregated portfolio-level report.
        """
        if assets is None:
            assets = sorted(ACTIVE_ASSETS_20260723)

        per_asset: dict[str, dict] = {}
        for asset_key in assets:
            try:
                per_asset[asset_key] = self.analyze_asset(asset_key, run_counterfactual=run_counterfactual)
            except Exception:
                logger.exception("Skipping %s due to error", asset_key)
                per_asset[asset_key] = {"asset": asset_key, "error": "analysis failed"}

        builder = ForensicsReportBuilder()
        portfolio = builder.aggregate(per_asset)
        return {"per_asset": per_asset, "portfolio": portfolio}
