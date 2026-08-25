"""Campaign 8 — TF-003 Independent Confirmation with Corrected Cost Accounting.

Single question (pre-registered, no new hypotheses, no tuning):

    Does TF-003 (quote-flow-extreme reversal, HP=1) survive independently
    when transaction costs are correctly incorporated INTO the per-bar
    return series?

STAGE A — CORRECTED ENGINE (locked by unit tests before any result):
    signal → position → per-bar gross return
          → cost charged on EVERY position flip
          → NET per-bar return → Sharpe/DD/economics.
    Costs are one-way charges applied at each flip. BASE = 6.5 bps,
    ADVERSE = 11 bps (equivalent to the C4–C7 round-trip conventions
    of 13/22 bps, now correctly split across entry and exit flips).

STAGE B — CONFIRMATION (frozen definition, no parameter changes):
    B1: full-window re-run with corrected accounting (apples-to-apples
        correction measurement vs Campaign 7).
    B2: strict chronological holdout — final 20% of the timeline evaluated
        alone (no statistic from this segment informed anything).
    LIMITATION (recorded honestly): the tick snapshot ends at the time of
        discovery, so a true out-of-sample FORWARD leg is not yet possible.
        Forward confirmation remains OPEN and must be completed on freshly
        collected ticks before any promotion beyond research status.

PRE-REGISTERED CONFIRMATION GATES (all must pass; fail-closed):
    - corrected net Sharpe ≥ 0.30 (base AND adverse costs)
    - OOS (holdout) net Sharpe > 0
    - WF consistency ≥ 70%
    - permutation p ≤ 0.05 (on the corrected net series)
    - ≥ 6/8 instruments net-positive
    - no catastrophic drawdown (corrected max DD > −25%)
    - no single-session dependency (all sessions net-positive OR no session
      below −0.5 Sharpe)

STAGE C — RISK TRANSFORMATION: explicitly NOT executed here. Only unlocked
if Stage B confirms.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd

from eigencapital.research.intraday.campaign4_15m import UNIVERSE
from eigencapital.research.intraday.campaign7_micro import (
    DATA_DIR,
    SIGNALS,
    TRADING_DAYS_PER_YEAR,
    BARS_PER_TRADING_DAY,
    _threshold,
    regime_analysis,
)
from eigencapital.research.intraday.campaign5_30m import classify

# ── Constants ───────────────────────────────────────────────────────────

PRIMARY_HID = "TF-003"
PRIMARY_SIGNAL = "sig_flow_fade"
PRIMARY_HP = 1                     # 5 minutes — as discovered, frozen
DIAGNOSTIC_HPS = [2]               # reported only, never gate-relevant

COST_ONE_WAY_BASE = 13 / 2 / 10000     # 6.5 bps
COST_ONE_WAY_ADVERSE = 22 / 2 / 10000  # 11 bps

HOLDOUT_FRACTION = 0.20            # strict chronological tail
WF_N_FOLDS = 5

GATES = {
    "net_sharpe_min": 0.30,
    "wf_consistency_min": 0.70,
    "perm_p_max": 0.05,
    "min_instruments_positive": 6,
    "max_dd_limit": -0.25,
    "session_floor": -0.50,
}

REPORT_JSON = "reports/campaign8_tf003_confirmation.json"
REPORT_MD = "reports/campaign8_tf003_confirmation.md"


# ═══════════════════════════════════════════════════════════════════════
# STAGE A — CORRECTED ENGINE
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class NetResult:
    gross_sharpe: float
    net_sharpe: float
    total_gross_ret: float
    total_net_ret: float
    total_cost_drag: float
    n_flips: int
    exposure: float                 # fraction of bars with nonzero position
    max_dd: float                   # on NET returns
    worst_bar: float                # tail loss, single worst NET bar
    avg_cost_per_flip_bps: float


def bt_corrected(
    df: pd.DataFrame,
    sig: pd.Series,
    hp: int,
    cost_one_way: float,
) -> NetResult:
    """Corrected accounting: costs enter the per-bar return series."""
    pos = np.sign(sig).shift(1).fillna(0)
    fwd = df["mid_close"].pct_change(hp).shift(-hp)

    gross = pos * fwd
    flips = pos.diff().abs().fillna(0)          # charge at every position change
    net = gross - flips * cost_one_way

    g_clean = gross.dropna()
    n_clean = net.dropna()
    ann = np.sqrt(TRADING_DAYS_PER_YEAR * BARS_PER_TRADING_DAY / hp)

    def _sharpe(s: pd.Series) -> float:
        return float(s.mean() / s.std() * ann) if len(s) > 30 and s.std() > 0 else 0.0

    def _maxdd(s: pd.Series) -> float:
        if s.empty:
            return 0.0
        cum = (1 + s).cumprod()
        return float(((cum - cum.cummax()) / cum.cummax()).min())

    n_flips = int(flips.sum())
    total_cost = float((flips * cost_one_way).sum())
    total_gross = float(g_clean.sum())
    total_net = float(n_clean.sum())

    return NetResult(
        gross_sharpe=_sharpe(g_clean),
        net_sharpe=_sharpe(n_clean),
        total_gross_ret=total_gross,
        total_net_ret=total_net,
        total_cost_drag=total_cost,
        n_flips=n_flips,
        exposure=float((pos != 0).mean()),
        max_dd=_maxdd(n_clean),
        worst_bar=float(n_clean.min()) if len(n_clean) else 0.0,
        avg_cost_per_flip_bps=(
            cost_one_way * 10000 if n_flips else 0.0
        ),
    )


def wf_validate_corrected(
    df: pd.DataFrame,
    func,
    hp: int,
    cost: float,
    n_folds: int = WF_N_FOLDS,
) -> Tuple[float, float]:
    fold_size = len(df) // (n_folds + 1)
    sharpes: List[float] = []
    for i in range(n_folds):
        s = fold_size * (i + 1)
        e = min(s + fold_size, len(df))
        if e - s < 100:
            continue
        try:
            sig = _threshold(func(df.iloc[s:e]))
            r = bt_corrected(df.iloc[s:e], sig, hp, cost)
            sharpes.append(r.net_sharpe)
        except Exception:
            sharpes.append(0.0)
    if not sharpes:
        return 0.0, 0.0
    cons = sum(1 for x in sharpes if x > 0) / len(sharpes)
    return cons, float(np.mean(sharpes))


def permutation_test_corrected(
    df: pd.DataFrame,
    func,
    hp: int,
    cost: float,
    n_permutations: int = 200,
) -> float:
    """Permutation test on the CORRECTED net series."""
    try:
        real_sig = _threshold(func(df))
        r = bt_corrected(df, real_sig, hp, cost)
        real_sharpe = r.net_sharpe
        pos = np.sign(real_sig).shift(1).fillna(0)
    except Exception:
        return 1.0
    if real_sharpe <= 0:
        return 1.0

    fwd = df["mid_close"].pct_change(hp).shift(-hp)
    cnt = 0
    for _ in range(n_permutations):
        shuffled_pos = pd.Series(
            pos.sample(frac=1.0, replace=False).values, index=df.index
        )
        flips = shuffled_pos.diff().abs().fillna(0)
        net = shuffled_pos * fwd - flips * cost
        clean = net.dropna()
        if len(clean) < 30 or clean.std() == 0:
            continue
        ann = np.sqrt(TRADING_DAYS_PER_YEAR * BARS_PER_TRADING_DAY / hp)
        ps = float(clean.mean() / clean.std() * ann)
        if ps >= real_sharpe:
            cnt += 1
    return cnt / n_permutations


# ═══════════════════════════════════════════════════════════════════════
# STAGE B — GATES AND RUNNER
# ═══════════════════════════════════════════════════════════════════════

@dataclass
class ConfirmationReport:
    verdict: str = "NOT_CONFIRMED"
    failed_gates: List[str] = field(default_factory=list)
    passed_gates: List[str] = field(default_factory=list)
    full_window: Optional[dict] = None
    holdout: Optional[dict] = None
    per_instrument: Dict[str, dict] = field(default_factory=dict)
    diagnostics: List[dict] = field(default_factory=list)


def _gate_check(
    full: NetResult,
    wf_cons: float,
    perm_p: float,
    sym_results: Dict[str, NetResult],
    session_sharpes: Dict[str, float],
) -> Tuple[List[str], List[str]]:
    """Evaluate pre-registered gates. Returns (failed, passed)."""
    failed, passed = [], []

    if full.net_sharpe >= GATES["net_sharpe_min"]:
        passed.append(f"net_sharpe {full.net_sharpe:.2f} ≥ {GATES['net_sharpe_min']}")
    else:
        failed.append(f"net_sharpe {full.net_sharpe:.2f} < {GATES['net_sharpe_min']}")

    if wf_cons >= GATES["wf_consistency_min"]:
        passed.append(f"wf_consistency {wf_cons:.0%} ≥ {GATES['wf_consistency_min']}")
    else:
        failed.append(f"wf_consistency {wf_cons:.0%} < {GATES['wf_consistency_min']}")

    if perm_p <= GATES["perm_p_max"]:
        passed.append(f"permutation p {perm_p:.3f} ≤ {GATES['perm_p_max']}")
    else:
        failed.append(f"permutation p {perm_p:.3f} > {GATES['perm_p_max']}")

    npos = sum(1 for r in sym_results.values() if r.net_sharpe > 0)
    need = GATES["min_instruments_positive"]
    if npos >= need:
        passed.append(f"instruments positive {npos}/8 ≥ {need}")
    else:
        failed.append(f"instruments positive {npos}/8 < {need}")

    if full.max_dd > GATES["max_dd_limit"]:
        passed.append(f"max_dd {full.max_dd:.1%} > {GATES['max_dd_limit']}")
    else:
        failed.append(f"max_dd {full.max_dd:.1%} ≤ {GATES['max_dd_limit']}")

    bad_sessions = {s: v for s, v in session_sharpes.items()
                    if v < GATES["session_floor"]}
    if not bad_sessions:
        passed.append("no session below floor "
                      f"{GATES['session_floor']}")
    else:
        failed.append(f"sessions below floor: {bad_sessions}")

    return failed, passed


def run(data_dir: str = DATA_DIR) -> ConfirmationReport:
    func = SIGNALS[PRIMARY_SIGNAL]
    rep = ConfirmationReport()

    data: Dict[str, pd.DataFrame] = {}
    for s in UNIVERSE:
        p = os.path.join(data_dir, f"{s}_M5micro.csv")
        if os.path.exists(p):
            data[s] = pd.read_csv(p, parse_dates=["time"])
            print(f"  Loaded {s}: {len(data[s])} micro bars")
    if not data:
        print("ERROR: no microstructure bars")
        rep.verdict = "INCONCLUSIVE"
        rep.failed_gates.append("no_data")
        return rep

    anchor_name = next((s for s in ["EURUSDm", "XAUUSDm"] if s in data),
                       list(data)[0])
    anchor = data[anchor_name]

    # ── Full window, base + adverse ────────────────────────────────────
    print("\n=== STAGE B1: full window (corrected accounting) ===")
    sig_anchor = _threshold(func(anchor))
    full_base = bt_corrected(anchor, sig_anchor, PRIMARY_HP, COST_ONE_WAY_BASE)
    full_adv = bt_corrected(anchor, sig_anchor, PRIMARY_HP, COST_ONE_WAY_ADVERSE)
    print(f"  anchor={anchor_name}: gross={full_base.gross_sharpe:+.2f} "
          f"net_base={full_base.net_sharpe:+.2f} net_adv={full_adv.net_sharpe:+.2f} "
          f"flips={full_base.n_flips:,} DD(net)={full_base.max_dd:.1%}")

    # Adverse must also clear the Sharpe gate
    if full_adv.net_sharpe < GATES["net_sharpe_min"]:
        rep.failed_gates.append(
            f"adverse-cost net Sharpe {full_adv.net_sharpe:.2f} < "
            f"{GATES['net_sharpe_min']}"
        )
    else:
        rep.passed_gates.append(
            f"adverse-cost net Sharpe {full_adv.net_sharpe:.2f}"
        )

    # ── Walk-forward + permutation (corrected) ─────────────────────────
    wf_cons, wf_oos = wf_validate_corrected(
        anchor, func, PRIMARY_HP, COST_ONE_WAY_BASE
    )
    perm_p = permutation_test_corrected(
        anchor, func, PRIMARY_HP, COST_ONE_WAY_BASE, n_permutations=200
    )
    print(f"  WF consistency={wf_cons:.0%} (OOS {wf_oos:+.2f}) "
          f"perm_p={perm_p:.3f}")
    rep.full_window = {
        **full_base.__dict__,
        "net_adverse_sharpe": full_adv.net_sharpe,
        "anchor": anchor_name,
        "wf_consistency": wf_cons,
        "wf_oos_sharpe": wf_oos,
        "permutation_p": perm_p,
    }

    # ── Strict chronological holdout ───────────────────────────────────
    print("\n=== STAGE B2: chronological holdout ===")
    cut = int(len(anchor) * (1 - HOLDOUT_FRACTION))
    ho_sig = _threshold(func(anchor.iloc[cut:]))
    holdout = bt_corrected(
        anchor.iloc[cut:], ho_sig, PRIMARY_HP, COST_ONE_WAY_BASE
    )
    print(f"  holdout ({HOLDOUT_FRACTION:.0%} tail): net={holdout.net_sharpe:+.2f} "
          f"DD={holdout.max_dd:.1%}")
    rep.holdout = holdout.__dict__
    if holdout.net_sharpe > 0:
        rep.passed_gates.append(f"holdout net Sharpe {holdout.net_sharpe:+.2f} > 0")
    else:
        rep.failed_gates.append(
            f"holdout net Sharpe {holdout.net_sharpe:+.2f} ≤ 0"
        )

    # ── Per-instrument (base costs) ────────────────────────────────────
    print("\n=== Per-instrument ===")
    for s, df in sorted(data.items()):
        try:
            sig = _threshold(func(df))
            r = bt_corrected(df, sig, PRIMARY_HP, COST_ONE_WAY_BASE)
            rep.per_instrument[s] = r.__dict__
            print(f"  {s}: net={r.net_sharpe:+.2f} DD={r.max_dd:.1%} "
                  f"flips={r.n_flips:,}")
        except Exception as e:
            print(f"  {s}: FAILED ({e})")

    # ── Session decomposition (corrected, anchor) ──────────────────────
    pos = np.sign(sig_anchor).shift(1).fillna(0)
    fwd = anchor["mid_close"].pct_change(PRIMARY_HP).shift(-PRIMARY_HP)
    flips = pos.diff().abs().fillna(0)
    net_series = (pos * fwd - flips * COST_ONE_WAY_BASE).dropna()
    ann = np.sqrt(TRADING_DAYS_PER_YEAR * BARS_PER_TRADING_DAY / PRIMARY_HP)
    from eigencapital.research.intraday.campaign4_15m import SESSION_BOUNDS_UTC
    hours = pd.to_datetime(anchor.loc[net_series.index, "time"]).dt.hour
    session_sharpes: Dict[str, float] = {}
    for name, (lo, hi) in SESSION_BOUNDS_UTC.items():
        r_ = net_series[(hours >= lo) & (hours < hi)]
        if len(r_) > 50 and r_.std() > 0:
            session_sharpes[name] = float(r_.mean() / r_.std() * ann)

    # ── Gate evaluation ────────────────────────────────────────────────
    failed, passed = _gate_check(
        full_base, wf_cons, perm_p, rep.per_instrument, session_sharpes
    )
    rep.failed_gates.extend(failed)
    rep.passed_gates.extend(passed)
    rep.verdict = "CONFIRMED" if not rep.failed_gates else "NOT_CONFIRMED"

    # ── Diagnostics (non-gating): other horizons ────────────────────────
    for hp in DIAGNOSTIC_HPS:
        d = bt_corrected(anchor, sig_anchor, hp, COST_ONE_WAY_BASE)
        rep.diagnostics.append({"hp_bars": hp, **d.__dict__})

    return rep


# ═══════════════════════════════════════════════════════════════════════
# REPORTS
# ═══════════════════════════════════════════════════════════════════════

def write_reports(rep: ConfirmationReport) -> None:
    now = time.strftime("%Y-%m-%d %H:%M UTC")
    os.makedirs("reports", exist_ok=True)

    lines = [
        "# CAMPAIGN 8 — TF-003 INDEPENDENT CONFIRMATION",
        "## with Corrected Net-Return / Cost Accounting",
        "",
        f"**Generated:** {now}",
        f"**Mechanism:** {PRIMARY_HID} quote-flow-extreme reversal "
        f"(HP={PRIMARY_HP}, frozen)",
        f"**Cost model:** one-way per flip — base {COST_ONE_WAY_BASE*10000:.1f}bps, "
        f"adverse {COST_ONE_WAY_ADVERSE*10000:.1f}bps",
        "**Engine:** Stage-A corrected (costs inside the return series); "
        "locked by unit tests before any result was computed",
        "",
        "---", "",
        f"# CONFIRMATION VERDICT: **{rep.verdict}**", "",
        "**Failed gates:**",
        *( [f"- ❌ {g}" for g in rep.failed_gates] or ["- none"] ),
        "",
        "**Passed gates:**",
        *[f"- ✅ {g}" for g in rep.passed_gates],
        "",
        "---", "",
        "## FULL WINDOW (corrected)", "",
    ]
    fw = rep.full_window or {}
    lines += [
        f"- Gross Sharpe: {fw.get('gross_sharpe', 0):+.2f} | "
        f"Net (base): {fw.get('net_sharpe', 0):+.2f} | "
        f"Net (adverse): {fw.get('net_adverse_sharpe', 0):+.2f}",
        f"- Flips: {fw.get('n_flips', 0):,} · exposure "
        f"{fw.get('exposure', 0):.0%} · cost drag {fw.get('total_cost_drag', 0):.4f}",
        f"- Max DD (net): {fw.get('max_dd', 0):.1%} · worst bar "
        f"{fw.get('worst_bar', 0):.4%}",
        f"- WF consistency: {fw.get('wf_consistency', 0):.0%} "
        f"(OOS {fw.get('wf_oos_sharpe', 0):+.2f}) · permutation p "
        f"{fw.get('permutation_p', 1):.3f}",
        "",
        "## CHRONOLOGICAL HOLDOUT (final 20%)", "",
    ]
    ho = rep.holdout or {}
    lines += [
        f"- Net Sharpe: {ho.get('net_sharpe', 0):+.2f} · "
        f"Max DD: {ho.get('max_dd', 0):.1%} · "
        f"flips {ho.get('n_flips', 0):,}", "",
        "## PER-INSTRUMENT (net, base costs)", "",
    ]
    lines += [
        f"- {s}: net {r.get('net_sharpe', 0):+.2f} · DD {r.get('max_dd', 0):.1%}"
        for s, r in sorted(rep.per_instrument.items())
    ]
    lines += [
        "", "## HONEST LIMITATIONS", "",
        "- The tick snapshot ends at discovery time; the forward leg of "
        "confirmation is OPEN. Freshly collected ticks must independently "
        "reproduce these results before any status promotion.",
        "- Broker-specific quote flow; conclusions do not generalize to "
        "institutional order flow.", "",
        "## DECISION", "",
    ]
    if rep.verdict == "CONFIRMED":
        lines.append(
            "Stage C (risk transformation campaign) is now UNLOCKED as a "
            "separate pre-registered effort. The raw expression still fails "
            "promotion rules until forward confirmation completes."
        )
    else:
        lines.append(
            "TF-003 is FROZEN as a fragile lead. No risk transformation may "
            "proceed on an unconfirmed effect."
        )

    with open(REPORT_MD, "w") as f:
        f.write("\n".join(lines) + "\n")

    payload = {
        "campaign": "campaign8_tf003_confirmation",
        "verdict": rep.verdict,
        "passed_gates": rep.passed_gates,
        "failed_gates": rep.failed_gates,
        "full_window": rep.full_window,
        "holdout": rep.holdout,
        "per_instrument": rep.per_instrument,
        "diagnostics": rep.diagnostics,
        "generated": now,
    }
    with open(REPORT_JSON, "w") as f:
        json.dump(payload, f, indent=2, default=str)

    print(f"\nReports written: {REPORT_MD}, {REPORT_JSON}")
    print(f"\nFINAL CONFIRMATION VERDICT: {rep.verdict}")


if __name__ == "__main__":
    import sys
    rep = run(sys.argv[1] if len(sys.argv) > 1 else DATA_DIR)
    write_reports(rep)
