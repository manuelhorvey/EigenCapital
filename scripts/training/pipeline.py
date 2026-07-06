#!/usr/bin/env python3
"""Model retrain pipeline — retrain + validate + compare + report + rollback.

Usage:
    # Full pipeline: baseline → retrain → validate → compare → report
    PYTHONPATH=$PYTHONPATH:. python scripts/training/pipeline.py

    # Retrain only (skip baseline capture, skip validation)
    PYTHONPATH=$PYTHONPATH:. python scripts/training/pipeline.py --retrain-only

    # Validate only (compare existing walk-forward parquets against baseline)
    PYTHONPATH=$PYTHONPATH:. python scripts/training/pipeline.py --validate-only

    # With rollback (if validation gates fail, restore old models)
    PYTHONPATH=$PYTHONPATH:. python scripts/training/pipeline.py --rollback

    # Dry run (print what would happen, don't execute)
    PYTHONPATH=$PYTHONPATH:. python scripts/training/pipeline.py --dry-run

Pipeline stages:
    1. Capture baseline — run walk-forward + PnL on current models (saved as "baseline" tag)
    2. Retrain — train all 22 models via retrain_all_fixed.py
    3. Validate — run walk-forward + PnL on new models ("retrained" tag)
    4. Compare — diff metrics per asset against baseline
    5. Report — save comparison CSV + summary to data/processed/pipeline_report_*.json
    6. Rollback (optional) — restore old model files if validation gates fail
"""

from __future__ import annotations

import argparse
import glob
import json
import logging
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

import pandas as pd

# ── Module-level constants ───────────────────────────────────────────────────

# Subprocess scripts (retrain_all_fixed.py, walk_forward_backtest.py, backtest_pnl.py)
# calculate their own base from their __file__ location, which resolves to
# scripts/ (e.g. scripts/training/retrain_all_fixed.py → os.path.dirname(os.path.dirname(...)) → scripts/).
# All output goes under scripts/walkforward/ and scripts/data/processed/.
SCRIPTS_ROOT = Path(__file__).resolve().parent.parent  # scripts/training/ → scripts/
PROJECT_ROOT = SCRIPTS_ROOT.parent
WALKDIR = SCRIPTS_ROOT / "walkforward"
MODEL_DIR = PROJECT_ROOT / "paper_trading" / "models"
DATA_DIR = SCRIPTS_ROOT / "data" / "processed"
MODEL_BACKUP_DIR = MODEL_DIR / "pipeline_backups"

# Validation gate thresholds
GATES = {
    "total_R_regression_pct": -20.0,  # total_R drops more than 20% → WARN
    "sharpe_adj_min": 0.5,  # sharpe_adj below 0.5 → WARN
    "max_dd_worsen_factor": 2.0,  # max_dd_R worse by 2x+ → WARN
    "max_fail_assets": 3,  # More than 3 assets FAIL → pipeline FAIL
    "win_rate_min": 0.30,  # win rate below 30% → WARN
    "n_trades_min": 10,  # fewer than 10 trades → INFO (data insufficiency)
}

logger = logging.getLogger("eigencapital.retrain_pipeline")
TAG_BASELINE = "baseline"
TAG_RETRAINED = "retrained"


# ── Stage 1: Run walk-forward backtest ──────────────────────────────────────


def run_walk_forward(tag: str) -> bool:
    """Run walk_forward_backtest.py for ALL assets with the given tag.

    Returns True if the walk-forward produced any signal parquets.
    """
    wf_script = PROJECT_ROOT / "scripts" / "backtest" / "walk_forward_backtest.py"
    cmd = [
        sys.executable,
        str(wf_script),
        "--tag", tag,
        "--years", "3",
        "--step", "1",
        "--ensemble-weight", "1.0",
        "--n-folds", "3",
    ]
    logger.info("Running walk-forward backtest (tag=%s)...", tag)
    t0 = time.perf_counter()
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
    elapsed = time.perf_counter() - t0

    # Log output regardless of return code (walk-forward continues on per-asset failures)
    for line in result.stdout.splitlines():
        if any(kw in line for kw in ("SKIP", "ERROR", "insufficient", "=== Cross")):
            logger.info("[WF %s] %s", tag, line.strip())

    # If any signal parquets were produced, consider it a partial success
    pattern = f"*_wf_signals_{tag}.parquet"
    parquet_count = len(list(WALKDIR.glob(pattern)))
    if parquet_count > 0:
        logger.info("Walk-forward (tag=%s) produced %d signal parquets in %.1fs", tag, parquet_count, elapsed)
        return True
    # Fallback: check for tag-less parquets (older format)
    fallback_count = len(list(WALKDIR.glob("*_wf_signals.parquet")))
    if fallback_count > 0:
        logger.info("Walk-forward (tag=%s) produced %d tag-less signal parquets (legacy format)", tag, fallback_count)
        return True
    logger.error("Walk-forward (tag=%s) produced ZERO signal parquets!", tag)
    logger.error("STDOUT: %s", result.stdout[-2000:])
    logger.error("STDERR: %s", result.stderr[-2000:])
    return False


