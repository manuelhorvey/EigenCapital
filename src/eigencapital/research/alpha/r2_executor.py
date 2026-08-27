"""Campaign R2 — Targeted Investigation of Surviving Alpha Family.

The Alpha Research Map identified:
- 1 promising family: continuation/breakout
- 3 manifestations: TREND-002, TREND-003, BRK-001
- 0 production strategies
- 14/14 affected by regime instability
- -81% to -88% max drawdowns

R2 attacks these weaknesses:
A. Drawdown decomposition — WHERE does the -88% come from?
B. Regime conditioning — WHEN does the signal work?
C. Risk transformation — HOW to size positions?
D. Portfolio construction — HOW to combine signals?
"""

from __future__ import annotations

import logging
from typing import Dict, Any

import numpy as np
import pandas as pd

from eigencapital.data.mt5_provider import MT5DataProvider

logger = logging.getLogger(__name__)


# ============================================================
# Drawdown Decomposition
# ============================================================


class DrawdownDecomposer:
    """Decomposes WHERE drawdowns come from."""

    def decompose(
        self,
        portfolio_returns: pd.Series,
        all_returns: pd.DataFrame,
        weights: pd.DataFrame,
    ) -> Dict[str, Any]:
        """Full drawdown decomposition."""
        # 1. Identify drawdown periods
        cum = (1 + portfolio_returns).cumprod()
        peak = cum.expanding().max()
        dd = (cum - peak) / peak

        # Find the worst drawdown
        trough_idx = dd.idxmin()
        peak_before = cum[:trough_idx].idxmax()
        cum[trough_idx:].idxmax() if trough_idx < cum.index[-1] else None

        # 2. Asset contribution during drawdown
        drawdown_period = (
            portfolio_returns.loc[peak_before:trough_idx]
            if peak_before != trough_idx
            else pd.Series(dtype=float)
        )
        asset_contributions = {}
        for col in weights.columns:
            if col in all_returns.columns:
                aligned_idx = drawdown_period.index.intersection(all_returns[col].index)
                if len(aligned_idx) > 0:
                    contrib = (
                        weights[col].reindex(aligned_idx).shift(1)
                        * all_returns[col].reindex(aligned_idx)
                    ).sum()
                    asset_contributions[col] = float(contrib)

        # 3. Regime analysis — what was volatility doing?
        spy = all_returns.get("US500m", pd.Series(dtype=float))
        if len(spy) > 0:
            vol_20d = spy.rolling(20).std() * np.sqrt(252)
            vol_at_peak = (
                vol_20d.reindex([peak_before]).values[0]
                if peak_before in vol_20d.index
                else 0
            )
            vol_at_trough = (
                vol_20d.reindex([trough_idx]).values[0]
                if trough_idx in vol_20d.index
                else 0
            )
        else:
            vol_at_peak = vol_at_trough = 0

        # 4. Long vs short contribution
        long_contrib = 0.0
        short_contrib = 0.0
        for col in weights.columns:
            if col in all_returns.columns:
                aligned = drawdown_period.index.intersection(all_returns[col].index)
                if len(aligned) > 0:
                    lc = (
                        weights[col].reindex(aligned).clip(lower=0).shift(1)
                        * all_returns[col].reindex(aligned)
                    ).sum()
                    sc = (
                        weights[col].reindex(aligned).clip(upper=0).shift(1)
                        * all_returns[col].reindex(aligned)
                    ).sum()
                    long_contrib += lc
                    short_contrib += sc

        return {
            "max_drawdown": float(dd.min()),
            "peak_date": str(peak_before.date())
            if hasattr(peak_before, "date")
            else str(peak_before),
            "trough_date": str(trough_idx.date())
            if hasattr(trough_idx, "date")
            else str(trough_idx),
            "drawdown_duration_days": len(drawdown_period),
            "asset_contributions": dict(
                sorted(asset_contributions.items(), key=lambda x: x[1])
            ),
            "long_contrib_during_dd": float(long_contrib),
            "short_contrib_during_dd": float(short_contrib),
            "vol_at_peak": float(vol_at_peak),
            "vol_at_trough": float(vol_at_trough),
            "total_return_during_dd": float(drawdown_period.sum()),
        }


