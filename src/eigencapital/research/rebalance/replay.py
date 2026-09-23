"""Offline replay engine for R4 rebalance-policy research (EXP-000002).

SIMULATION ONLY — never connects to a broker, never submits orders, never
touches live evidence files. Its purpose is a controlled ablation of the
intervention clock:

    SAME frozen R4 signal (parity-verified reconstruction)
    → SAME target portfolio at every decision date
    → ONLY the rebalance policy differs

No look-ahead (Section 15): the decision at date T uses the signal computed
from bars with index ≤ T, the close of bar T as the execution price (the live
loop acts on the next tick after the D1 close; the close of T is the last
price observable at decision time), and positions marked over past intervals
only. Future bars are never visible to any policy decision.

Cost model (Section 11): every policy pays the SAME bps per unit of one-sided
turnover in weight space: cost = turnover_one_sided × cost_bps / 1e4 × equity.
The bps value comes from the frozen strategy config (transaction_cost_bps +
slippage_bps, default 10 + 5 = 15 bps), matching the project's documented
10 bps per side convention (scripts/audit/reconstruct.py C7). Cost-ladder
stresses (base/×1.25/×1.5/×2) multiply the SAME bps for ALL policies — no
policy is ever compared gross against net.

Min-lot fidelity (Section 21): the replay books as-if-traded weights with a
configurable minimum tradable weight (min_lot_weight, default 0.01 — the
smallest FX min-lot's weight on the ~$5k account). Sub-minimum targets are
floored to the minimum exactly like the live sizing path
(`max(min_vol, round(raw_lots, 2))`), and the resulting weight distortion
(achieved − intended) is recorded per policy. R4 weights themselves are never
altered.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Dict, List, Mapping, Sequence, Tuple

import numpy as np
import pandas as pd

from eigencapital.core.rebalance import (
    CANONICAL_MIN_WEIGHT as MIN_SIGNAL_WEIGHT,
)
from eigencapital.core.rebalance import (
    PolicyConfig,
    RebalanceEvents,
    RebalancePolicy,
    build_policy,
    compute_target_hash,
)


@dataclass(frozen=True)
class ReplayConfig:
    """Replay simulation parameters (explicit, no hidden defaults)."""

    equity: float = 5100.0  # weight-space proxy (config capital.max_equity)
    cost_bps: float = 15.0  # transaction_cost_bps + slippage_bps (frozen config)
    min_lot_weight: float = 0.01  # smallest min-lot position as a weight
    max_positions: int = 20  # frozen capital.max_concurrent_positions
    start: str | None = None  # evaluation window start (ISO date)
    end: str | None = None  # evaluation window end (ISO date)
    decision_dates: Sequence[pd.Timestamp] | None = None  # precomputed grid


@dataclass
class CycleRecord:
    """One decision date's record for one policy."""

    decision_date: Any
    action: str
    reason: str
    target_hash: str
    gross_turnover_executed: float  # one-sided turnover booked at this date
    estimated_cost: float
    max_weight_deviation: float
    tradable_symbols: Tuple[str, ...] = ()
    banded_symbols: Tuple[str, ...] = ()
    n_orders: int = 0


