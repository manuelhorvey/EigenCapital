"""Pair Trading Pipeline — R4-MR frozen contract, stages 3–9.

R4 Phase B1 (docs/research/R4_MEAN_REVERSION.md). Runs ONE preregistered
pair through the frozen pipeline:

    rolling PIT estimation (250-bar window, 21-bar step)
      → gates: ADF p<0.05, cointegration p<0.05, 5 ≤ half-life ≤ 60
      → regime active/inactive (fail → flat, never stale re-use)
    daily z-score (frozen 60-bar spread window, CURRENT regime's β/α)
      → entry |z| ≥ 2.0, exit |z| ≤ 0.5 (frozen, no search)
    ±1 unit spread notional; 15 bps one-way per leg (4 × 15 bps per round trip)

Execution semantics (preregistered reading of the contract):
- Gates/β/α are estimated on windows ending STRICTLY BEFORE the regime's
  first decision bar (PIT, contract item 3).
- Decisions at bar t execute at bar t+1 (one-bar lag, R3 convention).
- A pending ENTRY is CANCELLED if the regime has gone inactive by execution
  time (recorded in `n_cancelled_entries` — never silently ignored).
- Exits are always honored regardless of regime state.
- Position P&L uses the ENTRY regime's (β, α); z (entries AND exits) uses
  the CURRENT regime's (β, α) over the frozen 60-bar spread window.
- A position still open at the last bar is force-closed with
  close_reason="end_of_sample" (honest, visible).

State machine: FLAT → SHORT_SPREAD (z ≥ +2) or LONG_SPREAD (z ≤ −2) →
FLAT on |z| ≤ 0.5. Verdicts (F-A/F-B/F-C) are applied by the runner over
the whole family, never here.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Tuple, cast

import pandas as pd

from eigencapital.research.mean_reversion.estimation import (
    adf_pvalue,
    coint_pvalue,
    half_life,
    hedge_ratio,
    spread_from,
)

# ── Frozen contract constants (ledger items 1–8) — NO search, NO defaults ────
ESTIMATION_WINDOW = 250
ESTIMATION_STEP = 21
ADF_MAX_P = 0.05
COINT_MAX_P = 0.05
HL_MIN_DAYS = 5.0
HL_MAX_DAYS = 60.0
Z_WINDOW = 60
Z_ENTRY = 2.0
Z_EXIT = 0.5
COST_ONE_WAY_PER_LEG = 0.0015  # 15 bps, R1/R3 convention
COST_PER_ROUND_TRIP = 4 * COST_ONE_WAY_PER_LEG  # 2 legs × (enter + exit)


class PipelineError(ValueError):
    """Invalid pipeline specification — never silently swallowed."""


@dataclass(frozen=True)
class GateState:
    """One estimation date's gate evaluation (PIT — all values pre-decision)."""

    date: pd.Timestamp
    adf_p: float
    coint_p: float
    beta: float
    alpha: float
    half_life_days: float | None
    regime_active: bool
    reason: str  # comma-joined failed gates, "" when active


@dataclass
class PairResult:
    """One pair's full-sample pipeline output (diagnostics + trades)."""

    pair: Tuple[str, str]
    gates: List[GateState] = field(default_factory=list)
    round_trips: List[Dict[str, object]] = field(default_factory=list)
    daily_returns: pd.Series = field(default_factory=lambda: pd.Series(dtype=float))
    n_estimation_dates: int = 0
    n_regime_active: int = 0
    n_cancelled_entries: int = 0
    n_gate_failures: Dict[str, int] = field(default_factory=dict)

    @property
    def total_pnl(self) -> float:
        return float(sum(cast(float, t["net_pnl"]) for t in self.round_trips))

    @property
    def hit_rate(self) -> float:
        if not self.round_trips:
            return 0.0
        wins = sum(1 for t in self.round_trips if cast(float, t["net_pnl"]) > 0)
        return wins / len(self.round_trips)