# ============================================================
# Regime Conditioner
# ============================================================


class RegimeConditioner:
    """Tests regime-conditioned versions of the surviving signals."""

    def condition_on_volatility(
        self,
        signal: pd.DataFrame,
        returns_df: pd.DataFrame,
        vol_lookback: int = 60,
    ) -> Dict[str, Any]:
        """Reduce exposure when volatility is high."""
        # Realized vol
        port_ret = (signal.shift(1) * returns_df).sum(axis=1) / signal.abs().sum(
            axis=1
        ).replace(0, np.nan)
        vol = port_ret.rolling(vol_lookback).std() * np.sqrt(252)
        vol_median = vol.expanding().median()

        # Regime: low vol = full exposure, high vol = reduced exposure
        regime = (vol < vol_median).astype(float)
        conditioned_signal = signal.multiply(regime, axis=0)

        # Compute conditioned returns
        conditioned_ret = (conditioned_signal.shift(1) * returns_df).sum(
            axis=1
        ) / conditioned_signal.abs().sum(axis=1).replace(0, np.nan)
        conditioned_ret = conditioned_ret.dropna()

        # Compare
        raw_ret = port_ret.dropna()
        common = raw_ret.index.intersection(conditioned_ret.index)

        return {
            "raw_sharpe": self._sharpe(raw_ret.reindex(common)),
            "conditioned_sharpe": self._sharpe(conditioned_ret.reindex(common)),
            "raw_max_dd": self._max_dd(raw_ret.reindex(common)),
            "conditioned_max_dd": self._max_dd(conditioned_ret.reindex(common)),
            "raw_turnover": self._turnover(signal.reindex(common)),
            "conditioned_turnover": self._turnover(conditioned_signal.reindex(common)),
            "regime_pct_high_vol": float(1 - regime.reindex(common).mean()),
        }

    def condition_on_trend_strength(
        self,
        signal: pd.DataFrame,
        returns_df: pd.DataFrame,
        trend_lookback: int = 252,
    ) -> Dict[str, Any]:
        """Reduce exposure when trend is weak."""
        # Cross-sectional trend strength: dispersion of 12m returns
        mom = (
            (1 + returns_df)
            .rolling(trend_lookback)
            .apply(lambda x: x.prod() - 1, raw=True)
        )
        trend_strength = mom.std(axis=1)
        strength_median = trend_strength.expanding().median()

        # Full exposure in strong trend, reduced in weak
        regime = (trend_strength > strength_median).astype(float)
        conditioned_signal = signal.multiply(regime, axis=0)

        port_ret = (signal.shift(1) * returns_df).sum(axis=1) / signal.abs().sum(
            axis=1
        ).replace(0, np.nan)
        cond_ret = (conditioned_signal.shift(1) * returns_df).sum(
            axis=1
        ) / conditioned_signal.abs().sum(axis=1).replace(0, np.nan)

        common = port_ret.dropna().index.intersection(cond_ret.dropna().index)

        return {
            "raw_sharpe": self._sharpe(port_ret.reindex(common)),
            "conditioned_sharpe": self._sharpe(cond_ret.reindex(common)),
            "raw_max_dd": self._max_dd(port_ret.reindex(common)),
            "conditioned_max_dd": self._max_dd(cond_ret.reindex(common)),
            "raw_turnover": self._turnover(signal.reindex(common)),
            "conditioned_turnover": self._turnover(conditioned_signal.reindex(common)),
            "regime_pct_strong_trend": float(regime.reindex(common).mean()),
        }

    def condition_on_cross_asset_risk(
        self,
        signal: pd.DataFrame,
        returns_df: pd.DataFrame,
        risk_lookback: int = 20,
    ) -> Dict[str, Any]:
        """Reduce exposure when cross-asset risk is elevated."""
        # Average cross-asset vol
        avg_vol = returns_df.rolling(risk_lookback).std().mean(axis=1) * np.sqrt(252)
        risk_median = avg_vol.expanding().median()

        regime = (avg_vol < risk_median).astype(float)
        conditioned_signal = signal.multiply(regime, axis=0)

        port_ret = (signal.shift(1) * returns_df).sum(axis=1) / signal.abs().sum(
            axis=1
        ).replace(0, np.nan)
        cond_ret = (conditioned_signal.shift(1) * returns_df).sum(
            axis=1
        ) / conditioned_signal.abs().sum(axis=1).replace(0, np.nan)

        common = port_ret.dropna().index.intersection(cond_ret.dropna().index)

        return {
            "raw_sharpe": self._sharpe(port_ret.reindex(common)),
            "conditioned_sharpe": self._sharpe(cond_ret.reindex(common)),
            "raw_max_dd": self._max_dd(port_ret.reindex(common)),
            "conditioned_max_dd": self._max_dd(cond_ret.reindex(common)),
            "regime_pct_low_risk": float(regime.reindex(common).mean()),
        }

    def _sharpe(self, r: pd.Series) -> float:
        if len(r) < 10 or r.std() == 0:
            return 0.0
        return float(r.mean() / r.std() * np.sqrt(252))

    def _max_dd(self, r: pd.Series) -> float:
        if len(r) < 10:
            return 0.0
        cum = (1 + r).cumprod()
        return float(((cum - cum.expanding().max()) / cum.expanding().max()).min())

    def _turnover(self, w: pd.DataFrame) -> float:
        return float(w.diff().abs().sum(axis=1).mean() * 252)