@dataclass
class PolicyResult:
    """Full replay output for one policy (Sections 10/11/12 diagnostics)."""

    policy_id: str
    policy_type: str
    config: Dict[str, Any]
    cycles: List[CycleRecord] = field(default_factory=list)
    final_weights: Dict[str, float] = field(default_factory=dict)
    daily_net_returns: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    daily_gross_returns: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))

    # ── turnover accounting (Section 10) ─────────────────────────────
    total_gross_turnover: float = 0.0  # one-sided, weight space
    n_rebalances: int = 0
    n_orders: int = 0
    n_entries: int = 0
    n_exits: int = 0
    n_reductions: int = 0
    n_increases: int = 0
    n_reversals: int = 0
    holding_periods: List[float] = field(default_factory=list)  # days per holding

    # ── cost accounting (Section 11) ─────────────────────────────────
    total_costs: float = 0.0
    gross_pnl: float = 0.0
    net_pnl: float = 0.0

    # ── tracking (Section 12) ────────────────────────────────────────
    weight_tracking_errors: List[float] = field(default_factory=list)  # per-cycle mean |Δw|
    tracking_error_samples: List[float] = field(default_factory=list)  # every |Δw| sample
    min_lot_distortion: float = 0.0  # running mean distortion per floored symbol

    def summary(self, cost_bps: float) -> Dict[str, Any]:
        """Section 30 report row."""
        ret = self.daily_net_returns
        gross = self.daily_gross_returns
        n_years = len(ret) / 252.0 if len(ret) else 0.0
        gross_ret = float(gross.sum()) if len(gross) else 0.0
        net_ret = float(ret.sum()) if len(ret) else 0.0
        cost_drag = net_ret - gross_ret
        te_max = float(np.max(self.tracking_error_samples)) if self.tracking_error_samples else 0.0
        return {
            "policy_id": self.policy_id,
            "rebalances": self.n_rebalances,
            "orders": self.n_orders,
            "entries": self.n_entries,
            "exits": self.n_exits,
            "reductions": self.n_reductions,
            "increases": self.n_increases,
            "reversals": self.n_reversals,
            "turnover_total": self.total_gross_turnover,
            "turnover_annualized": (self.total_gross_turnover / n_years) if n_years > 0 else 0.0,
            "gross_return": gross_ret,
            "net_return": net_ret,
            "cost_drag": cost_drag,
            "cost_over_gross": (abs(cost_drag) / abs(gross_ret)) if abs(gross_ret) > 1e-12 else float("inf"),
            "return_per_turnover": (net_ret / self.total_gross_turnover) if self.total_gross_turnover > 1e-12 else 0.0,
            "net_sharpe": _annualized_sharpe(ret),
            "gross_sharpe": _annualized_sharpe(gross),
            "max_drawdown": _max_drawdown(ret),
            "net_pnl": self.net_pnl,
            "gross_pnl": self.gross_pnl,
            "total_costs": self.total_costs,
            "tracking_error_mean": (
                float(np.mean(self.weight_tracking_errors)) if self.weight_tracking_errors else 0.0
            ),
            "tracking_error_max": te_max,
            "avg_holding_days": (float(np.mean(self.holding_periods)) if self.holding_periods else 0.0),
            "min_lot_distortion": self.min_lot_distortion,
            "cost_bps": cost_bps,
        }


def _annualized_sharpe(returns: pd.Series, periods_per_year: float = 252.0) -> float:
    if len(returns) < 2:
        return 0.0
    std = float(returns.std(ddof=1))
    if std <= 1e-12 or not math.isfinite(std):
        return 0.0
    return float(returns.mean()) / std * math.sqrt(periods_per_year)


def _max_drawdown(returns: pd.Series) -> float:
    if len(returns) == 0:
        return 0.0
    curve = (1.0 + returns.fillna(0.0)).cumprod()
    peak = curve.cummax()
    dd = curve / peak - 1.0
    return float(dd.min())


def apply_min_lot_floor(
    target_weights: Mapping[str, float],
    min_lot_weight: float,
    max_positions: int,
) -> Tuple[Dict[str, float], List[str]]:
    """Mirror the live sizing floor: sub-minimum ACTIVE targets → minimum.

    The live generator ranks by |w| and keeps the top `max_positions`; active
    sub-minimum targets are floored UP to min volume exactly like
    generate_orders. Returns (floored_weights, floored_symbols).
    """
    ranked = sorted(
        ((s, w) for s, w in target_weights.items() if abs(w) > MIN_SIGNAL_WEIGHT),
        key=lambda kv: (-abs(kv[1]), kv[0]),
    )[:max_positions]
    floored: Dict[str, float] = {}
    floored_syms: List[str] = []
    for sym, w in ranked:
        if abs(w) < min_lot_weight:
            floored[sym] = math.copysign(min_lot_weight, w)
            floored_syms.append(sym)
        else:
            floored[sym] = w
    return floored, floored_syms


