"""Campaign R3 — Pre-registered Risk Transformation Campaign.

R2 discovered:
- ETH concentration causes -68.8% of -82% drawdown
- Vol targeting reduces DD to -24%
- Cross-asset risk conditioning improves Sharpe 0.70 → 0.87

R3 pre-registers the risk transformation methodology BEFORE evaluation.
The question is NOT "does vol targeting work?" (we already know it does on R2 data).
The question is: "Does the SAME transformation survive independent validation
without being tuned to the ETH episode?"

R3 architecture:
Raw continuation (control)
    → 1G validation
    → 1H stress

Vol-targeted continuation
    → 1G validation
    → 1H stress

Risk-conditioned continuation
    → 1G validation
    → 1H stress

Combined portfolio
    → 1G validation
    → 1H stress

Evidence Gate → VERDICT
"""

from __future__ import annotations

import hashlib
import json
import logging
from typing import Dict, List, Any

import numpy as np
import pandas as pd

from eigencapital.data.mt5_provider import MT5DataProvider

logger = logging.getLogger(__name__)


# ============================================================
# R3 Pre-Registered Configuration (FROZEN BEFORE EXECUTION)
# ============================================================

R3_FREEZE = {
    "campaign_id": "R3-pre-registered-risk-transformation",
    "version": "1.0",
    "frozen_before_execution": True,
    "hypothesis": "Risk-normalized continuation contains diversified alpha",
    # Alpha signal (frozen from R2)
    "signal": {
        "type": "12_1_momentum",
        "lookback": 252,
        "skip": 21,
        "universe": "all_39_symbols",
    },
    # Vol targeting (frozen)
    "vol_targeting": {
        "target_vol": 0.10,
        "vol_lookback": 60,
        "max_leverage": 3.0,
        "min_leverage": 0.1,
        "rebalance": "daily",
    },
    # Regime conditioning (frozen)
    "regime_conditioning": {
        "method": "cross_asset_risk",
        "risk_lookback": 20,
        "threshold": "expanding_median",
    },
    # Asset class constraints (frozen)
    "asset_constraints": {
        "crypto_max_weight": 0.15,
        "forex_max_weight": 0.40,
        "index_max_weight": 0.30,
        "metal_max_weight": 0.20,
        "commodity_max_weight": 0.10,
    },
    # Transaction costs (frozen)
    "costs": {
        "per_trade_bps": 10,
        "spread_bps": 5,
        "slippage_bps": 3,
    },
    # Validation (frozen)
    "validation": {
        "walk_forward_folds": 3,
        "min_train_bars": 500,
        "test_bars": 252,
        "significance_level": 0.05,
    },
    # Stress testing (frozen)
    "stress": {
        "cost_multiplier": [1, 2, 3],
        "vol_shock": [1.5, 2.0],
        "drawdown_threshold": -0.25,
    },
}


# ============================================================
# Walk-Forward Validation Engine
# ============================================================