# ============================================================
# Risk Transformer
# ============================================================


class RiskTransformer:
    """Tests risk-transformed versions of signals."""

    def vol_target(
        self,
        signal: pd.DataFrame,
        returns_df: pd.DataFrame,
        target_vol: float = 0.10,
        vol_lookback: int = 60,
    ) -> Dict[str, Any]:
        """Volatility-target the portfolio."""
        port_ret = (signal.shift(1) * returns_df).sum(axis=1) / signal.abs().sum(
            axis=1
        ).replace(0, np.nan)
        realized_vol = port_ret.rolling(vol_lookback).std() * np.sqrt(252)

        # Scale: target_vol / realized_vol
        scale = target_vol / realized_vol.replace(0, np.nan)
        scale = scale.clip(0, 3)  # Cap at 3x leverage

        vol_targeted_ret = port_ret * scale.shift(1)
        vol_targeted_ret = vol_targeted_ret.dropna()

        common = port_ret.dropna().index.intersection(vol_targeted_ret.index)

        return {
            "raw_sharpe": self._sharpe(port_ret.reindex(common)),
            "vol_targeted_sharpe": self._sharpe(vol_targeted_ret.reindex(common)),
            "raw_max_dd": self._max_dd(port_ret.reindex(common)),
            "vol_targeted_max_dd": self._max_dd(vol_targeted_ret.reindex(common)),
            "raw_vol": float(port_ret.reindex(common).std() * np.sqrt(252)),
            "vol_targeted_vol": float(vol_targeted_ret.std() * np.sqrt(252)),
            "avg_leverage": float(scale.reindex(common).mean()),
        }

    def signal_strength_sizing(
        self,
        signal: pd.DataFrame,
        returns_df: pd.DataFrame,
    ) -> Dict[str, Any]:
        """Size positions by signal strength (stronger signal = larger position)."""
        # Normalize signal strength
        signal_strength = signal.abs().sum(axis=1)
        normalized = signal.div(signal_strength.replace(0, np.nan), axis=0)

        port_ret = (signal.shift(1) * returns_df).sum(axis=1) / signal.abs().sum(
            axis=1
        ).replace(0, np.nan)
        sized_ret = (normalized.shift(1) * returns_df).sum(
            axis=1
        ) / normalized.abs().sum(axis=1).replace(0, np.nan)

        common = port_ret.dropna().index.intersection(sized_ret.dropna().index)

        return {
            "raw_sharpe": self._sharpe(port_ret.reindex(common)),
            "sized_sharpe": self._sharpe(sized_ret.reindex(common)),
            "raw_max_dd": self._max_dd(port_ret.reindex(common)),
            "sized_max_dd": self._max_dd(sized_ret.reindex(common)),
        }

    def _sharpe(self, r: pd.Series) -> float:
        if len(r) < 10 or r.std() == 0:
            return 0.0
        return float(r.mean() / r.std() * np.sqrt(252))

    def _max_dd(self, r: pd.Series) -> float:
        if len(r) < 10:
            return 0.0
        cum = (1 + r).cumprod()
        return float(((cum - cum.expanding().max()) / cum.expanding().max()).min())


