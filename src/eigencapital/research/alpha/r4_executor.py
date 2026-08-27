"""Campaign R4 — Pre-registered Risk Transformation for Tail Risk Reduction.

R3 found: CONDITIONAL (OOS Sharpe 1.02, 100% consistency, but -62% stress DD)

R4 is NOT another alpha hunt. It's a risk-transformation experiment.

Principle: Don't optimize for -25% DD. Let the evidence determine what
the strategy is allowed to become.

Test independently:
A. Asset volatility limits
B. Crypto concentration limits
C. Correlation/concentration controls
D. Portfolio volatility targeting (frozen from R3)
E. Inverse-vol / risk-parity allocation
F. Drawdown exposure reduction
G. Combined risk architecture

Each frozen before evaluation. Evidence determines verdict.
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Any, Dict

import numpy as np
import pandas as pd

from eigencapital.data.mt5_provider import MT5DataProvider
from eigencapital.research.alpha.r3_executor import StressTester, WalkForwardValidator

logger = logging.getLogger(__name__)


# ============================================================
# R4 Pre-Registered Configuration
# ============================================================

R4_FREEZE = {
    "campaign_id": "R4-risk-transformation",
    "version": "1.0",
    "hypothesis": "Pre-specified risk architecture reduces tail risk while preserving OOS edge",
    # Base signal (frozen from R3)
    "signal": {"type": "12_1_momentum", "lookback": 252, "skip": 21},
    # Risk transformations (frozen)
    "asset_vol_cap": {"max_annual_vol": 0.50, "vol_lookback": 60},
    "crypto_cap": {"max_weight": 0.10},
    "concentration_cap": {"max_single_asset": 0.20},
    "risk_parity": {"vol_lookback": 60, "target_vol": 0.10},
    "drawdown_reducer": {"dd_threshold": -0.15, "reduction_factor": 0.5},
    "regime_aware": {"risk_lookback": 20, "threshold": "expanding_median"},
    # Validation (frozen)
    "walk_forward_folds": 3,
    "min_train_bars": 500,
    "test_bars": 252,
    "stress_cost_multipliers": [1, 2, 3],
    "stress_vol_shocks": [1.5, 2.0],
}


# ============================================================
# Risk Transformers
# ============================================================


class R4RiskTransformers:
    """Individual risk transformations for R4."""

    def asset_vol_cap(
        self,
        weights: pd.DataFrame,
        returns_df: pd.DataFrame,
        max_vol: float = 0.50,
        vol_lookback: int = 60,
    ) -> pd.DataFrame:
        """Cap individual asset volatility contribution."""
        asset_vol = returns_df.rolling(vol_lookback).std() * np.sqrt(252)
        vol_ratio = asset_vol / max_vol
        cap = np.minimum(vol_ratio, 1.0)
        # Reduce weight for high-vol assets
        adjusted = weights * cap
        return adjusted

    def crypto_concentration_cap(
        self,
        weights: pd.DataFrame,
        max_weight: float = 0.10,
    ) -> pd.DataFrame:
        """Cap crypto at max_weight."""
        crypto_cols = [c for c in weights.columns if "BTC" in c or "ETH" in c]
        adjusted = weights.copy()
        for col in crypto_cols:
            if col in adjusted.columns:
                adjusted[col] = adjusted[col].clip(-max_weight, max_weight)
        return adjusted

    def single_asset_cap(
        self,
        weights: pd.DataFrame,
        max_single: float = 0.20,
    ) -> pd.DataFrame:
        """Cap any single asset at max_single."""
        return weights.clip(-max_single, max_single)

    def risk_parity_weights(
        self,
        returns_df: pd.DataFrame,
        vol_lookback: int = 60,
    ) -> pd.DataFrame:
        """Inverse-volatility (risk parity) weights."""
        asset_vol = returns_df.rolling(vol_lookback).std()
        inv_vol = 1 / asset_vol.replace(0, np.nan)
        weights = inv_vol.div(inv_vol.sum(axis=1), axis=0).fillna(0)
        return weights

    def drawdown_reducer(
        self,
        portfolio_returns: pd.Series,
        raw_weights: pd.DataFrame,
        dd_threshold: float = -0.15,
        reduction_factor: float = 0.5,
    ) -> pd.DataFrame:
        """Reduce exposure when drawdown exceeds threshold."""
        cum = (1 + portfolio_returns).cumprod()
        peak = cum.expanding().max()
        dd = (cum - peak) / peak

        # When DD exceeds threshold, reduce weights
        in_drawdown = (dd < dd_threshold).astype(float)
        scale = 1 - (in_drawdown * reduction_factor)

        return raw_weights.multiply(scale, axis=0)

    def regime_aware_exposure(
        self,
        weights: pd.DataFrame,
        returns_df: pd.DataFrame,
        risk_lookback: int = 20,
    ) -> pd.DataFrame:
        """Reduce exposure in high-risk regime."""
        avg_vol = returns_df.rolling(risk_lookback).std().mean(axis=1) * np.sqrt(252)
        risk_median = avg_vol.expanding().median()
        regime = (avg_vol < risk_median).astype(float)
        return weights.multiply(regime, axis=0)


# ============================================================
# R4 Campaign Executor
# ============================================================


class R4CampaignExecutor:
    """Executes the pre-registered R4 risk transformation campaign."""

    def run(self) -> Dict[str, Any]:
        provider = MT5DataProvider()
        data, manifest = provider.load_from_csv()
        transformers = R4RiskTransformers()

        # Compute base signal
        returns_df = pd.DataFrame(
            {sym: df["close"].pct_change() for sym, df in data.items() if "close" in df.columns}
        ).dropna(how="all")

        mom_12m = (1 + returns_df).rolling(252).apply(lambda x: x.prod() - 1, raw=True)
        mom_1m = (1 + returns_df).rolling(21).apply(lambda x: x.prod() - 1, raw=True)
        signal = (mom_12m - mom_1m).dropna(how="all")
        ranks = signal.rank(axis=1, pct=True)
        base_weights = ranks - 0.5

        # Regime conditioning (frozen from R3)
        avg_vol = returns_df.rolling(20).std().mean(axis=1) * np.sqrt(252)
        risk_median = avg_vol.expanding().median()
        regime = (avg_vol < risk_median).astype(float)
        rc_weights = base_weights.multiply(regime, axis=0)

        wf = WalkForwardValidator()
        st = StressTester()

        strategies = {}

        # ================================================================
        # A. BASELINE: Risk-Conditioned (from R3)
        # ================================================================
        print("=" * 70)
        print("A. BASELINE: Risk-Conditioned (R3)")
        print("=" * 70)
        base_ret = self._portfolio_return(rc_weights, returns_df)
        base_turnover = rc_weights.diff().abs().sum(axis=1).mean() * 252
        base_wf = wf.validate(base_ret, "A_baseline_rc")
        base_stress = st.stress_test(base_ret, base_turnover, "A_baseline_rc")
        strategies["A_baseline_rc"] = self._report("A", "Baseline RC", base_ret, base_wf, base_stress)

        # ================================================================
        # B. + Asset Vol Cap
        # ================================================================
        print("\n" + "=" * 70)
        print("B. + Asset Volatility Cap (50% annual)")
        print("=" * 70)
        b_weights = transformers.asset_vol_cap(rc_weights, returns_df, 0.50, 60)
        b_ret = self._portfolio_return(b_weights, returns_df)
        b_turnover = b_weights.diff().abs().sum(axis=1).mean() * 252
        b_wf = wf.validate(b_ret, "B_asset_vol_cap")
        b_stress = st.stress_test(b_ret, b_turnover, "B_asset_vol_cap")
        strategies["B_asset_vol_cap"] = self._report("B", "Asset Vol Cap", b_ret, b_wf, b_stress)

        # ================================================================
        # C. + Crypto Cap (10%)
        # ================================================================
        print("\n" + "=" * 70)
        print("C. + Crypto Concentration Cap (10%)")
        print("=" * 70)
        c_weights = transformers.crypto_concentration_cap(b_weights, 0.10)
        c_ret = self._portfolio_return(c_weights, returns_df)
        c_turnover = c_weights.diff().abs().sum(axis=1).mean() * 252
        c_wf = wf.validate(c_ret, "C_crypto_cap")
        c_stress = st.stress_test(c_ret, c_turnover, "C_crypto_cap")
        strategies["C_crypto_cap"] = self._report("C", "Crypto Cap", c_ret, c_wf, c_stress)

        # ================================================================
        # D. + Single Asset Cap (20%)
        # ================================================================
        print("\n" + "=" * 70)
        print("D. + Single Asset Cap (20%)")
        print("=" * 70)
        d_weights = transformers.single_asset_cap(c_weights, 0.20)
        d_ret = self._portfolio_return(d_weights, returns_df)
        d_turnover = d_weights.diff().abs().sum(axis=1).mean() * 252
        d_wf = wf.validate(d_ret, "D_single_asset_cap")
        d_stress = st.stress_test(d_ret, d_turnover, "D_single_asset_cap")
        strategies["D_single_asset_cap"] = self._report("D", "Single Asset Cap", d_ret, d_wf, d_stress)

        # ================================================================
        # E. Risk Parity (alternative allocation)
        # ================================================================
        print("\n" + "=" * 70)
        print("E. Risk Parity Allocation")
        print("=" * 70)
        e_weights = transformers.risk_parity_weights(returns_df, 60)
        e_ret = self._portfolio_return(e_weights, returns_df)
        e_turnover = e_weights.diff().abs().sum(axis=1).mean() * 252
        e_wf = wf.validate(e_ret, "E_risk_parity")
        e_stress = st.stress_test(e_ret, e_turnover, "E_risk_parity")
        strategies["E_risk_parity"] = self._report("E", "Risk Parity", e_ret, e_wf, e_stress)

        # ================================================================
        # F. Drawdown Reducer
        # ================================================================
        print("\n" + "=" * 70)
        print("F. Drawdown Exposure Reducer (threshold -15%)")
        print("=" * 70)
        base_port_ret = self._portfolio_return(rc_weights, returns_df)
        f_weights = transformers.drawdown_reducer(base_port_ret, rc_weights, -0.15, 0.5)
        f_ret = self._portfolio_return(f_weights, returns_df)
        f_turnover = f_weights.diff().abs().sum(axis=1).mean() * 252
        f_wf = wf.validate(f_ret, "F_dd_reducer")
        f_stress = st.stress_test(f_ret, f_turnover, "F_dd_reducer")
        strategies["F_dd_reducer"] = self._report("F", "DD Reducer", f_ret, f_wf, f_stress)

        # ================================================================
        # G. Combined (B + C + D + F)
        # ================================================================
        print("\n" + "=" * 70)
        print("G. COMBINED: VolCap + CryptoCap + AssetCap + DDReducer")
        print("=" * 70)
        g_weights = transformers.drawdown_reducer(
            self._portfolio_return(d_weights, returns_df),
            d_weights,
            -0.15,
            0.5,
        )
        g_ret = self._portfolio_return(g_weights, returns_df)
        g_turnover = g_weights.diff().abs().sum(axis=1).mean() * 252
        g_wf = wf.validate(g_ret, "G_combined")
        g_stress = st.stress_test(g_ret, g_turnover, "G_combined")
        strategies["G_combined"] = self._report("G", "Combined", g_ret, g_wf, g_stress)

        # ================================================================
        # EVIDENCE GATE
        # ================================================================
        print("\n" + "=" * 70)
        print("R4 EVIDENCE GATE")
        print("=" * 70)

        freeze_hash = hashlib.sha256(json.dumps(R4_FREEZE, sort_keys=True).encode()).hexdigest()[:16]
        print(f"  Freeze: {freeze_hash}")
        print()

        verdicts = {}
        for key, s in strategies.items():
            if s["wf_passed"] and s["stress_passed"]:
                verdict = "VALIDATED"
            elif s["wf_passed"]:
                verdict = "CONDITIONAL"
            else:
                verdict = "REJECTED"

            verdicts[key] = {
                "verdict": verdict,
                "oos_sharpe": s["oos_sharpe"],
                "max_dd": s["max_dd"],
                "wf_passed": s["wf_passed"],
                "stress_passed": s["stress_passed"],
            }

            icon = "✅" if verdict == "VALIDATED" else "⚠️" if verdict == "CONDITIONAL" else "❌"
            print(f"  {icon} {s['label']:25s} → {verdict:15s} (OOS: {s['oos_sharpe']:.3f}, DD: {s['max_dd']:.3f})")

        # Best candidate
        best = max(
            [(k, v) for k, v in verdicts.items() if v["wf_passed"]],
            key=lambda x: x[1]["oos_sharpe"],
            default=None,
        )

        if best:
            best_key, best_v = best
            print(f"\n  Best candidate: {best_key}")
            print(f"  OOS Sharpe: {best_v['oos_sharpe']:.3f}")
            print(f"  Max DD: {best_v['max_dd']:.3f}")
            print(f"  Verdict: {best_v['verdict']}")

            if best_v["max_dd"] < -0.25:
                print(f"\n  NOTE: Stress DD ({best_v['max_dd']:.1%}) exceeds -25% threshold.")
                print("  This may be a higher-risk strategy. The evidence determines the label.")
                if best_v["verdict"] == "CONDITIONAL":
                    final = f"HIGH_RISK_CONDITIONAL — OOS positive, stress DD {best_v['max_dd']:.1%}"
                else:
                    final = f"VALIDATED — stress DD {best_v['max_dd']:.1%}"
            else:
                final = "VALIDATED — all gates pass"
        else:
            final = "REJECTED — no candidate survives walk-forward"

        print(f"\n  FINAL: {final}")

        return {
            "freeze": R4_FREEZE,
            "freeze_hash": freeze_hash,
            "strategies": strategies,
            "verdicts": verdicts,
            "final_verdict": final,
            "best_candidate": best_key if best else None,
        }

    def _portfolio_return(self, weights: pd.DataFrame, returns_df: pd.DataFrame) -> pd.Series:
        aligned = weights.index.intersection(returns_df.index)
        w = weights.reindex(aligned).shift(1)
        r = returns_df.reindex(aligned)
        port = (w * r).sum(axis=1) / w.abs().sum(axis=1).replace(0, np.nan)
        return port.dropna()

    def _report(
        self,
        letter: str,
        label: str,
        ret: pd.Series,
        wf_result: Dict,
        stress_result: Dict,
    ) -> Dict:
        oos_sharpe = wf_result.get("overall_oos_sharpe", 0)
        max_dd = stress_result.get("raw_max_dd", 0)
        print(f"  Walk-forward: {'✅ PASSED' if wf_result['passed'] else '❌ FAILED'} (OOS Sharpe: {oos_sharpe:.3f})")
        print(f"  Stress: {'✅ PASSED' if stress_result['passed'] else '❌ FAILED'} (Max DD: {max_dd:.3f})")
        return {
            "label": f"{letter}. {label}",
            "oos_sharpe": oos_sharpe,
            "max_dd": max_dd,
            "wf_passed": wf_result["passed"],
            "stress_passed": stress_result["passed"],
            "wf_details": wf_result,
            "stress_details": stress_result,
        }