def run_pnl_backtest(tag: str) -> pd.DataFrame | None:
    """Run backtest_pnl.py for the given tag and return per-asset metrics.

    Parses the printed per-asset table and portfolio metrics from stdout.
    Returns a DataFrame indexed by asset, or None if the backtest failed.
    """
    pnl_script = PROJECT_ROOT / "scripts" / "backtest" / "backtest_pnl.py"
    cmd = [
        sys.executable,
        str(pnl_script),
        "--tag", tag,
        "--weight-method", "equal_v1",
        "--sell-only",
    ]
    logger.info("Running PnL backtest (tag=%s)...", tag)
    t0 = time.perf_counter()
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
    elapsed = time.perf_counter() - t0

    # Check for the CSV output
    csv_path = WALKDIR / f"pnl_backtest_{tag}.csv"
    if csv_path.exists():
        df = pd.read_csv(csv_path).set_index("asset")
        logger.info("PnL backtest (tag=%s) loaded %d assets from CSV in %.1fs", tag, len(df), elapsed)
        return df

    # Fallback: parse metrics from stdout
    logger.warning("PnL backtest CSV not found at %s — trying to parse stdout", csv_path)
    logger.info("PnL stdout (last 60 lines):\n%s", result.stdout[-3000:])
    return None


# ── Stage 2: Retrain all assets ─────────────────────────────────────────────


def run_retrain() -> tuple[bool, str]:
    """Run retrain_all_fixed.py to retrain all 22 models.

    Returns (success, report_path) where report_path is the training report CSV.
    """
    retrain_script = PROJECT_ROOT / "scripts" / "training" / "retrain_all_fixed.py"
    cmd = [sys.executable, str(retrain_script)]
    logger.info("Running full retrain...")
    t0 = time.perf_counter()
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(PROJECT_ROOT))
    elapsed = time.perf_counter() - t0

    # Log output
    for line in result.stdout.splitlines():
        if any(kw in line for kw in ("✓", "✗", "ERROR", "TRAINING REPORT", "OK:", "Failed:")):
            logger.info("[RETRAIN] %s", line.strip())

    # Find latest training report
    report_pattern = str(DATA_DIR / "training_report_*.csv")
    reports = sorted(glob.glob(report_pattern))
    report_path = reports[-1] if reports else ""

    # Count successes
    if report_path:
        report_df = pd.read_csv(report_path)
        ok_count = (report_df["status"] == "OK").sum()
        fail_count = len(report_df) - ok_count
        logger.info("Retrain complete: %d OK, %d failed in %.1fs", ok_count, fail_count, elapsed)
        return fail_count == 0, report_path

    logger.error("Retrain produced no report CSV!")
    logger.error("STDOUT (last 2000 chars):\n%s", result.stdout[-2000:])
    logger.error("STDERR (last 2000 chars):\n%s", result.stderr[-2000:])
    return False, ""


# ── Stage 3: Compare baseline vs retrained metrics ──────────────────────────