def run_pair(
    log_a: pd.Series,
    log_b: pd.Series,
    pair: Tuple[str, str],
    estimation_window: int = ESTIMATION_WINDOW,
    estimation_step: int = ESTIMATION_STEP,
) -> PairResult:
    """Run ONE pair through the frozen pipeline over its common history.

    Args:
        log_a, log_b: LOG prices of the two legs, indexed by date. The
            caller aligns them to the common calendar.
        pair: (symbol_a, symbol_b) for records.
        estimation_window, estimation_step: frozen contract geometry.

    Raises:
        PipelineError: on degenerate inputs (too short, misaligned).
    """
    if estimation_window < Z_WINDOW + 2:
        raise PipelineError(f"estimation window {estimation_window} cannot support the frozen z-window ({Z_WINDOW})")
    common = log_a.index.intersection(log_b.index)
    if len(common) < estimation_window + 2:
        raise PipelineError(f"pair {pair}: {len(common)} common bars < window+2 ({estimation_window + 2}) — cannot run")
    a = log_a.reindex(common)
    b = log_b.reindex(common)
    n = len(common)

    result = PairResult(pair=pair)
    gate_failures: Dict[str, int] = {"adf": 0, "coint": 0, "half_life": 0}
    est_dates = set(range(estimation_window, n, estimation_step))

    # Regime state (updated only at estimation dates)
    regime_active = False
    beta = alpha = float("nan")

    # Position state
    position: str | None = None  # None | "LONG_SPREAD" | "SHORT_SPREAD"
    entry_idx: int | None = None
    entry_beta = entry_alpha = float("nan")
    entry_z = float("nan")

    def _spread(i: int, bt: float, at: float) -> float:
        return float(a.iloc[i] - bt * b.iloc[i] - at)

    def _z(i: int, bt: float, at: float) -> float | None:
        """PIT z at bar i: spread over the frozen 60-bar window ending at i."""
        lo = i - Z_WINDOW + 1
        if lo < 0:
            return None
        win = pd.Series(
            [_spread(k, bt, at) for k in range(lo, i + 1)],
            index=common[lo : i + 1],
        )
        std = float(win.std(ddof=1))
        if not pd.notna(std) or std <= 1e-12:
            return None
        return float((win.iloc[-1] - win.mean()) / std)

    pending: Tuple[str, int] | None = None  # (action, decision_bar)
    daily_index: List[pd.Timestamp] = []
    daily_values: List[float] = []

    def _close(i: int, z_exit: float, reason: str) -> None:
        nonlocal position, entry_idx, entry_beta, entry_alpha, entry_z
        assert position is not None and entry_idx is not None
        s_entry = _spread(entry_idx, entry_beta, entry_alpha)
        s_exit = _spread(i, entry_beta, entry_alpha)
        gross = (s_exit - s_entry) if position == "LONG_SPREAD" else (s_entry - s_exit)
        result.round_trips.append(
            {
                "direction": position,
                "entry_date": common[entry_idx],
                "exit_date": common[i],
                "entry_z": entry_z,
                "exit_z": z_exit,
                "beta": entry_beta,
                "alpha": entry_alpha,
                "gross_pnl": gross,
                "cost": COST_PER_ROUND_TRIP,
                "net_pnl": gross - COST_PER_ROUND_TRIP,
                "close_reason": reason,
            }
        )
        position, entry_idx = None, None

    for t in range(estimation_window, n):
        date = common[t]

        # (a) Regime re-estimation at preregistered dates — PIT window.
        if t in est_dates:
            wa = a.iloc[t - estimation_window : t]
            wb = b.iloc[t - estimation_window : t]
            p_adf = adf_pvalue(wa)
            p_coint = coint_pvalue(wa, wb)
            beta_w, alpha_w = hedge_ratio(wa, wb)
            hl = half_life(spread_from(wa, wb, beta_w, alpha_w))
            reasons: List[str] = []
            if p_adf >= ADF_MAX_P:
                reasons.append("adf")
            if p_coint >= COINT_MAX_P:
                reasons.append("coint")
            if hl is None or not (HL_MIN_DAYS <= hl <= HL_MAX_DAYS):
                reasons.append("half_life")
            regime_active = not reasons
            beta, alpha = beta_w, alpha_w
            result.gates.append(
                GateState(
                    date=date,
                    adf_p=p_adf,
                    coint_p=p_coint,
                    beta=beta_w,
                    alpha=alpha_w,
                    half_life_days=hl,
                    regime_active=regime_active,
                    reason=",".join(reasons),
                )
            )
            result.n_estimation_dates += 1
            if regime_active:
                result.n_regime_active += 1
            else:
                for key in reasons:
                    gate_failures[key] += 1

        # (b) Execute the decision made at t−1, at bar t (one-bar lag).
        if pending is not None:
            action, decision_bar = pending
            pending = None
            if action == "EXIT" and position is not None:
                z_now = _z(t, beta, alpha)  # current regime params (latest PIT)
                _close(t, float(z_now) if z_now is not None else float("nan"), f"z_exit@{common[decision_bar].date()}")
            elif action.startswith("ENTER") and position is None:
                if not regime_active:
                    result.n_cancelled_entries += 1  # regime died between
                else:  # decision and execution — cancel, never enter
                    position = action[6:]
                    entry_idx = t
                    entry_beta, entry_alpha = beta, alpha
                    z_dec = _z(decision_bar, beta, alpha)
                    entry_z = float(z_dec) if z_dec is not None else float("nan")

        # (c) Daily return for bar t (position opened strictly before t).
        if position is None or entry_idx is None or entry_idx >= t:
            daily_values.append(0.0)
        else:
            s_now = _spread(t, entry_beta, entry_alpha)
            s_prev = _spread(t - 1, entry_beta, entry_alpha)
            signed = (s_now - s_prev) if position == "LONG_SPREAD" else (s_prev - s_now)
            daily_values.append(signed)
        daily_index.append(date)

        # (d) Decide at bar t (executed at t+1). z under CURRENT regime's
        # (β, α) — the latest PIT estimates, updated at every estimation date
        # regardless of gate outcome (exits must always be computable).
        if t + 1 < n:
            z_cur = _z(t, beta, alpha)
            if z_cur is not None:
                if position is None:
                    if regime_active:
                        if z_cur >= Z_ENTRY:
                            pending = ("ENTER_SHORT_SPREAD", t)
                        elif z_cur <= -Z_ENTRY:
                            pending = ("ENTER_LONG_SPREAD", t)
                elif abs(z_cur) <= Z_EXIT:
                    pending = ("EXIT", t)

    # Force-close any position still open at the last bar (honest, visible).
    if position is not None:
        z_last = _z(n - 1, entry_beta, entry_alpha)
        _close(n - 1, float(z_last) if z_last is not None else float("nan"), "end_of_sample")

    result.n_gate_failures = gate_failures
    result.daily_returns = pd.Series(daily_values, index=pd.DatetimeIndex(daily_index), dtype=float)
    return result
