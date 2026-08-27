"""Validation Report Generator — deterministic Markdown output.

Produces a comprehensive, reproducible validation report from
a ValidationResult object.

Usage:
    from eigencapital.analytics.validation.report import generate_report
    markdown = generate_report(result)
"""

from __future__ import annotations

from eigencapital.analytics.validation.evidence_gate import EvidenceVerdict
from eigencapital.analytics.validation.validator import ValidationResult


def generate_report(result: ValidationResult) -> str:
    """Generate a deterministic Markdown validation report.

    Args:
        result: Complete ValidationResult from ValidationEngine

    Returns:
        Markdown string with full validation report
    """
    lines = []

    # ── Header ──────────────────────────────────────────────────────
    lines.append(f"# Validation Report: {result.experiment_id or 'Unknown'}")
    lines.append("")
    lines.append(f"**Verdict: {result.verdict}**")
    lines.append("")

    # ── 1. Experiment Identity ──────────────────────────────────────
    lines.append("## 1. Experiment Identity")
    lines.append("")
    lines.append(f"- **Experiment ID:** {result.experiment_id}")
    if result.provenance_hash:
        lines.append(f"- **Provenance Hash:** `{result.provenance_hash}`")
    lines.append("")

    # ── 2. Baseline Metrics ─────────────────────────────────────────
    lines.append("## 2. Baseline Metrics")
    lines.append("")
    if result.baseline_metrics:
        m = result.baseline_metrics
        lines.append("| Metric | Value |")
        lines.append("|--------|-------|")
        lines.append(f"| Total Return | {m.total_return:.4%} |")
        lines.append(f"| CAGR | {m.cagr:.4%} |")
        lines.append(f"| Annualized Volatility | {m.annualized_volatility:.4%} |")
        lines.append(f"| Sharpe Ratio | {m.sharpe_ratio:.4f} |")
        lines.append(f"| Sortino Ratio | {m.sortino_ratio:.4f} |")
        lines.append(f"| Calmar Ratio | {m.calmar_ratio:.4f} |")
        lines.append(f"| Max Drawdown | {m.max_drawdown:.4%} |")
        lines.append(f"| Observations | {m.observation_count} |")
    else:
        lines.append("*No baseline metrics available.*")
    lines.append("")

    # ── 3. Walk-Forward ─────────────────────────────────────────────
    lines.append("## 3. Walk-Forward Analysis")
    lines.append("")
    if result.walk_forward and result.walk_forward.total_windows > 0:
        wf = result.walk_forward
        lines.append(f"- **Windows:** {wf.total_windows}")
        lines.append(f"- **Mean OOS Sharpe:** {wf.mean_oos_sharpe:.4f}")
        lines.append(f"- **OOS Sharpe Range:** [{wf.min_oos_sharpe:.4f}, {wf.max_oos_sharpe:.4f}]")
        lines.append(f"- **Degradation Ratio:** {wf.degradation_ratio:.2f}x")
        lines.append(f"- **Profitable Windows:** {wf.pct_profitable_windows:.1f}%")
    else:
        lines.append("*Walk-forward analysis unavailable or insufficient data.*")
    lines.append("")

    # ── 4. Bootstrap ────────────────────────────────────────────────
    lines.append("## 4. Bootstrap Confidence Intervals")
    lines.append("")
    if result.bootstrap_iid and result.bootstrap_iid.n_bootstrap > 0:
        b = result.bootstrap_iid
        lines.append("- **Method:** IID")
        lines.append(f"- **Iterations:** {b.n_bootstrap}")
        lines.append(f"- **Sharpe CI:** [{b.sharpe_ci_lower:.4f}, {b.sharpe_ci_upper:.4f}]")
        lines.append(f"- **% Positive Sharpe:** {b.pct_positive_sharpe:.1f}%")
    if result.bootstrap_block and result.bootstrap_block.n_bootstrap > 0:
        bb = result.bootstrap_block
        lines.append(f"- **Method:** Block (size={bb.block_size})")
        lines.append(f"- **Sharpe CI:** [{bb.sharpe_ci_lower:.4f}, {bb.sharpe_ci_upper:.4f}]")
    if not result.bootstrap_iid and not result.bootstrap_block:
        lines.append("*Bootstrap analysis unavailable.*")
    lines.append("")

    # ── 5. Permutation Test ─────────────────────────────────────────
    lines.append("## 5. Permutation Test")
    lines.append("")
    if result.permutation and result.permutation.n_permutations > 0:
        p = result.permutation
        lines.append(f"- **Observed Sharpe:** {p.observed_sharpe:.4f}")
        lines.append(f"- **p-value:** {p.p_value:.4f}")
        lines.append(f"- **Significant at 5%:** {'Yes' if p.significant_at_5pct else 'No'}")
        lines.append(f"- **Significant at 1%:** {'Yes' if p.significant_at_1pct else 'No'}")
    else:
        lines.append("*Permutation test unavailable.*")
    lines.append("")

    # ── 6. Cost Stress ──────────────────────────────────────────────
    lines.append("## 6. Cost Stress Analysis")
    lines.append("")
    if result.cost_stress and result.cost_stress.levels:
        cs = result.cost_stress
        lines.append(f"- **Survives 1.5x costs:** {'Yes' if cs.survives_1_5x else 'No'}")
        lines.append(f"- **Survives 2x costs:** {'Yes' if cs.survives_2x else 'No'}")
        lines.append(f"- **Breakeven multiplier:** {cs.breakeven_multiplier:.2f}x")
        lines.append("")
        lines.append("| Multiplier | Sharpe | Profitable |")
        lines.append("|-----------|--------|-----------|")
        for level in cs.levels:
            lines.append(f"| {level.multiplier:.1f}x | {level.sharpe:.4f} | {'Yes' if level.is_profitable else 'No'} |")
    else:
        lines.append("*Cost stress analysis unavailable.*")
    lines.append("")

    # ── 7. Regime Analysis ──────────────────────────────────────────
    lines.append("## 7. Regime Analysis")
    lines.append("")
    if result.regime and result.regime.regimes:
        r = result.regime
        lines.append(f"- **Regime-dependent:** {'Yes' if r.regime_dependent else 'No'}")
        lines.append(f"- **Sharpe range:** {r.sharpe_range:.4f}")
        lines.append(f"- **Worst regime:** {r.worst_regime}")
        lines.append(f"- **Best regime:** {r.best_regime}")
        lines.append("")
        lines.append("| Regime | Sharpe | Total Return | Max DD | Win Rate |")
        lines.append("|--------|--------|-------------|--------|----------|")
        for regime in r.regimes:
            lines.append(
                f"| {regime.regime} | {regime.sharpe:.4f} | {regime.total_return:.4%} | {regime.max_drawdown:.4%} | {regime.win_rate:.1f}% |"
            )
    else:
        lines.append("*Regime analysis unavailable.*")
    lines.append("")

    # ── 8. Universe Perturbation ────────────────────────────────────
    lines.append("## 8. Universe Perturbation")
    lines.append("")
    if result.universe:
        u = result.universe
        lines.append(f"- **Single instrument dependency:** {'Yes' if u.single_instrument_dependency else 'No'}")
        lines.append(f"- **Robustness score:** {u.robustness_score:.1f}%")
        conc = u.concentration
        lines.append(f"- **HHI:** {conc.herfindahl_index:.4f}")
        lines.append(f"- **Most concentrated:** {conc.most_concentrated_instrument}")
        lines.append(f"- **Concentration warning:** {'Yes' if conc.concentration_warning else 'No'}")
    else:
        lines.append("*Universe perturbation analysis unavailable.*")
    lines.append("")

    # ── 9. Temporal Stability ───────────────────────────────────────
    lines.append("## 9. Temporal Stability")
    lines.append("")
    if result.temporal and result.temporal.window_count > 0:
        t = result.temporal
        lines.append(f"- **Rolling windows:** {t.window_count}")
        lines.append(f"- **Sharpe trend:** {t.sharpe_trend:.6f}")
        lines.append(f"- **Sharpe stability:** {t.sharpe_stability:.4f}")
        lines.append(f"- **Min Sharpe:** {t.min_sharpe:.4f}")
        lines.append(f"- **Max Sharpe:** {t.max_sharpe:.4f}")
        lines.append(f"- **% Positive Sharpe:** {t.pct_positive_sharpe:.1f}%")
        lines.append(f"- **Performance decay:** {'Yes' if t.performance_decay else 'No'}")
    else:
        lines.append("*Temporal stability analysis unavailable or insufficient data.*")
    lines.append("")

    # ── 10. Multiple Testing ────────────────────────────────────────
    lines.append("## 10. Multiple Testing")
    lines.append("")
    if result.multiple_testing and result.multiple_testing.n_tests > 1:
        mt = result.multiple_testing
        lines.append(f"- **Method:** {mt.method}")
        lines.append(f"- **Tests:** {mt.n_tests}")
        lines.append(f"- **Rejected:** {sum(mt.rejected)}")
    else:
        lines.append("*Single test (no multiple-testing correction needed).*")
    lines.append("")

    # ── 11. PBO ─────────────────────────────────────────────────────
    lines.append("## 11. Probability of Backtest Overfitting")
    lines.append("")
    if result.pbo:
        pbo = result.pbo
        if pbo.sufficient_experiments:
            lines.append(f"- **PBO:** {pbo.pbo:.4f}")
            lines.append(f"- **Candidates:** {pbo.n_candidates}")
        else:
            lines.append("- **Status:** INSUFFICIENT_EXPERIMENTS")
            lines.append(f"- **Message:** {pbo.message}")
    else:
        lines.append("*PBO analysis not performed.*")
    lines.append("")

    # ── 12. Evidence Gate ───────────────────────────────────────────
    lines.append("## 12. Evidence Gate")
    lines.append("")
    lines.append(f"### Verdict: **{result.verdict}**")
    lines.append("")
    if result.missing_evidence:
        lines.append(f"**Missing evidence:** {', '.join(result.missing_evidence)}")
        lines.append("")
    if result.warnings:
        lines.append("**Warnings:**")
        for w in result.warnings:
            lines.append(f"- {w}")
        lines.append("")

    lines.append("| Check | Passed | Missing | Severity | Message |")
    lines.append("|-------|--------|---------|----------|---------|")
    for check in result.evidence_checks:
        passed = "✅" if check["passed"] else ("❓" if check.get("missing") else "❌")
        missing = "YES" if check.get("missing") else ""
        lines.append(f"| {check['check_id']} | {passed} | {missing} | {check['severity']} | {check['message'][:80]} |")
    lines.append("")

    # ── 13. Limitations ─────────────────────────────────────────────
    lines.append("## 13. Limitations")
    lines.append("")
    lines.append("- This validation evaluates statistical properties of the equity curve.")
    lines.append("- It does not evaluate real-world execution quality, liquidity, or market impact.")
    lines.append("- Missing evidence components result in INCONCLUSIVE, not PASS.")
    lines.append("- Statistical significance does not imply economic significance.")
    lines.append("")

    # ── 14. Recommended Next Action ─────────────────────────────────
    lines.append("## 14. Recommended Next Action")
    lines.append("")
    if result.verdict == EvidenceVerdict.REJECTED:
        lines.append("**REJECTED.** Do not proceed. Investigate failure modes.")
    elif result.verdict == EvidenceVerdict.INCONCLUSIVE:
        lines.append("**INCONCLUSIVE.** Gather missing evidence before proceeding.")
    elif result.verdict == EvidenceVerdict.CANDIDATE:
        lines.append("**CANDIDATE.** Evidence is promising but not yet strong enough for validation.")
        lines.append("Recommend Phase 1H robustness and adversarial simulation.")
    elif result.verdict == EvidenceVerdict.VALIDATED:
        lines.append("**VALIDATED.** Evidence is strong. Proceed with caution to Phase 1H.")
    lines.append("")

    return "\n".join(lines)
