"""Portfolio risk compression test — stress scenario injection for TP/SL optimization.

Evaluates portfolio under four scenarios defined in the TP/SL audit prompt:
1. Normal regime — baseline Monte Carlo
2. High volatility regime (2-3x ATR) — vol multiplier shock
3. Correlation spike regime — all correlated assets move together
4. Sequential loss streak (5-10 losses) — synthetic loss injection

Reports max daily DD, max total DD, and constraint violations.
"""

from __future__ import annotations

import logging
import sys
from dataclasses import dataclass

import numpy as np
import pandas as pd

from pathlib import Path

from scripts.backtest.monte_carlo_drawdown import (
    SELL_ONLY_ACTIVE,
    load_daily_portfolio_returns,
)

logger = logging.getLogger("eigencapital.optimization.risk_compression")

DEFAULT_DAILY_DD_LIMIT = -0.05
DEFAULT_MAX_DD_LIMIT = -0.15
DEFAULT_N_SIM = 10_000
DEFAULT_BLOCK_SIZE = 10


@dataclass
class StressScenario:
    name: str
    vol_multiplier: float = 1.0
    correlation_shock: bool = False
    loss_streak: int = 0
    loss_streak_magnitude: float = -2.0


@dataclass
class ScenarioResult:
    name: str
    max_dd_series: pd.Series
    max_daily_dd: float
    max_total_dd: float
    p_positive_return: float
    daily_dd_breached: bool
    max_dd_breached: bool
    var_95_dd: float
    cvar_95_dd: float


def inject_scenario(
    pct_returns: pd.Series,
    scenario: StressScenario,
    rng: np.random.Generator,
) -> pd.Series:
    """Apply stress scenario to a copy of the return series."""
    returns = pct_returns.copy()

    if scenario.vol_multiplier != 1.0:
        returns = returns * scenario.vol_multiplier

    if scenario.correlation_shock:
        n = len(returns)
        shock_days = rng.choice(n, size=int(n * 0.3), replace=False)
        corr_extra = rng.normal(0, abs(float(returns.std())) * 2, size=len(shock_days))
        returns.iloc[shock_days] += corr_extra
        returns.iloc[shock_days] = returns.iloc[shock_days].clip(-0.15, 0.15)

    if scenario.loss_streak > 0:
        streak_start = rng.integers(0, max(1, len(returns) - scenario.loss_streak))
        for i in range(scenario.loss_streak):
            if streak_start + i < len(returns):
                returns.iloc[streak_start + i] = scenario.loss_streak_magnitude * abs(float(returns.std()))

    return returns


def block_bootstrap(
    returns: pd.Series,
    n_sim: int,
    block_size: int,
    horizon_days: int,
    rng: np.random.Generator,
) -> list[pd.Series]:
    """Block bootstrap from return series for a given horizon."""
    paths: list[pd.Series] = []
    for _ in range(n_sim):
        sampled: list[float] = []
        while len(sampled) < horizon_days:
            start = rng.integers(0, max(1, len(returns) - block_size))
            sampled.extend(returns.iloc[start : start + block_size].tolist())
        paths.append(pd.Series(sampled[:horizon_days]))
    return paths


def compute_path_metrics(path: pd.Series) -> dict[str, float]:
    """Compute metrics for a single bootstrapped path."""
    cum = (1 + path).cumprod()
    running_max = cum.cummax()
    dd = (cum - running_max) / running_max
    max_dd = float(dd.min())
    total_return = float(cum.iloc[-1] - 1)
    return {"max_dd": max_dd, "total_return": total_return}


def run_scenario(
    pct_returns: pd.Series,
    scenario: StressScenario,
    n_sim: int = DEFAULT_N_SIM,
    block_size: int = DEFAULT_BLOCK_SIZE,
    horizon_days: int = 252,
    daily_dd_limit: float = DEFAULT_DAILY_DD_LIMIT,
    max_dd_limit: float = DEFAULT_MAX_DD_LIMIT,
    rng: np.random.Generator | None = None,
) -> ScenarioResult:
    """Run a single stress scenario and return aggregate results."""
    if rng is None:
        rng = np.random.default_rng(42)

    stressed = inject_scenario(pct_returns, scenario, rng)
    paths = block_bootstrap(stressed, n_sim, block_size, horizon_days, rng)

    max_dds: list[float] = []
    total_returns: list[float] = []
    for path in paths:
        metrics = compute_path_metrics(path)
        max_dds.append(metrics["max_dd"])
        total_returns.append(metrics["total_return"])

    max_dd_series = pd.Series(max_dds)
    max_daily_dd = float(pct_returns.min())
    max_total_dd = float(max_dd_series.mean())
    p_positive = float((np.array(total_returns) > 0).mean())

    sorted_dds = np.sort(max_dds)
    idx_95 = int(len(sorted_dds) * 0.95)
    var_95 = float(sorted_dds[idx_95]) if idx_95 < len(sorted_dds) else float(sorted_dds[-1])
    cvar_95 = float(np.mean(sorted_dds[idx_95:])) if idx_95 < len(sorted_dds) else var_95

    return ScenarioResult(
        name=scenario.name,
        max_dd_series=max_dd_series,
        max_daily_dd=round(max_daily_dd, 4),
        max_total_dd=round(max_total_dd, 4),
        p_positive_return=round(p_positive, 4),
        daily_dd_breached=max_daily_dd < daily_dd_limit,
        max_dd_breached=max_total_dd < max_dd_limit,
        var_95_dd=round(var_95, 4),
        cvar_95_dd=round(cvar_95, 4),
    )


