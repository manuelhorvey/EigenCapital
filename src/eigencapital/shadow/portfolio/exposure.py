"""Exposure model for the R4-S shadow portfolio constructor.

Derives underlying currency/factor exposure for every candidate from the
portfolio's signed weights, so the selector can see when "10 different
trades" are really "1-3 underlying macro/factor bets".

REUSE: currency/asset-class classification reuses the canonical maps in
`eigencapital.live.portfolio_analytics` (SYMBOL_CURRENCY_MAP, CURRENCIES,
ASSET_CLASS_MAP) rather than duplicating them.

Factor groups (risk_on / usd / commodity / equity_beta / safe_haven) are
derived, lightweight, and DIAGNOSTIC ONLY — they are recorded in shadow
evidence for cluster diagnostics and are never used as trading rules.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Tuple

from eigencapital.live.portfolio_analytics import (
    ASSET_CLASS_MAP,
    CURRENCIES,
    SYMBOL_CURRENCY_MAP,
)

# Symbols absent from the analytics maps (indices/energy/crypto singles).
SINGLE_LEG_ASSET_CLASS: Dict[str, str] = {
    "US30": "indices",
    "USTEC": "indices",
    "US500": "indices",
    "XAUUSD": "metals",
    "XAGUSD": "metals",
    "BTCUSD": "crypto",
    "ETHUSD": "crypto",
    "USOIL": "energy",
}

# Derived macro/factor group per instrument. Lightweight, evidence-oriented;
# NOT a static trading rule (correlation remains estimated from returns).
FACTOR_GROUP: Dict[str, str] = {
    "US30": "equity_beta",
    "USTEC": "equity_beta",
    "US500": "equity_beta",
    "BTCUSD": "equity_beta",  # empirically high equity-beta in risk-off
    "ETHUSD": "equity_beta",
    "XAUUSD": "safe_haven",
    "XAGUSD": "commodity",
    "USOIL": "commodity",
}

_CURRENCY_SET = set(CURRENCIES)


def _classify_asset_class(symbol: str) -> str:
    if symbol in ASSET_CLASS_MAP:
        return ASSET_CLASS_MAP[symbol]
    if symbol in SINGLE_LEG_ASSET_CLASS:
        return SINGLE_LEG_ASSET_CLASS[symbol]
    for c1 in CURRENCIES:
        for c2 in CURRENCIES:
            if c1 != c2 and symbol.startswith(c1) and symbol.endswith(c2):
                return "forex"
    return "other"


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
    if symbol in FACTOR_GROUP:
        return FACTOR_GROUP[symbol]
    asset_class = _classify_asset_class(symbol)
    if asset_class == "metals":
        return "safe_haven"
    if asset_class == "energy":
        return "commodity"
    if asset_class == "forex":
        base, quote = get_currencies(symbol)
        # Commodity currencies proxy the commodity factor.
        if "AUD" in (base, quote) or "NZD" in (base, quote) or "CAD" in (base, quote):
            return "commodity"
        if base == "JPY" or quote == "JPY":
            return "safe_haven"
        return "risk_on"
    return "other"


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
            ac = _classify_asset_class(sym)
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