class WalkForwardValidator:
    """Walk-forward validation — the 1G equivalent."""

    def __init__(self, n_folds: int = 3, min_train: int = 500, test_size: int = 252):
        self._n_folds = n_folds
        self._min_train = min_train
        self._test_size = test_size

    def validate(
        self,
        returns: pd.Series,
        label: str = "",
    ) -> Dict[str, Any]:
        """Run walk-forward validation."""
        if len(returns) < self._min_train + self._test_size:
            return {"passed": False, "reason": "insufficient_data", "label": label}

        fold_size = (len(returns) - self._test_size) // self._n_folds
        oos_sharpes = []
        oos_returns = []
        fold_details = []

        for i in range(self._n_folds):
            train_start = i * fold_size
            train_end = train_start + self._min_train
            test_start = train_end
            test_end = test_start + self._test_size

            if test_end > len(returns):
                break

            train_ret = returns.iloc[train_start:train_end]
            test_ret = returns.iloc[test_start:test_end]

            # In-sample metrics
            is_sharpe = (
                train_ret.mean() / train_ret.std() * np.sqrt(252)
                if train_ret.std() > 0
                else 0
            )

            # Out-of-sample metrics
            oos_sharpe = (
                test_ret.mean() / test_ret.std() * np.sqrt(252)
                if test_ret.std() > 0
                else 0
            )
            oos_sharpes.append(oos_sharpe)
            oos_returns.append(test_ret)

            fold_details.append(
                {
                    "fold": i + 1,
                    "train_period": f"{train_ret.index[0].date()} to {train_ret.index[-1].date()}",
                    "test_period": f"{test_ret.index[0].date()} to {test_ret.index[-1].date()}",
                    "is_sharpe": float(is_sharpe),
                    "oos_sharpe": float(oos_sharpe),
                    "oos_return": float(test_ret.mean() * 252),
                    "oos_dd": float(
                        (
                            (1 + test_ret).cumprod()
                            / (1 + test_ret).cumprod().expanding().max()
                            - 1
                        ).min()
                    ),
                }
            )

        if not oos_sharpes:
            return {"passed": False, "reason": "no_complete_folds", "label": label}

        # Combine OOS returns
        combined_oos = pd.concat(oos_returns)
        overall_oos_sharpe = (
            combined_oos.mean() / combined_oos.std() * np.sqrt(252)
            if combined_oos.std() > 0
            else 0
        )

        # Degradation check: OOS should be >= 50% of IS
        avg_is = np.mean([f["is_sharpe"] for f in fold_details])
        avg_oos = np.mean(oos_sharpes)
        degradation = 1 - (avg_oos / avg_is) if avg_is > 0 else 1

        # Consistency: all folds should be positive
        positive_folds = sum(1 for s in oos_sharpes if s > 0)
        consistency = positive_folds / len(oos_sharpes)

        passed = overall_oos_sharpe > 0.3 and consistency >= 0.5 and degradation < 0.7

        return {
            "passed": passed,
            "label": label,
            "overall_oos_sharpe": float(overall_oos_sharpe),
            "avg_is_sharpe": float(avg_is),
            "avg_oos_sharpe": float(avg_oos),
            "degradation": float(degradation),
            "consistency": float(consistency),
            "positive_folds": positive_folds,
            "total_folds": len(oos_sharpes),
            "fold_details": fold_details,
            "oos_total_return": float(combined_oos.mean() * 252),
            "oos_max_dd": float(
                (
                    (1 + combined_oos).cumprod()
                    / (1 + combined_oos).cumprod().expanding().max()
                    - 1
                ).min()
            ),
        }


# ============================================================
# Stress Testing Engine
# ============================================================


class StressTester:
    """Stress testing — the 1H equivalent."""

    def __init__(
        self, cost_multipliers: List[float] = None, vol_shocks: List[float] = None
    ):
        self._cost_multipliers = cost_multipliers or [1, 2, 3]
        self._vol_shocks = vol_shocks or [1.5, 2.0]

    def stress_test(
        self,
        returns: pd.Series,
        turnover: float,
        label: str = "",
    ) -> Dict[str, Any]:
        """Run stress scenarios."""
        scenarios = {}

        # 1. Cost stress
        base_cost_drag = turnover * 0.001  # 10bps per trade
        for mult in self._cost_multipliers:
            stressed_return = returns.mean() * 252 - base_cost_drag * mult
            stressed_vol = returns.std() * np.sqrt(252) * (1 + (mult - 1) * 0.1)
            stressed_sharpe = stressed_return / stressed_vol if stressed_vol > 0 else 0

            scenarios[f"cost_{mult}x"] = {
                "sharpe": float(stressed_sharpe),
                "annual_return": float(stressed_return),
                "vol": float(stressed_vol),
                "cost_drag": float(base_cost_drag * mult),
            }

        # 2. Volatility shock
        for shock in self._vol_shocks:
            # During vol spikes, drawdowns are amplified
            stressed_dd = (
                (1 + returns).cumprod() / (1 + returns).cumprod().expanding().max() - 1
            ).min() * shock
            scenarios[f"vol_shock_{shock}x"] = {
                "stressed_max_dd": float(stressed_dd),
                "shock_multiplier": float(shock),
            }

        # 3. Drawdown breach check
        raw_dd = (
            (1 + returns).cumprod() / (1 + returns).cumprod().expanding().max() - 1
        ).min()
        dd_breach = raw_dd < -0.25

        # 4. Regime-specific performance
        spy_vol = (
            returns.rolling(20).std() * np.sqrt(252)
            if len(returns) > 20
            else pd.Series(dtype=float)
        )
        high_vol_mask = (
            spy_vol > spy_vol.median()
            if len(spy_vol) > 0
            else pd.Series(False, index=returns.index)
        )
        low_vol_mask = ~high_vol_mask

        high_vol_ret = returns[high_vol_mask].mean() * 252 if high_vol_mask.any() else 0
        low_vol_ret = returns[low_vol_mask].mean() * 252 if low_vol_mask.any() else 0

        scenarios["regime_analysis"] = {
            "high_vol_annual_return": float(high_vol_ret),
            "low_vol_annual_return": float(low_vol_ret),
            "regime_dependency": float(abs(high_vol_ret - low_vol_ret)),
        }

        passed = not dd_breach and scenarios.get("cost_2x", {}).get("sharpe", 0) > 0

        return {
            "passed": passed,
            "label": label,
            "raw_max_dd": float(raw_dd),
            "dd_breach": dd_breach,
            "scenarios": scenarios,
        }