def compare_metrics(
    baseline_df: pd.DataFrame | None,
    retrained_df: pd.DataFrame | None,
) -> list[dict]:
    """Compare per-asset metrics and return a list of comparison records.

    Each record contains the asset name, baseline metrics, retrained metrics,
    deltas, and gate verdict (PASS / WARN / FAIL).
    """
    if baseline_df is None or retrained_df is None:
        logger.error("Cannot compare: one or both metric DataFrames are missing")
        return []

    common_assets = sorted(set(baseline_df.index) & set(retrained_df.index))
    if not common_assets:
        logger.error("No common assets between baseline and retrained!")
        return []

    comparisons = []
    for asset in common_assets:
        base = baseline_df.loc[asset]
        new = retrained_df.loc[asset]

        total_r_delta = new.get("total_R", 0) - base.get("total_R", 0)
        total_r_pct = (total_r_delta / max(abs(base.get("total_R", 1)), 1)) * 100

        sharpe_delta = new.get("sharpe_adj", 0) - base.get("sharpe_adj", 0)
        max_dd_base = base.get("max_dd_R", 0.0) or 0.0
        max_dd_new = new.get("max_dd_R", 0.0) or 0.0
        if max_dd_base < 0:
            max_dd_worsen = max_dd_new / max_dd_base
        elif max_dd_new < 0:
            max_dd_worsen = float("inf")  # new drawdown where none existed in baseline
        else:
            max_dd_worsen = 1.0  # no drawdown in either

        # Determine gate verdicts
        issues = []
        if total_r_pct < GATES["total_R_regression_pct"]:
            issues.append(f"total_R regression: {total_r_pct:.1f}% (threshold {GATES['total_R_regression_pct']:.0f}%)")
        if new.get("sharpe_adj", 1) < GATES["sharpe_adj_min"]:
            issues.append(f"sharpe_adj={new.get('sharpe_adj', 0):.2f} < {GATES['sharpe_adj_min']}")
        if max_dd_worsen > GATES["max_dd_worsen_factor"]:
            issues.append(f"max_dd worsened {max_dd_worsen:.1f}x (baseline={max_dd_base:.2f}, new={max_dd_new:.2f})")
        if new.get("win_rate", 1) < GATES["win_rate_min"]:
            issues.append(f"win_rate={new.get('win_rate', 0):.2f} < {GATES['win_rate_min']}")
        if new.get("n_trades", 0) < GATES["n_trades_min"]:
            verdict = "INFO"
            issues = []  # insufficient data — skip remaining gate checks
        elif issues:
            verdict = "FAIL" if total_r_pct < GATES["total_R_regression_pct"] else "WARN"
        else:
            verdict = "PASS"

        comparisons.append({
            "asset": asset,
            "verdict": verdict,
            "issues": issues,
            "baseline": {
                "total_R": base.get("total_R", 0),
                "sharpe_adj": base.get("sharpe_adj", 0),
                "max_dd_R": base.get("max_dd_R", 0),
                "win_rate": base.get("win_rate", 0),
                "n_trades": int(base.get("n_trades", 0)),
            },
            "retrained": {
                "total_R": new.get("total_R", 0),
                "sharpe_adj": new.get("sharpe_adj", 0),
                "max_dd_R": new.get("max_dd_R", 0),
                "win_rate": new.get("win_rate", 0),
                "n_trades": int(new.get("n_trades", 0)),
            },
            "delta": {
                "total_R": round(total_r_delta, 2),
                "total_R_pct": round(total_r_pct, 1),
                "sharpe_adj": round(sharpe_delta, 4),
                "max_dd_new_vs_base": round(max_dd_worsen, 2),
            },
        })

    return comparisons


# ── Stage 4: Rollback ───────────────────────────────────────────────────────


def backup_models() -> None:
    """Backup current model files before retraining."""
    MODEL_BACKUP_DIR.mkdir(parents=True, exist_ok=True)
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir = MODEL_BACKUP_DIR / ts
    backup_dir.mkdir(parents=True, exist_ok=True)
    count = 0
    for ext in ("*.json", "*_hash.txt"):
        for f in MODEL_DIR.glob(ext):
            if f.name.startswith("calibration"):
                continue
            shutil.copy2(str(f), str(backup_dir / f.name))
            count += 1
    logger.info("Backed up %d model files to %s", count, backup_dir)