# ============================================================
# Portfolio Constructor
# ============================================================


class PortfolioConstructor:
    """Tests different portfolio construction methods on survivors."""

    def equal_weight(
        self,
        signals: Dict[str, pd.DataFrame],
        returns_df: pd.DataFrame,
    ) -> Dict[str, Any]:
        """1/N equal weight across all signals."""
        combined = pd.DataFrame(signals)
        avg_signal = combined.mean(axis=1)

        # Cross-sectional from average signal
        avg_signal_df = pd.DataFrame({"avg": avg_signal})
        ranks = avg_signal_df.rank(axis=1, pct=True)
        weights = pd.DataFrame({"avg": (ranks - 0.5).values}, index=ranks.index)

        port_ret = (weights.shift(1) * returns_df.mean(axis=1).to_frame("avg")).sum(
            axis=1
        )

        return {
            "method": "equal_weight",
            "sharpe": self._sharpe(port_ret),
            "max_dd": self._max_dd(port_ret),
            "turnover": float(weights.diff().abs().sum(axis=1).mean() * 252),
        }

    def inverse_vol(
        self,
        signal: pd.DataFrame,
        returns_df: pd.DataFrame,
        vol_lookback: int = 60,
    ) -> Dict[str, Any]:
        """Inverse-volatility weighted across assets."""
        asset_vol = returns_df.rolling(vol_lookback).std()
        inv_vol = 1 / asset_vol.replace(0, np.nan)
        weights = inv_vol.div(inv_vol.sum(axis=1), axis=0).fillna(0)

        (signal.shift(1) * returns_df).sum(axis=1) / signal.abs().sum(axis=1).replace(
            0, np.nan
        )

        # Recompute with inv-vol weights
        port_ret_iv = (weights.shift(1) * returns_df).sum(axis=1)

        return {
            "method": "inverse_vol",
            "sharpe": self._sharpe(port_ret_iv),
            "max_dd": self._max_dd(port_ret_iv),
            "turnover": float(weights.diff().abs().sum(axis=1).mean() * 252),
        }

    def _sharpe(self, r: pd.Series) -> float:
        r = r.dropna()
        if len(r) < 10 or r.std() == 0:
            return 0.0
        return float(r.mean() / r.std() * np.sqrt(252))

    def _max_dd(self, r: pd.Series) -> float:
        r = r.dropna()
        if len(r) < 10:
            return 0.0
        cum = (1 + r).cumprod()
        return float(((cum - cum.expanding().max()) / cum.expanding().max()).min())


# ============================================================
# R2 Campaign Executor
# ============================================================