class PolicyReplay:
    """As-if-traded simulation of ONE policy over the frozen signal stream.

    Execution convention: trades happen at the decision date's close (the
    last observable price); the interval return between consecutive decision
    dates accrues to the weights held over that interval (decided strictly
    before the interval starts).
    """

    def __init__(
        self,
        config: PolicyConfig,
        replay_cfg: ReplayConfig,
        weights_panel: pd.DataFrame,
        closes: pd.DataFrame,
    ) -> None:
        """
        weights_panel: index/columns = decision dates × symbols, values =
            the frozen R4 target weight computed from bars ≤ that date
            (IDENTICAL for every policy — Section 14).
        closes: close-price panel aligned with weights_panel (same source
            data; used only for backward-looking mark-to-market).
        """
        self._config = config
        self._cfg = replay_cfg
        self._weights = weights_panel
        self._closes = closes
        self._policy: RebalancePolicy = build_policy(config)

    @property
    def policy(self) -> RebalancePolicy:
        return self._policy

    def _decision_dates(self) -> List[pd.Timestamp]:
        cfg = self._cfg
        if cfg.decision_dates is not None:
            dates = list(cfg.decision_dates)
        else:
            idx = self._weights.index
            if cfg.start:
                idx = idx[idx >= pd.Timestamp(cfg.start)]
            if cfg.end:
                idx = idx[idx <= pd.Timestamp(cfg.end)]
            dates = list(idx)
        return [pd.Timestamp(d) for d in dates]

    def run(self) -> PolicyResult:
        cfg = self._cfg
        result = PolicyResult(
            policy_id=self._config.policy_id,
            policy_type=self._config.policy_type.value,
            config=self._config.to_dict(),
        )
        current: Dict[str, float] = {}  # held signed weights (post-trade)
        entry_dates: Dict[str, pd.Timestamp] = {}
        prev_close: pd.Timestamp | None = None

        for t in self._decision_dates():
            target_raw = {s: float(w) for s, w in self._weights.loc[t].items() if np.isfinite(w)}
            target, floored_syms = apply_min_lot_floor(target_raw, cfg.min_lot_weight, cfg.max_positions)

            # ── Policy decision (intervention clock; no future info) ─────
            decision = self._policy.should_rebalance(
                current_weights=current,
                target_weights=target,
                signal_timestamp=t.to_pydatetime(),
                now=t.to_pydatetime(),
                events=RebalanceEvents(),
            )
            self._policy.record_target(compute_target_hash(target), t.to_pydatetime())

            # ── 1. Mark-to-market [prev_close, t] on weights held over it ─
            interval_ret = 0.0
            if prev_close is not None and current:
                try:
                    p0 = self._closes.loc[prev_close]
                    p1 = self._closes.loc[t]
                except KeyError:
                    p0, p1 = None, None
                if p0 is not None and p1 is not None:
                    for sym, w in current.items():
                        c0 = float(p0.get(sym, np.nan)) if hasattr(p0, "get") else np.nan
                        c1 = float(p1.get(sym, np.nan)) if hasattr(p1, "get") else np.nan
                        if np.isfinite(c0) and np.isfinite(c1) and c0 != 0:
                            interval_ret += w * (c1 / c0 - 1.0)

            # ── 2. Trade at t's close ────────────────────────────────────
            cost_today = 0.0
            one_sided = 0.0
            if decision.should_trade:
                tradable = set(decision.tradable_symbols)
                banded = set(decision.banded_symbols)
                # Trade-event counts on tradable symbols.
                for sym in sorted(tradable):
                    tw = target.get(sym, 0.0)
                    cw = current.get(sym, 0.0)
                    if abs(tw) > MIN_SIGNAL_WEIGHT and abs(cw) <= MIN_SIGNAL_WEIGHT:
                        result.n_entries += 1
                    elif abs(tw) <= MIN_SIGNAL_WEIGHT and abs(cw) > MIN_SIGNAL_WEIGHT:
                        result.n_exits += 1
                    elif (tw > 0) != (cw > 0) and abs(cw) > MIN_SIGNAL_WEIGHT:
                        result.n_reversals += 1
                    elif abs(tw - cw) > 1e-9:
                        if abs(tw) > abs(cw):
                            result.n_increases += 1
                        else:
                            result.n_reductions += 1
                    if sym not in entry_dates and abs(tw) > MIN_SIGNAL_WEIGHT:
                        entry_dates[sym] = t
                # Exits: held symbols whose target went flat (full_exit class).
                # Banded symbols are HELD, not exited — the band keeps them.
                for sym in sorted(set(current) - tradable - banded):
                    if abs(current.get(sym, 0.0)) > MIN_SIGNAL_WEIGHT:
                        result.n_exits += 1
                    entry_dates.pop(sym, None)
                # Turnover counts only what is actually traded: tradable
                # symbols moving to their target (full exits contribute
                # |0 − current|). Banded/carried symbols place no order and
                # pay nothing — charging their deferred drift would penalise
                # wide bands for trades that never happened.
                one_sided = sum(abs(float(target.get(s, 0.0)) - float(current.get(s, 0.0))) for s in tradable)
                cost_today = one_sided * cfg.cost_bps / 1e4 * cfg.equity
                result.total_gross_turnover += one_sided
                result.total_costs += cost_today
                # New portfolio: tradable actives take target weights; banded
                # symbols (and any held symbol the band protected) keep
                # carrying their previous weights.
                new_portfolio: Dict[str, float] = {}
                for sym in tradable:
                    if abs(target.get(sym, 0.0)) > MIN_SIGNAL_WEIGHT:
                        new_portfolio[sym] = float(target[sym])
                for sym, w in current.items():
                    if sym not in tradable and abs(w) > MIN_SIGNAL_WEIGHT:
                        new_portfolio[sym] = float(w)
                current = new_portfolio
                self._policy.record_trade(t.to_pydatetime(), decision)
                result.n_rebalances += 1
                result.n_orders += len(tradable)
                if floored_syms:
                    distortion = sum(abs(float(target_raw.get(s, 0.0)) - current.get(s, 0.0)) for s in floored_syms)
                    result.min_lot_distortion = (
                        result.min_lot_distortion * (result.n_rebalances - 1) + distortion / max(len(floored_syms), 1)
                    ) / result.n_rebalances
            else:
                self._policy.record_hold(decision)

            # ── 3. Diagnostics (Section 12) ──────────────────────────────
            dev_samples = [abs(float(target.get(s, 0.0)) - current.get(s, 0.0)) for s in set(target) | set(current)]
            mean_dev = float(np.mean(dev_samples)) if dev_samples else 0.0
            result.weight_tracking_errors.append(mean_dev)
            result.tracking_error_samples.extend(dev_samples)

            result.cycles.append(
                CycleRecord(
                    decision_date=t,
                    action=decision.action.value,
                    reason=decision.reason.value,
                    target_hash=compute_target_hash(target),
                    gross_turnover_executed=(one_sided if decision.should_trade else 0.0),
                    estimated_cost=cost_today,
                    max_weight_deviation=decision.max_weight_deviation,
                    tradable_symbols=tuple(sorted(decision.tradable_symbols)),
                    banded_symbols=tuple(sorted(decision.banded_symbols)),
                    n_orders=(len(decision.tradable_symbols) if decision.should_trade else 0),
                )
            )
            result.daily_gross_returns.loc[t] = interval_ret
            result.daily_net_returns.loc[t] = interval_ret - cost_today / cfg.equity
            prev_close = t

        result.final_weights = dict(current)
        result.gross_pnl = float(result.daily_gross_returns.sum()) * cfg.equity
        result.net_pnl = float(result.daily_net_returns.sum()) * cfg.equity
        dates = self._decision_dates()
        if dates:
            last_t = dates[-1]
            result.holding_periods = [(last_t - t0).total_seconds() / 86400.0 for t0 in entry_dates.values()]
        return result