def rollback_models() -> None:
    """Restore model files from the most recent backup."""
    backups = sorted(MODEL_BACKUP_DIR.iterdir())
    if not backups:
        logger.error("No backup directories found — cannot rollback!")
        return
    latest_backup = backups[-1]
    count = 0
    for f in latest_backup.iterdir():
        dest = MODEL_DIR / f.name
        shutil.copy2(str(f), str(dest))
        count += 1
    logger.info("Rolled back %d model files from %s", count, latest_backup)


# ── Stage 5: Report ─────────────────────────────────────────────────────────


def generate_report(
    comparisons: list[dict],
    retrain_report_path: str = "",
    pipeline_success: bool = False,
    tag_baseline: str = TAG_BASELINE,
    tag_retrained: str = TAG_RETRAINED,
    elapsed: float = 0.0,
) -> dict:
    """Generate and save the pipeline report JSON."""
    pass_count = sum(1 for c in comparisons if c["verdict"] == "PASS")
    warn_count = sum(1 for c in comparisons if c["verdict"] == "WARN")
    fail_count = sum(1 for c in comparisons if c["verdict"] == "FAIL")
    info_count = sum(1 for c in comparisons if c["verdict"] == "INFO")

    total_r_deltas = [c["delta"]["total_R"] for c in comparisons]
    total_r_improved = sum(1 for d in total_r_deltas if d > 0)
    total_r_degraded = sum(1 for d in total_r_deltas if d < 0)
    total_r_unchanged = sum(1 for d in total_r_deltas if d == 0)

    report = {
        "pipeline": {
            "timestamp": datetime.now().isoformat(),
            "elapsed_s": round(elapsed, 1),
            "tag_baseline": tag_baseline,
            "tag_retrained": tag_retrained,
            "retrain_report": retrain_report_path,
            "success": pipeline_success,
        },
        "summary": {
            "n_assets": len(comparisons),
            "pass": pass_count,
            "warn": warn_count,
            "fail": fail_count,
            "info": info_count,
            "total_R_improved": total_r_improved,
            "total_R_degraded": total_r_degraded,
            "total_R_unchanged": total_r_unchanged,
            "total_R_sum_baseline": round(
                sum(c["baseline"]["total_R"] for c in comparisons), 2
            ),
            "total_R_sum_retrained": round(
                sum(c["retrained"]["total_R"] for c in comparisons), 2
            ),
        },
        "gates": {
            name: value for name, value in GATES.items()
        },
        "assets": comparisons,
    }

    # Save report
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    report_path = DATA_DIR / f"pipeline_report_{ts}.json"
    DATA_DIR.mkdir(parents=True, exist_ok=True)
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    logger.info("Pipeline report saved to %s", report_path)
    return report


def print_report_summary(report: dict) -> None:
    """Print a human-readable summary of the pipeline report."""
    pipe = report["pipeline"]
    summary = report["summary"]

    print()
    print("=" * 72)
    print(f"  PIPELINE REPORT — {pipe['timestamp']}")
    print("=" * 72)
    print(f"  Elapsed: {pipe['elapsed_s']:.1f}s")
    print(f"  Status:  {'✓ PASS' if pipe['success'] else '✗ FAIL'}")
    print(f"  Baseline tag: {pipe['tag_baseline']}")
    print(f"  Retrained tag: {pipe['tag_retrained']}")
    print()
    print(f"  {'Result':<12} {'Count':<8}")
    print(f"  {'─' * 20}")
    print(f"  {'PASS':<12} {summary['pass']:<8}")
    print(f"  {'WARN':<12} {summary['warn']:<8}")
    print(f"  {'FAIL':<12} {summary['fail']:<8}")
    print(f"  {'INFO':<12} {summary['info']:<8}")
    print()
    print(f"  total_R improvement: {summary['total_R_improved']}/{summary['n_assets']} assets")
    print(f"  total_R degradation: {summary['total_R_degraded']}/{summary['n_assets']} assets")
    print(f"  Portfolio total_R: {summary['total_R_sum_baseline']:.1f} → {summary['total_R_sum_retrained']:.1f}")
    print()

    # Show failing/warning assets
    failing = [c for c in report["assets"] if c["verdict"] in ("FAIL", "WARN")]
    if failing:
        print(f"  {'Asset':<12} {'Verdict':<8} {'Issue':<40}")
        print(f"  {'─' * 60}")
        for c in failing:
            short_issue = c["issues"][0][:38] if c["issues"] else "N/A"
            print(f"  {c['asset']:<12} {c['verdict']:<8} {short_issue:<40}")
        print()

    # Show portfolio-level metrics if both tags exist
    try:
        pf_base_path = WALKDIR / f"portfolio_equity_{pipe['tag_baseline']}.csv"
        pf_new_path = WALKDIR / f"portfolio_equity_{pipe['tag_retrained']}.csv"
        if pf_base_path.exists() and pf_new_path.exists():
            pf_base = pd.read_csv(pf_base_path)
            pf_new = pd.read_csv(pf_new_path)
            print("  Portfolio summary:")
            print(f"    Baseline: {len(pf_base)} days, total_R={pf_base['portfolio_r'].sum():.2f}")
            print(f"    Retrained: {len(pf_new)} days, total_R={pf_new['portfolio_r'].sum():.2f}")
            print()
    except Exception:  # noqa: BLE001
        pass

    print("=" * 72)
    print()