class R2CampaignExecutor:
    """Executes Campaign R2 — targeted investigation of surviving family."""

    def run(self) -> Dict[str, Any]:
        """Run the full R2 campaign."""
        provider = MT5DataProvider()
        data, manifest = provider.load_from_csv()

        results = {"manifest": manifest.to_dict(), "sections": {}}

        # Compute the surviving signal: 3-month momentum (best performer)
        returns_df = pd.DataFrame(
            {
                sym: df["close"].pct_change()
                for sym, df in data.items()
                if "close" in df.columns
            }
        ).dropna(how="all")

        # Core signal: 3-month momentum (TREND-002's signal)
        (1 + returns_df).rolling(63).apply(lambda x: x.prod() - 1, raw=True)
        mom_12m = (1 + returns_df).rolling(252).apply(lambda x: x.prod() - 1, raw=True)
        signal_12_1 = mom_12m - (1 + returns_df).rolling(21).apply(
            lambda x: x.prod() - 1, raw=True
        )

        ranks = signal_12_1.rank(axis=1, pct=True)
        weights = ranks - 0.5
        weights = weights.dropna(how="all")

        port_ret = (weights.shift(1) * returns_df).sum(axis=1) / weights.abs().sum(
            axis=1
        ).replace(0, np.nan)
        port_ret = port_ret.dropna()

        # ================================================================
        # A. DRAWDOWN DECOMPOSITION
        # ================================================================
        print("=" * 70)
        print("A. DRAWDOWN DECOMPOSITION")
        print("=" * 70)

        decomposer = DrawdownDecomposer()
        dd_analysis = decomposer.decompose(port_ret, returns_df, weights)

        print(f"  Max Drawdown: {dd_analysis['max_drawdown']:.3f}")
        print(f"  Peak: {dd_analysis['peak_date']}")
        print(f"  Trough: {dd_analysis['trough_date']}")
        print(f"  Duration: {dd_analysis['drawdown_duration_days']} days")
        print(f"  Vol at peak: {dd_analysis['vol_at_peak']:.3f}")
        print(f"  Vol at trough: {dd_analysis['vol_at_trough']:.3f}")
        print(
            f"  Long contribution during DD: {dd_analysis['long_contrib_during_dd']:.4f}"
        )
        print(
            f"  Short contribution during DD: {dd_analysis['short_contrib_during_dd']:.4f}"
        )
        print("\n  Asset contributions during drawdown:")
        for asset, contrib in sorted(
            dd_analysis["asset_contributions"].items(), key=lambda x: x[1]
        ):
            print(f"    {asset:12s} {contrib:+.4f}")

        results["sections"]["drawdown_decomposition"] = dd_analysis

        # ================================================================
        # B. REGIME CONDITIONING
        # ================================================================
        print("\n" + "=" * 70)
        print("B. REGIME CONDITIONING")
        print("=" * 70)

        conditioner = RegimeConditioner()

        # B1: Volatility regime
        print("\n  B1: Volatility Regime Conditioning")
        vol_result = conditioner.condition_on_volatility(weights, returns_df)
        print(f"    Raw Sharpe:       {vol_result['raw_sharpe']:.3f}")
        print(f"    Conditioned:      {vol_result['conditioned_sharpe']:.3f}")
        print(f"    Raw Max DD:       {vol_result['raw_max_dd']:.3f}")
        print(f"    Conditioned DD:   {vol_result['conditioned_max_dd']:.3f}")
        print(f"    High vol %:       {vol_result['regime_pct_high_vol']:.1%}")

        # B2: Trend strength
        print("\n  B2: Trend Strength Conditioning")
        trend_result = conditioner.condition_on_trend_strength(weights, returns_df)
        print(f"    Raw Sharpe:       {trend_result['raw_sharpe']:.3f}")
        print(f"    Conditioned:      {trend_result['conditioned_sharpe']:.3f}")
        print(f"    Raw Max DD:       {trend_result['raw_max_dd']:.3f}")
        print(f"    Conditioned DD:   {trend_result['conditioned_max_dd']:.3f}")
        print(f"    Strong trend %:   {trend_result['regime_pct_strong_trend']:.1%}")

        # B3: Cross-asset risk
        print("\n  B3: Cross-Asset Risk Conditioning")
        risk_result = conditioner.condition_on_cross_asset_risk(weights, returns_df)
        print(f"    Raw Sharpe:       {risk_result['raw_sharpe']:.3f}")
        print(f"    Conditioned:      {risk_result['conditioned_sharpe']:.3f}")
        print(f"    Raw Max DD:       {risk_result['raw_max_dd']:.3f}")
        print(f"    Conditioned DD:   {risk_result['conditioned_max_dd']:.3f}")
        print(f"    Low risk %:       {risk_result['regime_pct_low_risk']:.1%}")

        results["sections"]["regime_conditioning"] = {
            "volatility": vol_result,
            "trend_strength": trend_result,
            "cross_asset_risk": risk_result,
        }

        # ================================================================
        # C. RISK TRANSFORMATION
        # ================================================================
        print("\n" + "=" * 70)
        print("C. RISK TRANSFORMATION")
        print("=" * 70)

        transformer = RiskTransformer()

        # C1: Vol targeting
        print("\n  C1: Volatility Targeting (10% target)")
        vt_result = transformer.vol_target(weights, returns_df, target_vol=0.10)
        print(f"    Raw Sharpe:       {vt_result['raw_sharpe']:.3f}")
        print(f"    VT Sharpe:        {vt_result['vol_targeted_sharpe']:.3f}")
        print(f"    Raw Max DD:       {vt_result['raw_max_dd']:.3f}")
        print(f"    VT Max DD:        {vt_result['vol_targeted_max_dd']:.3f}")
        print(f"    Raw Vol:          {vt_result['raw_vol']:.3f}")
        print(f"    VT Vol:           {vt_result['vol_targeted_vol']:.3f}")
        print(f"    Avg Leverage:     {vt_result['avg_leverage']:.2f}x")

        # C2: Signal strength sizing
        print("\n  C2: Signal Strength Sizing")
        ss_result = transformer.signal_strength_sizing(weights, returns_df)
        print(f"    Raw Sharpe:       {ss_result['raw_sharpe']:.3f}")
        print(f"    Sized Sharpe:     {ss_result['sized_sharpe']:.3f}")
        print(f"    Raw Max DD:       {ss_result['raw_max_dd']:.3f}")
        print(f"    Sized Max DD:     {ss_result['sized_max_dd']:.3f}")

        results["sections"]["risk_transformation"] = {
            "vol_targeting": vt_result,
            "signal_strength": ss_result,
        }

        # ================================================================
        # D. PORTFOLIO CONSTRUCTION
        # ================================================================
        print("\n" + "=" * 70)
        print("D. PORTFOLIO CONSTRUCTION")
        print("=" * 70)

        constructor = PortfolioConstructor()

        # D1: Inverse vol
        print("\n  D1: Inverse Volatility Weighting")
        iv_result = constructor.inverse_vol(weights, returns_df)
        print(f"    Method:           {iv_result['method']}")
        print(f"    Sharpe:           {iv_result['sharpe']:.3f}")
        print(f"    Max DD:           {iv_result['max_dd']:.3f}")
        print(f"    Turnover:         {iv_result['turnover']:.1f}x")

        results["sections"]["portfolio_construction"] = {
            "inverse_vol": iv_result,
        }

        # ================================================================
        # SUMMARY
        # ================================================================
        print("\n" + "=" * 70)
        print("CAMPAIGN R2 SUMMARY")
        print("=" * 70)

        # Best regime conditioner
        best_regime = max(
            [
                ("vol", vol_result["conditioned_sharpe"]),
                ("trend", trend_result["conditioned_sharpe"]),
                ("risk", risk_result["conditioned_sharpe"]),
            ],
            key=lambda x: x[1],
        )

        # Best risk transformer
        best_risk = max(
            [
                ("vol_target", vt_result["vol_targeted_sharpe"]),
                ("signal_size", ss_result["sized_sharpe"]),
            ],
            key=lambda x: x[1],
        )

        print(
            f"\n  Best regime conditioner: {best_regime[0]} (Sharpe {best_regime[1]:.3f})"
        )
        print(f"  Best risk transformer: {best_risk[0]} (Sharpe {best_risk[1]:.3f})")

        # Key finding
        improvements = []
        if vol_result["conditioned_max_dd"] > vol_result["raw_max_dd"] * 0.5:
            improvements.append("Vol regime conditioning halves drawdown")
        if trend_result["conditioned_max_dd"] > trend_result["raw_max_dd"] * 0.5:
            improvements.append("Trend strength conditioning halves drawdown")
        if vt_result["vol_targeted_max_dd"] > vt_result["raw_max_dd"] * 0.5:
            improvements.append("Vol targeting halves drawdown")

        print("\n  Key improvements:")
        for imp in improvements:
            print(f"    ✅ {imp}")

        if not improvements:
            print(
                "    ⚠️  No regime/risk transformation significantly improved the profile"
            )

        results["summary"] = {
            "best_regime_conditioner": best_regime[0],
            "best_regime_sharpe": best_regime[1],
            "best_risk_transformer": best_risk[0],
            "best_risk_sharpe": best_risk[1],
            "improvements": improvements,
            "raw_sharpe": float(vol_result["raw_sharpe"]),
            "raw_max_dd": float(vol_result["raw_max_dd"]),
        }

        return results