def run_all_scenarios(
    pct_returns: pd.Series,
    n_sim: int = DEFAULT_N_SIM,
    daily_dd_limit: float = DEFAULT_DAILY_DD_LIMIT,
    max_dd_limit: float = DEFAULT_MAX_DD_LIMIT,
) -> list[ScenarioResult]:
    """Run all four stress scenarios and return results."""
    rng = np.random.default_rng(42)

    scenarios = [
        StressScenario(name="normal"),
        StressScenario(name="high_vol", vol_multiplier=2.5),
        StressScenario(name="correlation_spike", correlation_shock=True),
        StressScenario(name="loss_streak_10", loss_streak=10, loss_streak_magnitude=-2.0),
    ]

    results: list[ScenarioResult] = []
    for sc in scenarios:
        logger.info("Running scenario: %s", sc.name)
        result = run_scenario(
            pct_returns,
            sc,
            n_sim=n_sim,
            daily_dd_limit=daily_dd_limit,
            max_dd_limit=max_dd_limit,
            rng=rng,
        )
        results.append(result)
    return results


def print_report(results: list[ScenarioResult], n_sim: int) -> None:
    """Print human-readable risk compression report."""
    print("=" * 80)
    print("  PORTFOLIO RISK COMPRESSION REPORT")
    print(f"  {n_sim} simulations per scenario")
    print("=" * 80)

    print(
        f"\n{'Scenario':20s} {'MaxDailyDD':>10s} {'MaxTotalDD':>10s} {'VaR(95)DD':>10s} "
        f"{'CVaR(95)':>10s} {'P(PosR)':>8s} {'DDLimit?':>8s} {'MaxLimit?':>9s}"
    )
    print(f"{'-' * 85}")
    for r in results:
        dd_ok = "OK" if not r.daily_dd_breached else "BREACH"
        md_ok = "OK" if not r.max_dd_breached else "BREACH"
        print(
            f"{r.name:20s} {r.max_daily_dd:>10.2%} {r.max_total_dd:>10.2%} "
            f"{r.var_95_dd:>10.2%} {r.cvar_95_dd:>10.2%} "
            f"{r.p_positive_return:>8.1%} {dd_ok:>8s} {md_ok:>9s}"
        )

    breaches = [r for r in results if r.daily_dd_breached or r.max_dd_breached]
    if breaches:
        print(f"\n{'!' * 60}")
        print("  CONSTRAINT BREACHES DETECTED")
        for r in breaches:
            if r.daily_dd_breached:
                print(f"  ✗ {r.name}: daily DD ({r.max_daily_dd:.2%}) exceeds limit")
            if r.max_dd_breached:
                print(f"  ✗ {r.name}: max DD ({r.max_total_dd:.2%}) exceeds limit")
        print(f"{'!' * 60}")
    else:
        print("\n  ✓ All constraints passed across all scenarios")

    print(f"\n{'=' * 80}")
    print()


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")

    import argparse

    parser = argparse.ArgumentParser(description="Portfolio risk compression stress test")
    parser.add_argument("--n-sim", type=int, default=DEFAULT_N_SIM, help="Number of simulations per scenario")
    parser.add_argument("--daily-dd-limit", type=float, default=DEFAULT_DAILY_DD_LIMIT, help="Daily drawdown limit")
    parser.add_argument("--max-dd-limit", type=float, default=DEFAULT_MAX_DD_LIMIT, help="Max drawdown limit")
    parser.add_argument("--horizon-days", type=int, default=252, help="Simulation horizon in trading days")
    parser.add_argument("--block-size", type=int, default=DEFAULT_BLOCK_SIZE, help="Block bootstrap block size")
    args = parser.parse_args()

    try:
        _, pct_returns = load_daily_portfolio_returns(sell_only=SELL_ONLY_ACTIVE)
    except FileNotFoundError:
        logger.error("No walk-forward signal parquets found.")
        logger.info("Run walk_forward_backtest.py first to generate signal parquets.")
        sys.exit(1)

    if len(pct_returns) < args.block_size * 2:
        logger.error(
            "Not enough daily returns (%d) for block bootstrap (block_size=%d)",
            len(pct_returns),
            args.block_size,
        )
        sys.exit(1)

    results = run_all_scenarios(
        pct_returns,
        n_sim=args.n_sim,
        daily_dd_limit=args.daily_dd_limit,
        max_dd_limit=args.max_dd_limit,
    )
    print_report(results, args.n_sim)


if __name__ == "__main__":
    main()