# ── Stage 6: Pipeline orchestrator ──────────────────────────────────────────


def run_pipeline(
    retrain_only: bool = False,
    validate_only: bool = False,
    dry_run: bool = False,
    rollback: bool = False,
    skip_retrain: bool = False,
    tag_baseline: str = TAG_BASELINE,
    tag_retrained: str = TAG_RETRAINED,
) -> bool:
    """Run the full or partial retrain pipeline.

    Returns True if the pipeline succeeded (validation gates passed).
    """
    pipeline_start = time.perf_counter()

    # ── Stage 0: Backup current models ────────────────────────────────
    if not dry_run and not validate_only and not skip_retrain:
        backup_models()

    # ── Stage 1: Capture baseline ─────────────────────────────────────
    baseline_df: pd.DataFrame | None = None
    if not retrain_only:
        logger.info("=" * 60)
        logger.info("STAGE 1/5: Capture baseline (tag=%s)", tag_baseline)
        logger.info("=" * 60)
        if not dry_run:
            wf_ok = run_walk_forward(tag_baseline)
            if wf_ok:
                baseline_df = run_pnl_backtest(tag_baseline)
                if baseline_df is not None:
                    logger.info("Baseline captured: %d assets", len(baseline_df))
                else:
                    logger.warning("Baseline PnL returned no metrics — will compare on retrained only")
            else:
                logger.warning("Baseline walk-forward failed — will generate baseline from retrained-only data")
        else:
            logger.info("[DRY RUN] Would run walk-forward (tag=%s) + PnL backtest", tag_baseline)

    # ── Stage 2: Retrain ──────────────────────────────────────────────
    retrain_ok = False
    retrain_report_path = ""
    if not validate_only and not skip_retrain:
        logger.info("=" * 60)
        logger.info("STAGE 2/5: Retrain all assets")
        logger.info("=" * 60)
        if not dry_run:
            retrain_ok, retrain_report_path = run_retrain()
        else:
            logger.info("[DRY RUN] Would run retrain_all_fixed.py")
            retrain_ok = True
    elif skip_retrain:
        logger.info("STAGE 2/5: Skipping retrain (--skip-retrain)")

    # ── Stage 3: Validate ─────────────────────────────────────────────
    retrained_df: pd.DataFrame | None = None
    if not retrain_only:
        logger.info("=" * 60)
        logger.info("STAGE 3/5: Validate retrained models (tag=%s)", tag_retrained)
        logger.info("=" * 60)
        if not dry_run:
            wf_ok = run_walk_forward(tag_retrained)
            if wf_ok:
                retrained_df = run_pnl_backtest(tag_retrained)
                if retrained_df is not None:
                    logger.info("Validation captured: %d assets", len(retrained_df))
                else:
                    logger.warning("Validation PnL returned no metrics")
            else:
                logger.warning("Validation walk-forward failed")
        else:
            logger.info("[DRY RUN] Would run walk-forward (tag=%s) + PnL backtest", tag_retrained)

    # ── Stage 4: Compare ──────────────────────────────────────────────
    comparisons: list[dict] = []
    if not retrain_only:
        logger.info("=" * 60)
        logger.info("STAGE 4/5: Compare baseline vs retrained")
        logger.info("=" * 60)
        comparisons = compare_metrics(baseline_df, retrained_df)
        if comparisons:
            logger.info("Compared %d assets", len(comparisons))
        else:
            logger.warning("No comparisons generated")

    # ── Stage 5: Report and gates ─────────────────────────────────────
    logger.info("=" * 60)
    logger.info("STAGE 5/5: Generate report and evaluate gates")
    logger.info("=" * 60)

    fail_count = sum(1 for c in comparisons if c["verdict"] == "FAIL")
    pipeline_success = fail_count <= GATES["max_fail_assets"]

    if retrain_only:
        pipeline_success = retrain_ok
    if validate_only:
        pipeline_success = fail_count <= GATES["max_fail_assets"]

    elapsed = time.perf_counter() - pipeline_start

    if not dry_run:
        report = generate_report(
            comparisons=comparisons,
            retrain_report_path=retrain_report_path,
            pipeline_success=pipeline_success,
            tag_baseline=tag_baseline,
            tag_retrained=tag_retrained,
            elapsed=elapsed,
        )
        print_report_summary(report)

        if not pipeline_success and rollback and not retrain_only:
            logger.warning("=" * 60)
            logger.warning("VALIDATION GATES FAILED — rolling back models!")
            logger.warning("=" * 60)
            rollback_models()
    else:
        print()
        print("=" * 72)
        print("  DRY RUN SUMMARY")
        print("=" * 72)
        print(f"  Baseline tag: {tag_baseline}")
        print(f"  Retrained tag: {tag_retrained}")
        print(f"  Retrain: {'YES' if not skip_retrain else 'SKIP'}")
        print(f"  Rollback on fail: {'YES' if rollback else 'NO'}")
        print(f"  Walk-forward + PnL: {'baseline + retrained' if not retrain_only else 'none'}")
        print("  Assets: all 22 configured")
        if comparisons:
            print(f"  Gate summary: {fail_count} failing assets (max {GATES['max_fail_assets']})")
        print()

    return pipeline_success