def run_policy_matrix(
    weights_panel: pd.DataFrame,
    closes: pd.DataFrame,
    replay_cfg: ReplayConfig,
    configs: Sequence[PolicyConfig] | None = None,
) -> Dict[str, PolicyResult]:
    """Run every policy over the SAME signal stream (Section 14 ablation)."""
    configs = configs if configs is not None else _matrix_configs()
    results: Dict[str, PolicyResult] = {}
    for config in configs:
        replay = PolicyReplay(config, replay_cfg, weights_panel, closes)
        results[config.policy_id] = replay.run()
    return results


def _matrix_configs() -> List[PolicyConfig]:
    from eigencapital.core.rebalance import experiment_matrix

    return experiment_matrix()


def cost_ladder(
    base_bps: float,
    multipliers: Sequence[float] = (1.0, 1.25, 1.5, 2.0),
) -> List[float]:
    """Section 20 cost ladder applied uniformly to every policy."""
    return [base_bps * m for m in multipliers]


def build_decision_grid(
    closes_index: pd.DatetimeIndex,
    start: str | None,
    end: str | None,
    cadence: str = "daily",
) -> List[pd.Timestamp]:
    """Candidate decision dates (backward-looking grid, no future knowledge).

    cadence: "daily" uses every bar in the window; "weekly" uses the last
    bar of each ISO week (a deterministic anchor known in advance). The
    POLICY — not the grid — decides which candidate dates trigger an
    intervention, so every policy sees the identical candidate grid.
    """
    idx = closes_index
    if start:
        idx = idx[idx >= pd.Timestamp(start)]
    if end:
        idx = idx[idx <= pd.Timestamp(end)]
    idx_list = list(idx)
    if cadence == "weekly":
        by_week: Dict[Tuple[int, int], pd.Timestamp] = {}
        for ts in idx_list:
            iso = ts.isocalendar()
            by_week[(iso[0], iso[1])] = ts  # a later bar in the same week overwrites
        return sorted(by_week.values())
    return idx_list
