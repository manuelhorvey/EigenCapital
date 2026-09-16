"""R4 Rebalance-Frequency Research CLI (EXP-000002) — offline ablation runner.

SHADOW-ONLY / RESEARCH-ONLY. Never connects to a broker, never submits
orders, never writes canonical R4 evidence files.

Runs the pre-registered rebalance-policy matrix (R4-REB-*) over the SAME
frozen R4 signal stream and produces the Section-30 comparison report:

    1. Loads the parity-verified offline universe + signal reconstruction
       (scripts/r4_shadow_portfolio.py build_universe / replicate_signal —
       C1 parity-tested against compute_r4_signal). The signal is computed
       ONCE; every policy consumes the identical target stream.
    2. For each decision date T, the target uses bars ≤ T only (no
       look-ahead); trades price at T's close.
    3. Applies the same transaction-cost model to every policy
       (transaction_cost_bps + slippage_bps from the frozen config), then
       re-runs the cost ladder (base/×1.25/×1.5/×2) uniformly.
    4. Registers/updates the experiment in the ExperimentRepository with
       trial metadata covering the whole pre-registered matrix.

Usage:
    python scripts/r4_rebalance_research.py --start 2025-01-01 --end 2026-09-15
    python scripts/r4_rebalance_research.py --start 2025-01-01 --register-only
    python scripts/r4_rebalance_research.py --start 2025-01-01 --out reports/rebalance_research
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import math
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "src"))

import pandas as pd  # noqa: E402

from eigencapital.config import load_config  # noqa: E402
from eigencapital.live.rebalance_policy import (  # noqa: E402
    THRESHOLD_CANDIDATES,
    experiment_matrix,
)
from eigencapital.research.experiments.registry import ExperimentRegistry  # noqa: E402
from eigencapital.research.experiments.repository import ExperimentRepository  # noqa: E402
from eigencapital.research.rebalance import ReplayConfig, run_policy_matrix  # noqa: E402

EXPERIMENT_ID = "EXP-000002"
HYPOTHESIS_ID = "HYP-R4-REB-001"
TRIAL_GROUP = "R4-REB-MATRIX-V1"
DEFAULT_OUT = "reports/rebalance_research"
REGISTRY_PATH = "research/experiments/registry"


def _load_reconstruction():
    """Import the parity-verified offline reconstruction (read-only)."""
    spec = importlib.util.spec_from_file_location(
        "r4_shadow_portfolio_mod", REPO / "scripts" / "r4_shadow_portfolio.py"
    )
    mod = importlib.util.module_from_spec(spec)
    sys.modules["r4_shadow_portfolio_mod"] = mod
    spec.loader.exec_module(mod)
    return mod


def build_signal_panels(config) -> tuple[pd.DataFrame, pd.DataFrame, Dict[str, Any]]:
    """One frozen signal stream for every policy (Section 14).

    Returns (weights_panel, closes, provenance). weights_panel[t, sym] is the
    frozen R4 target weight for date t computed from bars ≤ t — the exact
    matrix the live loop would act on, so every policy sees identical targets.
    """
    mod = _load_reconstruction()
    allowed = dict(config.broker.allowed_symbols)
    universe = mod.build_universe(allowed)
    close_wide = pd.DataFrame({sym: f["close"] for sym, f in sorted(universe.items())}).sort_index()
    close_wide = close_wide[~close_wide.index.duplicated(keep="last")]
    fin, regime_on, _returns = mod.replicate_signal(close_wide)
    provenance = {
        "signal_source": "scripts/r4_shadow_portfolio.py:replicate_signal (C1 parity-verified)",
        "universe_source": "scripts/r4_shadow_portfolio.py:build_universe",
        "signal_rows": int(fin.shape[0]),
        "signal_cols": int(fin.shape[1]),
        "first_index": str(fin.index.min().date()) if len(fin.index) else "",
        "last_index": str(fin.index.max().date()) if len(fin.index) else "",
    }
    return fin, close_wide, provenance


def register_experiment(
    registry_dir: str,
    evaluation_period: tuple[str, str],
    config_version: str,
) -> str:
    """Pre-register EXP-000002 with full matrix trial accounting (Section 26).

    Every candidate configuration counts as a trial in ONE family — the
    threshold grid is registered, not hidden.
    """
    matrix = experiment_matrix()
    n_trials = len(matrix)
    repo = ExperimentRepository(registry_dir)
    registry = ExperimentRegistry()
    exp = registry.create(
        experiment_id=EXPERIMENT_ID,
        hypothesis_id=HYPOTHESIS_ID,
        git_commit=_git_head(),
        dataset_id="mt5_d1_csv",
        dataset_version="R5_data_manifest_2026-08-25",
        dataset_hash=_dataset_hash(),
        strategy_id="risk_conditioned_continuation",
        strategy_version="R4.0",
        strategy_config_hash="aaab6c00dc05a09a380af7fbd705cc8c241ea69023b6a8ddc8d5e7f0b82b2beb",
        strategy_artifact_hash="",
        parameters={
            "policies": [c.policy_id for c in matrix],
            "threshold_candidates": list(THRESHOLD_CANDIDATES),
            "weekly_anchor": "Monday 00:00 UTC (configurable)",
            "cost_model": "uniform bps per unit one-sided turnover (weight space)",
            "signal": "frozen R4, parity-verified offline reconstruction",
            "config_version": config_version,
        },
        cost_model_id="uniform_bps_weight_space",
        cost_model_version="v1",
        parent_experiment_id="",
        trial_metadata={
            "trial_group_id": TRIAL_GROUP,
            "trial_index": 1,
            "hypothesis_family": "rebalance_frequency",
            "selection_method": "pre_registered_matrix_no_search",
            "trials_in_family": n_trials,
            "parameter_search_space": {
                "policy_type": ["CANONICAL", "DAILY", "WEEKLY", "THRESHOLD", "HYBRID"],
                "threshold": list(THRESHOLD_CANDIDATES),
            },
        },
        train_start="",
        train_end="",
        validation_start=evaluation_period[0],
        validation_end=evaluation_period[1],
        test_start="",
        test_end="",
        status="PRE_REGISTERED",
    )
    registry.freeze_test_parameters(EXPERIMENT_ID)
    repo.save(exp)
    return str(Path(registry_dir) / f"{EXPERIMENT_ID}.json")


def _git_head() -> str:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=REPO, capture_output=True, text=True, timeout=10)
        return out.stdout.strip() if out.returncode == 0 else "UNAVAILABLE"
    except (OSError, subprocess.TimeoutExpired):
        return "UNAVAILABLE"


def _dataset_hash() -> str:
    import hashlib

    manifest = REPO / "data" / "mt5" / "R5_data_manifest.json"
    if manifest.exists():
        h = hashlib.sha256()
        with open(manifest, "rb") as f:
            for chunk in iter(lambda: f.read(1 << 20), b""):
                h.update(chunk)
        return h.hexdigest()
    return "MISSING"


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=False, default=None, help="evaluation window start (ISO)")
    parser.add_argument("--end", required=False, default=None, help="evaluation window end (ISO)")
    parser.add_argument("--out", default=DEFAULT_OUT, help="output directory for the report")
    parser.add_argument("--register-only", action="store_true", help="only pre-register the experiment, no replay")
    parser.add_argument("--registry-dir", default=REGISTRY_PATH, help="experiment repository directory")
    parser.add_argument(
        "--grid",
        choices=["daily", "weekly"],
        default="daily",
        help="candidate decision grid; the POLICY still decides interventions",
    )
    parser.add_argument(
        "--min-lot-weight",
        type=float,
        default=0.01,
        help="minimum tradable per-position weight for the min-lot floor "
        "(Section 21 sensitivity knob; default 0.01 = 1%% of equity)",
    )
    args = parser.parse_args()

    config = load_config("production")
    cost_bps = float(config.strategy.transaction_cost_bps + config.strategy.slippage_bps)

    period = (args.start or "", args.end or "")
    registered = register_experiment(args.registry_dir, period, config.__dict__.get("environment", "production"))

    if args.register_only:
        print(f"✅ Pre-registered {EXPERIMENT_ID} → {registered}")
        return

    print("═" * 72)
    print(f"  R4 REBALANCE-FREQUENCY RESEARCH ({EXPERIMENT_ID}) — shadow ablation")
    print("═" * 72)
    print(f"  Registered: {registered}")

    weights, closes, provenance = build_signal_panels(config)
    for k, v in provenance.items():
        print(f"  {k}: {v}")
    print(f"  cost model: {cost_bps:.1f} bps per unit one-sided turnover (uniform)")

    replay_cfg = ReplayConfig(
        equity=float(config.capital.max_equity),
        cost_bps=cost_bps,
        min_lot_weight=args.min_lot_weight,
        start=args.start,
        end=args.end,
    )
    from eigencapital.research.rebalance.replay import build_decision_grid  # local import: optional grid

    grid = build_decision_grid(weights.index, args.start, args.end, cadence=args.grid)
    replay_cfg = ReplayConfig(
        equity=float(config.capital.max_equity),
        cost_bps=cost_bps,
        min_lot_weight=args.min_lot_weight,
        decision_dates=grid,
    )
    print(f"  decision grid: {len(grid)} candidate dates ({args.grid}), window {period}")
    print(f"  min-lot floor: {args.min_lot_weight:.4f} of equity per position (Section 21 sensitivity knob)")

    results = run_policy_matrix(weights, closes, replay_cfg)
    base = {r.policy_id: r.summary(cost_bps) for r in results.values()}

    # Realized vol (Section 30 risk table): annualized std of the policy's
    # own daily net returns — a slower clock may drift realized risk.
    realized_vol = {
        pid: (float(r.daily_net_returns.std(ddof=1) * math.sqrt(252.0)) if len(r.daily_net_returns) > 1 else 0.0)
        for pid, r in results.items()
    }

    # ── Cost ladder (Section 20): uniform multipliers, all policies ──────
    ladder_rows: List[Dict[str, Any]] = []
    for mult in (1.0, 1.25, 1.5, 2.0):
        bps = cost_bps * mult
        ladder_cfg = ReplayConfig(
            equity=float(config.capital.max_equity),
            cost_bps=bps,
            min_lot_weight=args.min_lot_weight,
            decision_dates=grid,
        )
        ladder_results = run_policy_matrix(weights, closes, ladder_cfg)
        for pid, res in ladder_results.items():
            s = res.summary(bps)
            ladder_rows.append(
                {"multiplier": mult, "policy_id": pid, "net_return": s["net_return"], "net_sharpe": s["net_sharpe"]}
            )

    out_dir = REPO / args.out
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
    report = {
        "experiment_id": EXPERIMENT_ID,
        "hypothesis_id": HYPOTHESIS_ID,
        "trial_group": TRIAL_GROUP,
        "generated_at": datetime.now(UTC).isoformat(),
        "git_head": _git_head(),
        "evaluation_window": {"start": args.start, "end": args.end, "grid": args.grid},
        "signal_provenance": provenance,
        "cost_bps_base": cost_bps,
        "primary_table": [base[pid] for pid in sorted(base)],
        "risk_table": [
            {"policy_id": pid, "realized_vol_annualized": realized_vol[pid]} for pid in sorted(realized_vol)
        ],
        "cost_ladder": ladder_rows,
    }
    report_path = out_dir / f"rebalance_report_{stamp}.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, sort_keys=True, default=str)

    # Console: Section-30 style table.
    cols = [
        ("policy_id", 22),
        ("rebalances", 10),
        ("orders", 7),
        ("turnover_total", 10),
        ("gross_return", 13),
        ("cost_drag", 11),
        ("net_return", 12),
        ("net_sharpe", 10),
        ("max_drawdown", 12),
        ("tracking_error_mean", 19),
        ("return_per_turnover", 19),
    ]
    print("\n" + " | ".join(name.center(w) for name, w in cols))
    print("-" * (sum(cols_w for _, cols_w in cols) + 3 * (len(cols) - 1)))
    for row in sorted(base.values(), key=lambda r: r["policy_id"]):
        print(
            " | ".join(
                f"{row[name]:>{w}.4f}" if isinstance(row[name], float) else f"{row[name]!s:>{w}}" for name, w in cols
            )
        )
    print(f"\n✅ Report written: {report_path}")
    print("   NOTE: research evidence only — NO production cadence change is made")
    print("   automatically; promotion requires the Section-27 gates.")


if __name__ == "__main__":
    main()