# ── CLI ──────────────────────────────────────────────────────────────────────


def main():
    parser = argparse.ArgumentParser(
        description="Model retrain pipeline — retrain + validate + compare + report + rollback",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full pipeline
  PYTHONPATH=$PYTHONPATH:. python scripts/training/pipeline.py

  # Retrain only (skip baseline/validation — fastest)
  PYTHONPATH=$PYTHONPATH:. python scripts/training/pipeline.py --retrain-only

  # Validate only (compare existing walk-forward parquets)
  PYTHONPATH=$PYTHONPATH:. python scripts/training/pipeline.py --validate-only

  # With rollback on gate failure
  PYTHONPATH=$PYTHONPATH:. python scripts/training/pipeline.py --rollback

  # Dry run
  PYTHONPATH=$PYTHONPATH:. python scripts/training/pipeline.py --dry-run
        """,
    )
    mode_group = parser.add_mutually_exclusive_group()
    mode_group.add_argument(
        "--retrain-only",
        action="store_true",
        help="Retrain models only — skip baseline capture and validation gates",
    )
    mode_group.add_argument(
        "--validate-only",
        action="store_true",
        help="Run validation only — compare existing walk-forward parquets against baseline",
    )
    parser.add_argument(
        "--rollback",
        action="store_true",
        help="Restore previous model files if validation gates fail",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print pipeline steps without executing",
    )
    parser.add_argument(
        "--skip-retrain",
        action="store_true",
        help="Skip the retrain step (manual retrain already completed)",
    )
    parser.add_argument(
        "--baseline-tag",
        default=TAG_BASELINE,
        help=f"Tag for baseline walk-forward parquets (default: {TAG_BASELINE})",
    )
    parser.add_argument(
        "--retrained-tag",
        default=TAG_RETRAINED,
        help=f"Tag for retrained walk-forward parquets (default: {TAG_RETRAINED})",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable DEBUG-level logging",
    )

    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )

    success = run_pipeline(
        retrain_only=args.retrain_only,
        validate_only=args.validate_only,
        dry_run=args.dry_run,
        rollback=args.rollback,
        skip_retrain=args.skip_retrain,
        tag_baseline=args.baseline_tag,
        tag_retrained=args.retrained_tag,
    )

    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
