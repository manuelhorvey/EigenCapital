"""Exposure model for the R4-S shadow portfolio constructor.

Derives underlying currency/factor exposure for every candidate from the
portfolio's signed weights, so the selector can see when "10 different
trades" are really "1-3 underlying macro/factor bets".

REUSE: classification is fully derived from the canonical maps in
`eigencapital.live.portfolio_analytics` (SYMBOL_CURRENCY_MAP, CURRENCIES,
ASSET_CLASS_MAP). The shadow layer owns NO symbol lists of its own, so a
universe change (e.g. HK50/JP225 admitted 2026-09-27) propagates here
automatically instead of silently diverging (the drift that previously left
US500 unclassifiable).

Factor groups (risk_on / usd / commodity / equity_beta / safe_haven) are
derived, lightweight, and DIAGNOSTIC ONLY — they are recorded in shadow
evidence for cluster diagnostics and are never used as trading rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from eigencapital.live.portfolio_analytics import (
    CURRENCIES,
    SYMBOL_CURRENCY_MAP,
    classify_asset_class,
)

# Factor groups derived from asset class. Explicit-mapped classes:
#   metals     → safe_haven (empirical risk-off demand; XAG shares the cluster)
#   energy     → commodity
# Everything not FX and not explicitly mapped falls through to equity_beta
# (indices and crypto singles are USD-quoted equity-beta risk).
_ASSET_CLASS_FACTOR_GROUP: Dict[str, str] = {
    "metals": "safe_haven",
    "energy": "commodity",
    "indices": "equity_beta",
    "crypto": "equity_beta",
}

# Per-symbol exceptions to the asset-class mapping, for instruments whose
# empirical cluster membership differs from their class. Evidence-oriented,
# NOT a static trading rule (correlation remains estimated from returns).
# BTC/ETH: empirically high equity-beta in risk-off.
_FACTOR_GROUP_EXCEPTIONS: Dict[str, str] = {
    "BTCUSD": "equity_beta",
    "ETHUSD": "equity_beta",
}

_CURRENCY_SET = set(CURRENCIES)


def get_currencies(symbol: str) -> Tuple[str, str]:
    """Return (base, quote) currencies for FX pairs; ("", "") otherwise."""
    if symbol in SYMBOL_CURRENCY_MAP:
        return SYMBOL_CURRENCY_MAP[symbol]
    for c1 in CURRENCIES:
        for c2 in CURRENCIES:
            if c1 != c2 and symbol.startswith(c1) and symbol.endswith(c2):
                return (c1, c2)
    return ("", "")


def get_factor_group(symbol: str) -> str:
    """Derived macro/factor group for a symbol (diagnostic only).

    Order: explicit per-symbol exception → asset-class mapping → FX
    currency-logic → 'other'. Future universe admissions need no edit here
    as long as their asset class is in the canonical ASSET_CLASS_MAP (or
    they are FX, which is classified structurally).
    """
    if symbol in _FACTOR_GROUP_EXCEPTIONS:
        return _FACTOR_GROUP_EXCEPTIONS[symbol]
    asset_class = classify_asset_class(symbol)
    if asset_class == "forex":
        base, quote = get_currencies(symbol)
        # Commodity currencies proxy the commodity factor.
        if "AUD" in (base, quote) or "NZD" in (base, quote) or "CAD" in (base, quote):
            return "commodity"
        if base == "JPY" or quote == "JPY":
            return "safe_haven"
        return "risk_on"
    return _ASSET_CLASS_FACTOR_GROUP.get(asset_class, "other")


@dataclass
class ExposureModelConfig:
    """Limits used by the selector to control redundant exposure.

    All experimental, shadow-only, isolated from frozen R4 configuration.
    """

    # Max |net| currency exposure as a fraction of gross notional.
    max_currency_exposure_pct: float = 0.60
    # Max share of gross notional in one factor group.
    max_factor_group_pct: float = 0.60
    # Max share of gross notional in one asset class. Default 1.0 = disabled
    # (FX-dominated universe; see ShadowSelectorConfig).
    max_asset_class_pct: float = 1.0


class ExposureModel:
    """Portfolio-level currency / asset-class / factor exposure calculator."""

    def __init__(self, config: ExposureModelConfig | None = None) -> None:
        self.config = config or ExposureModelConfig()

    def currency_exposure(
        self,
        weights: Dict[str, float],
        notionals: Dict[str, float] | None = None,
    ) -> Dict[str, float]:
        """Signed currency exposure in notional-equivalent units.

        For FX: LONG AUDUSD ≈ +AUD / -USD; SHORT EURUSD ≈ -EUR / +USD.
        Single-leg instruments (indices, metals, crypto, energy) are treated
        as USD-exposed (they are all USD-quoted risk positions).
        """
        exposures: Dict[str, float] = {c: 0.0 for c in CURRENCIES}
        for sym, w in weights.items():
            if w == 0.0:
                continue
            notional = abs(notionals.get(sym, abs(w))) if notionals else abs(w)
            signed = notional if w > 0 else -notional
            base, quote = get_currencies(sym)
            if base and quote:
                exposures[base] = exposures.get(base, 0.0) + signed
                exposures[quote] = exposures.get(quote, 0.0) - signed
            else:
                # USD-quoted single-leg risk proxy.
                exposures["USD"] = exposures.get("USD", 0.0) - signed
        return {c: v for c, v in exposures.items() if abs(v) > 1e-12}

    def asset_class_exposure(self, weights: Dict[str, float]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for sym, w in weights.items():
            if w == 0.0:
                continue
            ac = classify_asset_class(sym)
            out[ac] = out.get(ac, 0.0) + abs(w)
        return out

    def factor_exposure(self, weights: Dict[str, float]) -> Dict[str, float]:
        out: Dict[str, float] = {}
        for sym, w in weights.items():
            if w == 0.0:
                continue
            fg = get_factor_group(sym)
            out[fg] = out.get(fg, 0.0) + abs(w)
        return out

    def max_cluster_exposure(self, weights: Dict[str, float]) -> Tuple[str, float]:
        """Largest factor-group share of gross exposure."""
        fx = self.factor_exposure(weights)
        gross = sum(abs(w) for w in weights.values())
        if not fx or gross <= 0:
            return ("", 0.0)
        name = max(fx, key=lambda k: fx[k])
        return (name, fx[name] / gross)

    def concentration_summary(self, weights: Dict[str, float]) -> Dict[str, Any]:
        gross = sum(abs(w) for w in weights.values())
        ccy = self.currency_exposure(weights)
        ac = self.asset_class_exposure(weights)
        fx = self.factor_exposure(weights)
        cluster_name, cluster_share = self.max_cluster_exposure(weights)

        def _pct(d: Dict[str, float]) -> Dict[str, float]:
            return {k: round(v / gross, 4) for k, v in d.items()} if gross > 0 else {}

        ccy_pct = _pct(ccy)
        ac_pct = _pct(ac)
        fx_pct = _pct(fx)
        max_ccy_name = max(ccy_pct, key=lambda k: abs(ccy_pct[k])) if ccy_pct else ""
        max_ccy_val = abs(ccy_pct.get(max_ccy_name, 0.0)) if ccy_pct else 0.0
        max_ac_name = max(ac_pct, key=lambda k: ac_pct[k]) if ac_pct else ""
        max_ac_val = ac_pct.get(max_ac_name, 0.0) if ac_pct else 0.0

        return {
            "gross": round(gross, 6),
            "currency_exposure_pct": ccy_pct,
            "max_currency_exposure": {"group": max_ccy_name, "pct": round(max_ccy_val, 4)},
            "asset_class_exposure_pct": ac_pct,
            "max_asset_class_exposure": {"group": max_ac_name, "pct": round(max_ac_val, 4)},
            "factor_exposure_pct": fx_pct,
            "max_cluster_exposure": {"group": cluster_name, "pct": round(cluster_share, 4)},
        }

    def violates(
        self,
        weights: Dict[str, float],
    ) -> List[str]:
        """Return constraint-violation reason codes for a candidate portfolio.

        Hard caps are REDUNDANCY caps: a single position is concentrated by
        definition (100% of gross in one currency), so caps fire only for
        multi-position portfolios where the same currency/factor/class is
        stacked. Soft excess-over-threshold λ penalties handle gradations.
        """
        active = [w for w in weights.values() if abs(w) > 1e-12]
        if len(active) < 2:
            return []
        gross = sum(abs(w) for w in active)
        if gross <= 0:
            return []
        reasons: List[str] = []
        summary = self.concentration_summary(weights)
        if summary["max_currency_exposure"]["pct"] > self.config.max_currency_exposure_pct:
            reasons.append("currency_concentration")
        if summary["max_cluster_exposure"]["pct"] > self.config.max_factor_group_pct:
            reasons.append("factor_concentration")
        if summary["max_asset_class_exposure"]["pct"] > self.config.max_asset_class_pct:
            reasons.append("asset_class_concentration")
        return reasons

    def final_state_rejection(
        self,
        final_weights: Dict[str, float],
        symbol: str,
        weight: float,
    ) -> str | None:
        """Hard-cap violation code for adding (symbol, weight) to a FINAL
        portfolio, or None when the final state does not violate.

        Used to label non-selected candidates with the TRUE final-state
        reason (R4-S 2026-09-08): a candidate that tripped a hard cap in an
        early greedy trial may not violate against the final selection, so
        the recorded rejection reason must be recomputed here, never carried
        over from an intermediate step.
        """
        trial = dict(final_weights)
        trial[symbol] = weight
        violations = self.violates(trial)
        return violations[0] if violations else None
