"""R4-S Shadow Portfolio Constructor — offline replay + live soak observation.

SHADOW-ONLY. This script NEVER submits orders. It:
  * reconstructs the frozen R4 candidate universe (same signal, same data),
  * records the frozen R4 selection as the untouched control group,
  * builds a correlation/exposure-aware shadow portfolio,
  * persists shadow decisions/outcomes to reports/r4_loop/shadow_portfolio_*.jsonl.

It does NOT write to decisions.jsonl / order_intents.jsonl / risk_gate_audit.jsonl
and does NOT call any broker order API. In observe mode it opens a READ-ONLY
MT5 session (market data + symbol info only).

Usage:
    # Offline replay over local D1 history (no MT5 required)
    python scripts/r4_shadow_portfolio.py --replay --start 2025-01-01 --end 2026-09-06

    # Live soak observation (read-only MT5, single cycle)
    python scripts/r4_shadow_portfolio.py --observe

    # Summarize recorded shadow evidence
    python scripts/r4_shadow_portfolio.py --status
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from eigencapital.config import load_config  # noqa: E402
from eigencapital.shadow.portfolio.correlation import CorrelationModel  # noqa: E402
from eigencapital.shadow.portfolio.exposure import ExposureModel, get_factor_group  # noqa: E402
from eigencapital.shadow.portfolio.selector import (  # noqa: E402
    ShadowCandidate,
    ShadowDecision,
    ShadowSelector,
    ShadowSelectorConfig,
)
from eigencapital.shadow.portfolio.tracker import (  # noqa: E402
    ShadowDecisionRecorder,
    ShadowPositionTracker,
    default_output_dir,
)

# Frozen signal parameters (must mirror config; parity-tested).
LOOKBACK, SKIP, VOL_LB = 252, 21, 60
ATR_PERIOD = 14
MIN_SIGNAL_WEIGHT = 0.005

# Data for offline replay (same convention as scripts/audit/reconstruct.py).
DATA_DIR = REPO / "data" / "mt5"

# Native symbols available as CSVs (subset of the 33-symbol production universe).
NATIVE = {
    "AUDUSD",
    "EURUSD",
    "GBPUSD",
    "USDJPY",
    "USDCAD",
    "USDCHF",
    "NZDUSD",
    "XAUUSD",
    "XAGUSD",
    "US500",
    "US30",
    "USTEC",
    "BTCUSD",
    "ETHUSD",
    "USOIL",
}

EQUITY_FOR_SHADOW = 5100.0  # weight-space proxy equity (documented; config max_equity)

# Selection sizes for the edge-by-size / frontier diagnostic (brief "next
# phase": top-1/2/4/6/8 plus the D3b/D4 evidence sizes — purely diagnostic,
# never a tuning target). Size 20 (the R4 baseline) is tracked separately.
SIZE_BREAKDOWN_NS = (1, 2, 4, 5, 6, 7, 8)
BASELINE_SIZE = 20  # R4-20 control column in the D4 realized-outcome table

# Project cost convention (scripts/audit/reconstruct.py C7): 10 bps per side.
COST_PER_SIDE_BPS = 10.0


def _row_prices(cw: pd.DataFrame, t: Any) -> Dict[str, float]:
    """Close prices for every signal symbol at row t (finite values only)."""
    row = cw.loc[t]
    return {s: float(row[s]) for s in cw.columns if np.isfinite(row[s])}


class _SizeTracker:
    """In-memory as-if-traded bookkeeping for one selection size N.

    Mirrors the ShadowPositionTracker convention (entry/exit at decision-bar
    close, weight-space notional = |w|·equity) but adds the project's 10 bps
    per-side cost convention so the frontier can be shown gross AND net of
    costs. Used only for diagnostics; the recommended portfolio's outcomes
    come from the authoritative ShadowPositionTracker.
    """

    def __init__(self, equity: float) -> None:
        self._equity = equity
        self._open: Dict[str, Tuple[float, float, float]] = {}  # sym -> (entry, w, atr_pct)

    def step(
        self,
        t: Any,
        selected: List[str],
        weights: Dict[str, float],
        prices: Dict[str, float],
        atr_pct: Dict[str, float] | None = None,
    ) -> Tuple[float, float, List[float], float]:
        """Rotate: realize exits at bar t, open new names.

        Returns (pnl, cost, r_list, turnover) where turnover is one-way
        rotation turnover in weight units (Σ|w| of closed names + Σ|w| of
        newly opened names; held names are never resized, so their Δw = 0).
        """
        atr_pct = atr_pct or {}
        pnl, cost, rs = 0.0, 0.0, []
        turnover = 0.0
        for sym, (ep, w, atr) in list(self._open.items()):
            if sym in selected:
                continue
            px = prices.get(sym)
            if px is None or not np.isfinite(px):
                continue
            p, r = self._realize(ep, w, atr, px)
            pnl += p
            if r is not None:
                rs.append(r)
            cost += COST_PER_SIDE_BPS / 1e4 * abs(w) * self._equity
            turnover += abs(w)
            self._open.pop(sym)
        for sym in selected:
            if sym in self._open:
                continue
            px = prices.get(sym)
            w = weights.get(sym, 0.0)
            if px is None or not np.isfinite(px) or w == 0.0:
                continue
            self._open[sym] = (float(px), float(w), float(atr_pct.get(sym, 0.0) or 0.0))
            cost += COST_PER_SIDE_BPS / 1e4 * abs(w) * self._equity
            turnover += abs(w)
        return pnl, cost, rs, turnover

    def close_all(self, prices: Dict[str, float]) -> Tuple[float, float, List[float], float]:
        pnl, cost, rs = 0.0, 0.0, []
        turnover = 0.0
        for sym, (ep, w, atr) in list(self._open.items()):
            px = prices.get(sym)
            if px is None or not np.isfinite(px):
                continue
            p, r = self._realize(ep, w, atr, px)
            pnl += p
            rs.append(r) if r is not None else None
            cost += COST_PER_SIDE_BPS / 1e4 * abs(w) * self._equity
            turnover += abs(w)
            self._open.pop(sym)
        return pnl, cost, rs, turnover

    def _realize(self, entry: float, w: float, atr_pct: float, exit_px: float) -> Tuple[float, float | None]:
        d = 1.0 if w > 0 else -1.0
        ret = d * (exit_px / entry - 1.0)
        pnl = ret * abs(w) * self._equity
        return pnl, (ret / atr_pct if atr_pct and atr_pct > 0 else None)


# ── Offline universe/signal reconstruction (parity-verified) ──────────


def _load_native_frame(symbol: str) -> pd.DataFrame | None:
    path = DATA_DIR / f"{symbol}m_D1.csv"
    if not path.exists():
        return None
    df = pd.read_csv(path, parse_dates=["time"])
    df = df.set_index("time").sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df[["open", "high", "low", "close"]]


def _invert_frames(f: pd.DataFrame) -> pd.DataFrame:
    return pd.DataFrame(
        {
            "open": 1.0 / f["open"],
            "high": 1.0 / f["low"],
            "low": 1.0 / f["high"],
            "close": 1.0 / f["close"],
        },
        index=f.index,
    )


def _ratio_frames(num: pd.DataFrame, den: pd.DataFrame) -> pd.DataFrame:
    idx = num.index.intersection(den.index)
    n, d = num.loc[idx], den.loc[idx]
    hi = np.maximum(n["high"] / d["low"], n["low"] / d["high"])
    lo = np.minimum(n["high"] / d["low"], n["low"] / d["high"])
    return pd.DataFrame(
        {"open": n["open"] / d["open"], "high": hi, "low": lo, "close": n["close"] / d["close"]},
        index=idx,
    )


def build_universe(allowed: Dict[str, str]) -> Dict[str, pd.DataFrame]:
    """Build per-symbol OHLC frames, synthesizing crosses from USD legs."""
    frames: Dict[str, pd.DataFrame] = {}
    for sym in allowed:
        if sym in NATIVE:
            f = _load_native_frame(sym)
            if f is not None:
                frames[sym] = f

    for sym in list(frames.keys()):
        if sym.endswith("USD") and sym[:-3] != "USD":
            inv = sym[:-3] + "_xUSD"
            if inv not in frames:
                frames[inv] = _invert_frames(frames[sym])
        elif sym.startswith("USD") and len(sym) > 3:
            inv = sym[3:] + "_xUSD"
            if inv not in frames:
                frames[inv] = _invert_frames(frames[sym])

    pending = [s for s in allowed if s not in frames]
    for _ in range(4):
        still = []
        for sym in pending:
            base, quote = sym[:3], sym[3:]
            f = None
            if quote == "USD":
                src = frames.get(base + "USD")
                if src is not None:
                    f = src.copy()
            elif base == "USD":
                src = frames.get(quote + "USD")
                if src is not None:
                    f = _invert_frames(src)
            else:
                nb = frames.get(base + "USD", frames.get(base + "_xUSD"))
                dq = frames.get(quote + "USD", frames.get(quote + "_xUSD"))
                if nb is not None and dq is not None:
                    f = _ratio_frames(nb, dq)
            if f is not None:
                frames[sym] = f
            else:
                still.append(sym)
        pending = still
        if not pending:
            break
    return frames


def replicate_signal(close_wide: pd.DataFrame) -> tuple[pd.DataFrame, pd.Series, pd.DataFrame]:
    """Byte-for-byte replica of the frozen R4 signal (parity-verified in
    scripts/audit/reconstruct.py C1). Returns (fin weights, regime_on, returns)."""
    returns_df = close_wide.pct_change()
    returns_df = returns_df.dropna(how="all").ffill().fillna(0)

    mom_12m = (1 + returns_df).rolling(LOOKBACK).apply(lambda x: x.prod() - 1, raw=True)
    mom_1m = (1 + returns_df).rolling(SKIP).apply(lambda x: x.prod() - 1, raw=True)
    sig = (mom_12m - mom_1m).dropna(how="all")

    rk = sig.rank(axis=1, pct=True)
    w = rk - 0.5

    avg_vol = returns_df.rolling(20).std().mean(axis=1) * np.sqrt(252)
    risk_median = avg_vol.expanding().median()
    regime = (avg_vol < risk_median).astype(float)

    vol60 = returns_df.rolling(VOL_LB).std() * np.sqrt(252)
    vol_scale = np.minimum(vol60 / 0.50, 1.0)

    fin = w.multiply(regime, axis=0) * vol_scale
    fin = fin.clip(-0.20, 0.20)
    if "BTCUSD" in fin.columns:
        fin["BTCUSD"] = fin["BTCUSD"].clip(-0.10, 0.10)

    regime_on = avg_vol < risk_median
    return fin, regime_on, returns_df


def _atr_pct_series(frame: pd.DataFrame, period: int = ATR_PERIOD) -> pd.Series:
    pc = frame["close"].shift(1)
    tr = pd.concat(
        [frame["high"] - frame["low"], (frame["high"] - pc).abs(), (frame["low"] - pc).abs()],
        axis=1,
    ).max(axis=1)
    return tr.rolling(period, min_periods=max(3, period // 2)).mean() / frame["close"]


def build_candidates(
    weights_at_t: pd.Series,
    eligible: List[str],
    asset_classes: Dict[str, str],
    vol_at_t: Dict[str, float],
    history_sufficient: Dict[str, bool],
    exposure: ExposureModel,
    feasible_override: bool = True,
) -> List[ShadowCandidate]:
    """Build the candidate universe exactly as R4 sees it (|w| > 0.005)."""
    ranked = sorted(
        [s for s in weights_at_t.index if s in eligible and abs(weights_at_t[s]) >= MIN_SIGNAL_WEIGHT],
        key=lambda s: -abs(weights_at_t[s]),
    )
    rank_map = {s: i + 1 for i, s in enumerate(ranked)}
    candidates: List[ShadowCandidate] = []
    for sym in ranked:
        w = float(weights_at_t[sym])
        candidates.append(
            ShadowCandidate(
                symbol=sym,
                weight=w,
                direction="LONG" if w > 0 else "SHORT",
                asset_class=asset_classes.get(sym, "other"),
                factor_group=get_factor_group(sym),
                feasible=feasible_override,
                r4_rank=rank_map[sym],
                annualized_vol=vol_at_t.get(sym),
                history_sufficient=history_sufficient.get(sym, True),
            )
        )
    return candidates


def print_comparison(decision: ShadowDecision) -> None:
    b = decision.baseline["metrics"]
    s = decision.selected["metrics"]
    e = decision.edge_metrics
    print("\n" + "═" * 60)
    print(f"SHADOW DECISION  {decision.signal_date}  [{decision.status}]")
    print("═" * 60)
    print(f"  Selected: {len(decision.selected['symbols'])}  (R4 baseline: {len(decision.baseline['symbols'])})")
    print(f"  {'metric':<28}{'R4':>14}{'shadow':>14}")
    rows = [
        ("gross edge", b["gross_edge"], s["gross_edge"]),
        ("avg pairwise corr", b["avg_pairwise_corr"], s["avg_pairwise_corr"]),
        ("max abs corr", b["max_abs_pairwise_corr"], s["max_abs_pairwise_corr"]),
        ("portfolio vol (ann)", b["portfolio_vol_annual"], s["portfolio_vol_annual"]),
        ("HHI", b["herfindahl"], s["herfindahl"]),
        ("eff positions", b["effective_positions"], s["effective_positions"]),
        ("div ratio", b["diversification_ratio"], s["diversification_ratio"]),
        (
            "max ccy exposure",
            b["exposure"]["max_currency_exposure"]["pct"],
            s["exposure"]["max_currency_exposure"]["pct"],
        ),
        (
            "max factor cluster",
            b["exposure"]["max_cluster_exposure"]["pct"],
            s["exposure"]["max_cluster_exposure"]["pct"],
        ),
    ]
    for name, r4, sh in rows:
        print(f"  {name:<28}{r4:>14.4f}{sh:>14.4f}")
    print(f"  edge retained: {e['edge_retained_pct']}%  top-signal: {e['top_signal_retention']}")
    print(f"  selected: {', '.join(decision.selected['symbols']) or '(none)'}")
    print(
        f"  rejected: {len(decision.candidates)} candidates, "
        f"reasons: {sorted({c['rejection_reason'] or 'selected' for c in decision.candidates})}"
    )


# ── Replay mode ───────────────────────────────────────────────────────


def run_replay(args: argparse.Namespace) -> int:
    config = load_config("production")
    allowed = dict(config.broker.allowed_symbols)
    eligible = [s for s, cls in allowed.items() if not cls.endswith("_excluded")]
    asset_classes = {s: cls.split("_")[0] for s, cls in allowed.items()}
    max_concurrent = int(config.capital.max_concurrent_positions)

    frames = build_universe(allowed)
    signal_syms = [s for s in sorted(frames) if s in allowed]
    cw = pd.DataFrame({s: frames[s]["close"] for s in signal_syms}).sort_index()
    fin, regime_on, returns_df = replicate_signal(cw)
    atr_pct = {s: _atr_pct_series(frames[s]) for s in signal_syms if s in frames}

    # Regime context (same series the frozen signal uses for its gate).
    avg_vol_series = returns_df.rolling(20).std().mean(axis=1) * np.sqrt(252)
    risk_median_series = avg_vol_series.expanding().median()

    start = pd.Timestamp(args.start) if args.start else fin.index[0]
    end = pd.Timestamp(args.end) if args.end else fin.index[-1]
    dates = [t for t in fin.index if start <= t <= end]

    selector = ShadowSelector(ShadowSelectorConfig())
    corr_model = CorrelationModel()
    exposure = ExposureModel()
    out_dir = args.out_dir or default_output_dir()
    recorder = ShadowDecisionRecorder(audit_dir=out_dir)
    tracker = ShadowPositionTracker(recorder, equity=EQUITY_FOR_SHADOW)

    size_trackers: Dict[int, _SizeTracker] = {}
    size_rows: List[Dict[str, Any]] = []
    baseline_tracker: _SizeTracker | None = None
    if args.size_breakdown:
        size_trackers = {n: _SizeTracker(equity=EQUITY_FOR_SHADOW) for n in SIZE_BREAKDOWN_NS}
        baseline_tracker = _SizeTracker(equity=EQUITY_FOR_SHADOW)

    decisions: List[ShadowDecision] = []
    n_regime_on = 0
    n_skipped = 0

    for t in dates:
        regime = bool(regime_on.loc[t])
        if not regime:
            n_skipped += 1
            continue
        n_regime_on += 1

        hist = returns_df.loc[:t]
        vol_at_t: Dict[str, float] = {}
        history_ok: Dict[str, bool] = {}
        for sym in signal_syms:
            series = hist[sym].dropna()
            history_ok[sym] = len(series) >= 30
            if len(series) >= VOL_LB:
                v = float(series.tail(VOL_LB).std() * np.sqrt(252))
                vol_at_t[sym] = v if v > 0 else 0.0

        weights_at_t = fin.loc[t]
        candidates = build_candidates(weights_at_t, eligible, asset_classes, vol_at_t, history_ok, exposure)
        snapshot = corr_model.build(hist, as_of=t)

        baseline_symbols = [c.symbol for c in candidates][:max_concurrent]
        cycle_id = f"R4S-{pd.Timestamp(t).date()}"
        vol_now = float(avg_vol_series.loc[t])
        vol_med = float(risk_median_series.loc[t])
        decision = selector.select(
            candidates,
            snapshot,
            baseline_symbols,
            cycle_id=cycle_id,
            decision_timestamp=datetime.now(UTC).isoformat(),
            signal_date=str(pd.Timestamp(t).date()),
            regime={
                "regime_on": True,
                "vol_now": vol_now,
                "vol_median": vol_med,
                "vol_ratio": vol_now / vol_med if vol_med > 0 else 0.0,
            },
        )
        recorder.record_decision(decision)
        decisions.append(decision)

        # Per-N realized tracking (diagnostics only; recommended portfolio
        # tracking above stays authoritative).
        if args.size_breakdown and decision.status == "SELECTED":
            chain_metrics = decision.chain_by_n
            for n in SIZE_BREAKDOWN_NS:
                if n not in chain_metrics:
                    continue
                syms = chain_metrics[n]["symbols"]
                wts = {s: decision.selected["weights"][s] for s in syms if s in decision.selected["weights"]}
                pnl, cost, rs, turnover = size_trackers[n].step(
                    t,
                    syms,
                    wts,
                    _row_prices(cw, t),
                    {s: float(atr_pct[s].loc[t]) if s in atr_pct and t in atr_pct[s].index else 0.0 for s in syms},
                )
                base_edge = decision.baseline["metrics"]["gross_edge"]
                size_rows.append(
                    {
                        "signal_date": decision.signal_date,
                        "size": n,
                        "gross_pnl": round(pnl, 6),
                        "cost": round(cost, 6),
                        "net_pnl": round(pnl - cost, 6),
                        "n_exits": len(rs),
                        "avg_r": round(float(np.mean(rs)), 4) if rs else None,
                        "turnover": round(turnover, 6),
                        "edge_retained_pct": round(100.0 * chain_metrics[n]["metrics"]["gross_edge"] / base_edge, 2)
                        if base_edge > 0
                        else None,
                        "portfolio_vol_annual": round(chain_metrics[n]["metrics"]["portfolio_vol_annual"], 6),
                        "max_abs_corr": round(chain_metrics[n]["metrics"]["max_abs_pairwise_corr"], 6),
                    }
                )

            # R4-20 control column: the frozen R4 baseline portfolio, realized
            # under the SAME cost/rotation conventions as the shadow chain so
            # D4 compares apples to apples. edge_retained_pct is definitionally
            # 100% (it IS the baseline).
            assert baseline_tracker is not None
            base_syms = decision.baseline["symbols"]
            base_wts = {s: decision.baseline["weights"][s] for s in base_syms if s in decision.baseline["weights"]}
            bp, bc, brs, bturn = baseline_tracker.step(t, base_syms, base_wts, _row_prices(cw, t))
            size_rows.append(
                {
                    "signal_date": decision.signal_date,
                    "size": BASELINE_SIZE,
                    "gross_pnl": round(bp, 6),
                    "cost": round(bc, 6),
                    "net_pnl": round(bp - bc, 6),
                    "n_exits": len(brs),
                    "avg_r": round(float(np.mean(brs)), 4) if brs else None,
                    "turnover": round(bturn, 6),
                    "edge_retained_pct": 100.0,
                    "portfolio_vol_annual": round(decision.baseline["metrics"]["portfolio_vol_annual"], 6),
                    "max_abs_corr": round(decision.baseline["metrics"]["max_abs_pairwise_corr"], 6),
                }
            )

        # Rotate shadow positions: close what left the selection, open the rest.
        # Prices at the decision bar cover ALL signal symbols — both the newly
        # selected and any being rotated out need a close to mark against.
        selected = decision.selected["symbols"]
        row = cw.loc[t]
        prices = {s: float(row[s]) for s in cw.columns if np.isfinite(row[s])}
        exits = [s for s in tracker.open_positions() if s not in selected]
        tracker.close_positions(exits, prices, t, cycle_id, decision.signal_date, "rotated_out")
        atr_now = {s: float(atr_pct[s].loc[t]) if s in atr_pct and t in atr_pct[s].index else 0.0 for s in selected}
        tracker.open_cycle(selected, decision.selected["weights"], prices, atr_now, cycle_id, decision.signal_date, t)

    # Close any positions still open at the end of the observation window.
    end_prices = {s: float(cw[s].iloc[-1]) for s in tracker.open_positions() if s in cw.columns}
    tracker.close_all(end_prices, fin.index[-1], "R4S-END", str(fin.index[-1].date()), "end_of_observation")

    # Close per-N trackers and persist the size-breakdown evidence.
    if args.size_breakdown:
        end_row = cw.iloc[-1]
        end_px = {s: float(end_row[s]) for s in cw.columns if np.isfinite(end_row[s])}
        for n in SIZE_BREAKDOWN_NS:
            pnl, cost, rs, turnover = size_trackers[n].close_all(end_px)
            size_rows.append(
                {
                    "signal_date": "END",
                    "size": n,
                    "gross_pnl": round(pnl, 6),
                    "cost": round(cost, 6),
                    "net_pnl": round(pnl - cost, 6),
                    "n_exits": len(rs),
                    "avg_r": round(float(np.mean(rs)), 4) if rs else None,
                    "turnover": round(turnover, 6),
                    "edge_retained_pct": None,
                    "portfolio_vol_annual": None,
                    "max_abs_corr": None,
                }
            )
        assert baseline_tracker is not None
        bp, bc, brs, bturn = baseline_tracker.close_all(end_px)
        size_rows.append(
            {
                "signal_date": "END",
                "size": BASELINE_SIZE,
                "gross_pnl": round(bp, 6),
                "cost": round(bc, 6),
                "net_pnl": round(bp - bc, 6),
                "n_exits": len(brs),
                "avg_r": round(float(np.mean(brs)), 4) if brs else None,
                "turnover": round(bturn, 6),
                "edge_retained_pct": None,
                "portfolio_vol_annual": None,
                "max_abs_corr": None,
            }
        )
        with open(Path(out_dir) / "shadow_portfolio_size_breakdown.jsonl", "w") as f:
            for row in size_rows:
                f.write(json.dumps(row) + "\n")
        print(f"  size breakdown: {Path(out_dir) / 'shadow_portfolio_size_breakdown.jsonl'}")

    # Summary
    selected_counts = [len(d.selected["symbols"]) for d in decisions if d.status == "SELECTED"]
    retained = [
        d.edge_metrics["edge_retained_pct"] for d in decisions if d.edge_metrics["edge_retained_pct"] is not None
    ]
    outcomes = recorder.read_outcomes()
    pnls = [o["shadow_pnl"] for o in outcomes if o.get("shadow_pnl") is not None and np.isfinite(o["shadow_pnl"])]
    rs = [o["shadow_r"] for o in outcomes if o.get("shadow_r") is not None and np.isfinite(o["shadow_r"])]

    print("\n" + "█" * 60)
    print("R4-S REPLAY SUMMARY")
    print("█" * 60)
    print(f"  window: {start.date()} → {end.date()}  (trading days in window: {len(dates)})")
    print(f"  regime-on decision days: {n_regime_on}   regime-off skipped: {n_skipped}")
    print(
        f"  shadow decisions recorded: {len(decisions)}  (no_portfolio: "
        f"{sum(1 for d in decisions if d.status != 'SELECTED')})"
    )
    if selected_counts:
        print(
            f"  avg shadow size: {np.mean(selected_counts):.2f}  (range {min(selected_counts)}–{max(selected_counts)})"
        )
    if retained:
        print(f"  avg edge retained: {np.mean(retained):.1f}%  (min {min(retained):.1f}%, max {max(retained):.1f}%)")
    if outcomes:
        line = f"  shadow outcomes: {len(outcomes)}"
        if pnls:
            line += f"  avg PnL proxy {np.mean(pnls):+.2f}  total {sum(pnls):+.2f}"
        if rs:
            line += f"  avg R {np.mean(rs):+.3f}  positive R {sum(1 for r in rs if r > 0)}/{len(rs)}"
        print(line)
    else:
        print("  shadow outcomes: 0")
    print(f"  decisions: {recorder.decisions_path}")
    print(f"  outcomes:  {recorder.outcomes_path}")

    for d in decisions[:3]:
        print_comparison(d)
    return 0


# ── Observe mode (read-only MT5) ──────────────────────────────────────


def _load_loop_module():
    spec = importlib.util.spec_from_file_location("r4_rebalance_loop", REPO / "scripts" / "r4_rebalance_loop.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules["r4_rebalance_loop"] = mod
    spec.loader.exec_module(mod)
    return mod


def run_observe(args: argparse.Namespace) -> int:
    try:
        from mt5linux import MetaTrader5
    except ImportError:
        print("observe mode requires an MT5 connection on the trading host (mt5linux).")
        print("Use --replay for offline shadow construction.")
        return 2

    loop = _load_loop_module()
    mt5 = MetaTrader5
    if not mt5.initialize():
        print(f"MT5 initialize failed: {mt5.last_error()}")
        return 2

    try:
        data = loop.fetch_d1_data(mt5, loop.R4_SYMBOLS)
        if not data:
            print("no market data available")
            return 2
        target_weights, diag, returns_df = loop.compute_r4_signal(data)
        if not diag["regime_on"]:
            print(
                f"regime OFF — R4 skips this cycle; shadow observes nothing "
                f"(vol {diag['vol_now']:.3f} vs median {diag['vol_median']:.3f})"
            )
            return 0

        prices: Dict[str, float] = {}
        contract_sizes: Dict[str, float] = {}
        min_volumes: Dict[str, float] = {}
        for sym in loop.R4_SYMBOLS:
            tick = mt5.symbol_info_tick(sym)
            info = mt5.symbol_info(sym)
            if tick and info:
                prices[sym] = tick.ask
                contract_sizes[sym] = info.trade_contract_size
                min_volumes[sym] = info.volume_min

        equity = float(mt5.account_info().equity)
        # Frozen R4 baseline selection via the loop's own generator (no orders).
        orders = loop.generate_orders(target_weights, {}, prices, contract_sizes, min_volumes, equity, None)
        baseline_symbols = [o[0] for o in orders if "rotated out" not in o[3]]

        vol_at_t: Dict[str, float] = {}
        history_ok: Dict[str, bool] = {}
        for sym in loop.R4_SYMBOLS:
            if sym in returns_df.columns:
                series = returns_df[sym].dropna()
                history_ok[sym] = len(series) >= 30
                if len(series) >= loop.VOL_LOOKBACK:
                    v = float(series.tail(loop.VOL_LOOKBACK).std() * np.sqrt(252))
                    vol_at_t[sym] = v if v > 0 else 0.0

        exposure = ExposureModel()
        candidates = build_candidates(
            target_weights,
            loop.ELIGIBLE_SYMBOLS,
            loop.ASSET_CLASSES,
            vol_at_t,
            history_ok,
            exposure,
            feasible_override=False,
        )
        # Feasibility from real symbol specs (mirrors generate_orders).
        for c in candidates:
            price = prices.get(c.symbol, 0.0)
            cs = contract_sizes.get(c.symbol, 0.0)
            min_vol = min_volumes.get(c.symbol, 0.01)
            if price <= 0 or cs <= 0:
                c.feasible = False
            elif min_vol * price * cs > loop.MAX_POSITION_USD:
                c.feasible = False
            else:
                c.min_lot_cost = round(min_vol * price * cs, 2)

        now = datetime.now(UTC)
        snapshot = CorrelationModel().build(returns_df, as_of=pd.Timestamp(now))
        decision = ShadowSelector().select(
            candidates,
            snapshot,
            baseline_symbols,
            cycle_id=f"R4S-{now:%Y%m%d-%H%M}",
            decision_timestamp=now.isoformat(),
            signal_date=diag["signal_date"],
        )
        out_dir = args.out_dir or default_output_dir()
        recorder = ShadowDecisionRecorder(audit_dir=out_dir)
        recorder.record_decision(decision)
        print_comparison(decision)
        print(f"  recorded → {recorder.decisions_path}")
        return 0
    finally:
        mt5.shutdown()


# ── Status mode ───────────────────────────────────────────────────────


def run_status(args: argparse.Namespace) -> int:
    out_dir = args.out_dir or default_output_dir()
    recorder = ShadowDecisionRecorder(audit_dir=out_dir)
    decisions = recorder.read_decisions()
    outcomes = recorder.read_outcomes()
    print(f"shadow decisions: {len(decisions)}  ({recorder.decisions_path})")
    print(f"shadow outcomes:  {len(outcomes)}  ({recorder.outcomes_path})")
    if decisions:
        statuses: Dict[str, int] = {}
        for d in decisions:
            statuses[d.get("status", "?")] = statuses.get(d.get("status", "?"), 0) + 1
        print(f"status breakdown: {statuses}")
        dates = [d.get("signal_date") for d in decisions]
        print(f"first/last signal date: {dates[0]} / {dates[-1]}")
        sizes = [len(d.get("selected", {}).get("symbols", [])) for d in decisions if d.get("status") == "SELECTED"]
        if sizes:
            print(f"avg shadow size (selected): {np.mean(sizes):.2f}  range {min(sizes)}–{max(sizes)}")
    if outcomes:
        pnls = [o["shadow_pnl"] for o in outcomes if o.get("shadow_pnl") is not None]
        rs = [o["shadow_r"] for o in outcomes if o.get("shadow_r") is not None]
        if pnls:
            print(f"avg outcome PnL proxy: {np.mean(pnls):+.2f}  total {sum(pnls):+.2f}")
        if rs:
            print(f"avg R: {np.mean(rs):+.3f}  positive R: {sum(1 for r in rs if r > 0)}/{len(rs)}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="R4-S shadow portfolio constructor (SHADOW ONLY)")
    parser.add_argument("--replay", action="store_true", help="offline replay over local D1 history")
    parser.add_argument("--observe", action="store_true", help="live soak observation (read-only MT5)")
    parser.add_argument("--status", action="store_true", help="summarize recorded shadow evidence")
    parser.add_argument("--start", default="", help="replay start date YYYY-MM-DD")
    parser.add_argument("--end", default="", help="replay end date YYYY-MM-DD")
    parser.add_argument("--out-dir", default="", help="shadow evidence directory (default reports/r4_loop)")
    parser.add_argument(
        "--fresh",
        action="store_true",
        help="truncate OWN shadow evidence files before running (never touches R4 evidence)",
    )
    parser.add_argument(
        "--size-breakdown",
        action="store_true",
        help="diagnostic: track realized outcomes per selection size (1/2/4/6/8) incl. 10bps/side costs",
    )
    args = parser.parse_args()
    if args.fresh:
        for name in ("shadow_portfolio_decisions.jsonl", "shadow_portfolio_outcomes.jsonl"):
            p = Path(args.out_dir or default_output_dir()) / name
            if p.exists():
                p.unlink()
                print(f"--fresh: cleared {p}")

    if args.status:
        return run_status(args)
    if args.observe:
        return run_observe(args)
    if args.replay:
        return run_replay(args)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
