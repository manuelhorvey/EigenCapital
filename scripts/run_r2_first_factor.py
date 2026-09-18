"""R2-B1 Runner — preregistered single-factor factor-lab experiment.

Preregistration (docs/research/R2_FACTOR_LAB.md §3, frozen before this run):
- Factor: momentum_12_1 — the R4 signal's own construction (12-1 month
  momentum, lookback=252, skip=21), computed POINT-IN-TIME per decision date.
  Availability timestamp = decision bar close (the signal uses only bars up
  to and including the decision bar).
- Universe: r4_local_v1 — the 8 R4-eligible symbols with local MT5 history.
- Horizon: 21 trading bars (1 month).
- Trial slot: factor_lab/momentum_12_1/h21, trial_index=1, family size 1.
- H0: mean rank IC <= 0 across the universe at this horizon.
- falsification: per the frozen contract (Holm, cost-adjusted spread,
  exclusion budget). Missing evidence -> INCONCLUSIVE, never PASS.

This validates the LAB on the platform's canonical signal construction.
If the lab cannot faithfully evaluate it, that is a laboratory finding.

Usage:
    python scripts/run_r2_first_factor.py [--horizon 21]
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import timedelta
from pathlib import Path
from typing import Dict, List, Tuple

sys.path.insert(0, "src")

import pandas as pd

from eigencapital.core.costs import STRESS_COST
from eigencapital.core.models.trial_metadata import TrialMetadata
from eigencapital.research.factor_lab.evaluation import evaluate_factor
from eigencapital.research.factor_lab.observations import build_factor_panels

SYMBOLS = ["AUDUSDm", "NZDUSDm", "GBPUSDm", "EURUSDm", "USDCHFm", "USDCADm", "USDJPYm", "XAUUSDm"]
UNIVERSE_VERSION = "r4_local_v1"
LOOKBACK = 252
SKIP = 21
DECISION_EVERY = 21  # monthly decisions on the D1 calendar
DEFAULT_HORIZON = 21  # 1 month forward return
OUT_DIR = "reports/r2_factor_lab"


def load_closes() -> Dict[str, pd.DataFrame]:
    data: Dict[str, pd.DataFrame] = {}
    for sym in SYMBOLS:
        path = Path("data/mt5") / f"{sym}_D1.csv"
        df = pd.read_csv(path, parse_dates=["time"]).set_index("time").sort_index()
        data[sym] = df[["close"]].copy()
    return data


def compute_signals_pit(
    closes: Dict[str, pd.DataFrame], decision_dates: List[pd.Timestamp]
) -> Dict[str, List[Tuple[str, float, str]]]:
    """Point-in-time 12-1 momentum signals at each decision date.

    For each decision date t, the signal uses ONLY closes up to and including
    t: mom = close(t)/close(t-252) - close(t)/close(t-252+21) normalized as
    (1+ret_12m)/(1+ret_1m) - 1 following the R4 construction. The availability
    timestamp equals the decision bar's close time — the signal is computable
    AT that close by construction (rolling windows end at t).
    """
    signals: Dict[str, List[Tuple[str, float, str]]] = {}
    for sym, df in closes.items():
        px = df["close"]
        rows: List[Tuple[str, float, str]] = []
        for t in decision_dates:
            if t not in px.index:
                continue
            pos = px.index.get_loc(t)
            if pos < LOOKBACK:
                continue  # not enough history — excluded (counted downstream)
            p_t = px.iloc[pos]
            p_12m_ago = px.iloc[pos - LOOKBACK]
            p_1m_ago = px.iloc[pos - LOOKBACK + SKIP]
            mom = (p_t / p_12m_ago) - (p_t / p_1m_ago)
            if pd.isna(mom):
                continue
            rows.append((t.strftime("%Y-%m-%d"), float(mom), t.strftime("%Y-%m-%dT%H:%M:%SZ")))
        signals[sym] = rows
    return signals


def main() -> None:
    parser = argparse.ArgumentParser(description="R2-B1 preregistered single-factor experiment")
    parser.add_argument("--horizon", type=int, default=DEFAULT_HORIZON)
    args = parser.parse_args()

    closes = load_closes()
    common_index = sorted(set.intersection(*[set(df.index) for df in closes.values()]))
    # Monthly decision dates on the common calendar, after the 252-bar warmup
    eligible = common_index[LOOKBACK:]
    decision_dates = eligible[::DECISION_EVERY]
    print(f"Decision dates: {len(decision_dates)} ({decision_dates[0].date()} -> {decision_dates[-1].date()})")

    signals = compute_signals_pit(closes, decision_dates)

    # Bars: the lab needs bar objects; build minimal close-only bars per symbol
    from eigencapital.core.models.bar import Bar

    bars_by_symbol: Dict[str, List[Bar]] = {}
    for sym, df in closes.items():
        bars = []
        prev = None
        for ts, row in df.iterrows():
            end = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
            start = (prev if prev is not None else ts - timedelta(days=1)).strftime("%Y-%m-%dT%H:%M:%SZ")
            c = float(row["close"])
            bars.append(
                Bar(
                    instrument_id=sym,
                    timestamp_utc=end,
                    bar_start_utc=start,
                    bar_end_utc=end,
                    open=c,
                    high=c,
                    low=c,
                    close=c,
                    volume=1000,
                    bar_interval="daily",
                )
            )
            prev = ts
        bars_by_symbol[sym] = bars

    panels = build_factor_panels(
        "momentum_12_1",
        UNIVERSE_VERSION,
        horizon=args.horizon,
        signals=signals,
        bars_by_symbol=bars_by_symbol,
    )
    print(
        f"Panels: {len(panels.panels)} periods, {panels.n_observations} observations, exclusions: {panels.exclusions}"
    )

    trial = TrialMetadata(
        trial_group_id=f"factor_lab/momentum_12_1/h{args.horizon}",
        trial_index=1,
        hypothesis_family="momentum",
        selection_method="single_candidate",
        trials_in_family=1,
        parameter_search_space={"horizon_bars": [args.horizon]},
    )
    result = evaluate_factor(
        panels,
        cost_model=STRESS_COST,
        trial_metadata=trial,
        top_fraction=0.34,  # ~top third of an 8-symbol cross-section
        min_names=5,
        min_periods=12,
    )

    out_dir = Path(OUT_DIR)
    out_dir.mkdir(parents=True, exist_ok=True)
    payload = {
        "experiment": "R2-B1 preregistered single factor",
        "preregistration": {
            "factor_id": "momentum_12_1",
            "hypothesis": "H0: mean rank IC <= 0",
            "universe_version": UNIVERSE_VERSION,
            "horizon_bars": args.horizon,
            "trial_group_id": trial.trial_group_id,
            "correction": "holm",
        },
        "panel_assembly": panels.to_dict(),
        "evaluation": result.to_dict(),
        "methodological_rule": (
            "Experiment-percentile/statistic statements about the run only. No forecast, no production implication."
        ),
    }
    (out_dir / "r2_b1_first_factor.json").write_text(json.dumps(payload, indent=2), encoding="utf-8")

    print("\n--- Preregistered result (H0: mean rank IC <= 0) ---")
    print(
        f"mean_ic      : {result.ic['mean_ic']:+.4f} (t={result.ic['t_stat']:+.2f}, "
        f"n={result.ic['n_periods']}, pct_pos={result.ic['pct_positive']:.2f})"
    )
    print(f"raw p / holm : {result.ic_p_value_raw:.4f} / {result.ic_p_value_holm:.4f}")
    print(f"gross spread : {result.quantile_spread_mean:+.6f}")
    print(f"cost-adj     : {result.cost_adjusted_spread:+.6f} (STRESS_COST haircut)")
    print(
        f"turnover     : {result.turnover['mean_top_set_turnover']:.3f} "
        f"(rank autocorr {result.turnover['mean_rank_autocorrelation']:+.3f})"
    )
    print(f"exclusions   : {result.exclusion_share:.2%}")
    print(f"VERDICT      : {result.verdict}")
    for r in result.reasons:
        print(f"  - {r}")
    print("\nMethodological rule: statement about THIS experiment only — no forecast, no production implication.")


if __name__ == "__main__":
    main()