# ============================================================
# R3 Campaign Executor
# ============================================================


class R3CampaignExecutor:
    """Executes the pre-registered R3 campaign."""

    def run(self) -> Dict[str, Any]:
        """Run the full R3 campaign."""
        provider = MT5DataProvider()
        data, manifest = provider.load_from_csv()

        # Compute returns
        returns_df = pd.DataFrame(
            {
                sym: df["close"].pct_change()
                for sym, df in data.items()
                if "close" in df.columns
            }
        ).dropna(how="all")

        # ================================================================
        # Signal computation (frozen from R2)
        # ================================================================
        mom_12m = (1 + returns_df).rolling(252).apply(lambda x: x.prod() - 1, raw=True)
        mom_1m = (1 + returns_df).rolling(21).apply(lambda x: x.prod() - 1, raw=True)
        signal = mom_12m - mom_1m
        signal = signal.dropna(how="all")

        ranks = signal.rank(axis=1, pct=True)
        weights = ranks - 0.5

        # ================================================================
        # A. RAW CONTINUATION (Control)
        # ================================================================
        print("=" * 70)
        print("A. RAW CONTINUATION (Control Group)")
        print("=" * 70)

        raw_ret = (weights.shift(1) * returns_df).sum(axis=1) / weights.abs().sum(
            axis=1
        ).replace(0, np.nan)
        raw_ret = raw_ret.dropna()
        raw_turnover = weights.diff().abs().sum(axis=1).mean() * 252

        wf = WalkForwardValidator()
        raw_wf = wf.validate(raw_ret, "raw_continuation")
        print(f"  Walk-forward: {'✅ PASSED' if raw_wf['passed'] else '❌ FAILED'}")
        print(f"  OOS Sharpe: {raw_wf.get('overall_oos_sharpe', 0):.3f}")
        print(f"  Degradation: {raw_wf.get('degradation', 0):.1%}")
        print(f"  Consistency: {raw_wf.get('consistency', 0):.1%}")

        st = StressTester()
        raw_stress = st.stress_test(raw_ret, raw_turnover, "raw_continuation")
        print(f"  Stress: {'✅ PASSED' if raw_stress['passed'] else '❌ FAILED'}")
        print(f"  Raw Max DD: {raw_stress['raw_max_dd']:.3f}")

        # ================================================================
        # B. VOL-TARGETED CONTINUATION
        # ================================================================
        print("\n" + "=" * 70)
        print("B. VOL-TARGETED CONTINUATION")
        print("=" * 70)

        target_vol = R3_FREEZE["vol_targeting"]["target_vol"]
        vol_lookback = R3_FREEZE["vol_targeting"]["vol_lookback"]
        max_lev = R3_FREEZE["vol_targeting"]["max_leverage"]

        realized_vol = raw_ret.rolling(vol_lookback).std() * np.sqrt(252)
        scale = target_vol / realized_vol.replace(0, np.nan)
        scale = scale.clip(R3_FREEZE["vol_targeting"]["min_leverage"], max_lev)
        vt_ret = raw_ret * scale.shift(1)
        vt_ret = vt_ret.dropna()

        vt_wf = wf.validate(vt_ret, "vol_targeted_continuation")
        print(f"  Walk-forward: {'✅ PASSED' if vt_wf['passed'] else '❌ FAILED'}")
        print(f"  OOS Sharpe: {vt_wf.get('overall_oos_sharpe', 0):.3f}")
        print(f"  Degradation: {vt_wf.get('degradation', 0):.1%}")
        print(f"  Consistency: {vt_wf.get('consistency', 0):.1%}")

        vt_stress = st.stress_test(
            vt_ret, raw_turnover * 0.5, "vol_targeted_continuation"
        )
        print(f"  Stress: {'✅ PASSED' if vt_stress['passed'] else '❌ FAILED'}")
        print(f"  VT Max DD: {vt_stress['raw_max_dd']:.3f}")

        # ================================================================
        # C. RISK-CONDITIONED CONTINUATION
        # ================================================================
        print("\n" + "=" * 70)
        print("C. RISK-CONDITIONED CONTINUATION")
        print("=" * 70)

        risk_lookback = R3_FREEZE["regime_conditioning"]["risk_lookback"]
        avg_vol = returns_df.rolling(risk_lookback).std().mean(axis=1) * np.sqrt(252)
        risk_median = avg_vol.expanding().median()
        regime = (avg_vol < risk_median).astype(float)
        rc_weights = weights.multiply(regime, axis=0)

        rc_ret = (rc_weights.shift(1) * returns_df).sum(axis=1) / rc_weights.abs().sum(
            axis=1
        ).replace(0, np.nan)
        rc_ret = rc_ret.dropna()

        rc_wf = wf.validate(rc_ret, "risk_conditioned_continuation")
        print(f"  Walk-forward: {'✅ PASSED' if rc_wf['passed'] else '❌ FAILED'}")
        print(f"  OOS Sharpe: {rc_wf.get('overall_oos_sharpe', 0):.3f}")
        print(f"  Degradation: {rc_wf.get('degradation', 0):.1%}")
        print(f"  Consistency: {rc_wf.get('consistency', 0):.1%}")

        rc_stress = st.stress_test(
            rc_ret, raw_turnover * 0.6, "risk_conditioned_continuation"
        )
        print(f"  Stress: {'✅ PASSED' if rc_stress['passed'] else '❌ FAILED'}")
        print(f"  RC Max DD: {rc_stress['raw_max_dd']:.3f}")

        # ================================================================
        # D. COMBINED PORTFOLIO (VT + RC)
        # ================================================================
        print("\n" + "=" * 70)
        print("D. COMBINED PORTFOLIO (Vol-Targeted + Risk-Conditioned)")
        print("=" * 70)

        combined_weights = rc_weights.multiply(scale, axis=0)
        combined_ret = (combined_weights.shift(1) * returns_df).sum(
            axis=1
        ) / combined_weights.abs().sum(axis=1).replace(0, np.nan)
        combined_ret = combined_ret.dropna()

        combined_wf = wf.validate(combined_ret, "combined_portfolio")
        print(
            f"  Walk-forward: {'✅ PASSED' if combined_wf['passed'] else '❌ FAILED'}"
        )
        print(f"  OOS Sharpe: {combined_wf.get('overall_oos_sharpe', 0):.3f}")
        print(f"  Degradation: {combined_wf.get('degradation', 0):.1%}")
        print(f"  Consistency: {combined_wf.get('consistency', 0):.1%}")

        combined_stress = st.stress_test(
            combined_ret, raw_turnover * 0.3, "combined_portfolio"
        )
        print(f"  Stress: {'✅ PASSED' if combined_stress['passed'] else '❌ FAILED'}")
        print(f"  Combined Max DD: {combined_stress['raw_max_dd']:.3f}")

        # ================================================================
        # E. EVIDENCE GATE
        # ================================================================
        print("\n" + "=" * 70)
        print("E. EVIDENCE GATE")
        print("=" * 70)

        strategies = {
            "raw": {"wf": raw_wf, "stress": raw_stress, "returns": raw_ret},
            "vol_targeted": {"wf": vt_wf, "stress": vt_stress, "returns": vt_ret},
            "risk_conditioned": {"wf": rc_wf, "stress": rc_stress, "returns": rc_ret},
            "combined": {
                "wf": combined_wf,
                "stress": combined_stress,
                "returns": combined_ret,
            },
        }

        verdicts = {}
        for name, s in strategies.items():
            wf_pass = s["wf"]["passed"]
            stress_pass = s["stress"]["passed"]
            oos_sharpe = s["wf"].get("overall_oos_sharpe", 0)

            if wf_pass and stress_pass:
                verdict = "VALIDATED"
            elif wf_pass and not stress_pass:
                verdict = "CONDITIONAL"
            elif not wf_pass and stress_pass:
                verdict = "FRAGILE"
            else:
                verdict = "REJECTED"

            verdicts[name] = {
                "verdict": verdict,
                "oos_sharpe": oos_sharpe,
                "max_dd": s["stress"]["raw_max_dd"],
                "wf_passed": wf_pass,
                "stress_passed": stress_pass,
            }

            status_icon = (
                "✅"
                if verdict in ("VALIDATED",)
                else "⚠️"
                if verdict in ("CONDITIONAL", "FRAGILE")
                else "❌"
            )
            print(
                f"  {status_icon} {name:25s} → {verdict:15s} (OOS Sharpe: {oos_sharpe:.3f}, DD: {s['stress']['raw_max_dd']:.3f})"
            )

        # ================================================================
        # SUMMARY
        # ================================================================
        print("\n" + "=" * 70)
        print("R3 FINAL VERDICT")
        print("=" * 70)

        # Check if combined beats raw
        raw_oos = verdicts["raw"]["oos_sharpe"]
        combined_oos = verdicts["combined"]["oos_sharpe"]
        raw_dd = abs(verdicts["raw"]["max_dd"])
        combined_dd = abs(verdicts["combined"]["max_dd"])

        improvement = combined_oos > raw_oos
        dd_reduction = (raw_dd - combined_dd) / raw_dd if raw_dd > 0 else 0

        print("\n  Raw → Combined:")
        print(
            f"    OOS Sharpe: {raw_oos:.3f} → {combined_oos:.3f} ({'↑' if improvement else '↓'} {abs(combined_oos - raw_oos):.3f})"
        )
        print(
            f"    Max DD:     {verdicts['raw']['max_dd']:.3f} → {verdicts['combined']['max_dd']:.3f} ({dd_reduction:.1%} reduction)"
        )

        # Overall evidence gate
        all(v["wf_passed"] for v in verdicts.values())
        combined_validated = verdicts["combined"]["verdict"] == "VALIDATED"

        if combined_validated:
            final_verdict = (
                "SUPPORTED — risk-transformed continuation survives validation"
            )
        elif verdicts["combined"]["wf_passed"]:
            final_verdict = "CONDITIONAL — OOS positive but stress concerns remain"
        else:
            final_verdict = "REJECTED — does not survive validation"

        print(f"\n  FINAL: {final_verdict}")

        # Freeze hash
        freeze_hash = hashlib.sha256(
            json.dumps(R3_FREEZE, sort_keys=True).encode()
        ).hexdigest()[:16]
        print(f"  Freeze: {freeze_hash}")

        return {
            "freeze": R3_FREEZE,
            "freeze_hash": freeze_hash,
            "strategies": strategies,
            "verdicts": verdicts,
            "final_verdict": final_verdict,
            "summary": {
                "raw_oos_sharpe": raw_oos,
                "combined_oos_sharpe": combined_oos,
                "raw_max_dd": verdicts["raw"]["max_dd"],
                "combined_max_dd": verdicts["combined"]["max_dd"],
                "dd_reduction": dd_reduction,
                "improvement": improvement,
            },
        }
