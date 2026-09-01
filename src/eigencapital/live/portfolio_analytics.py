"""Shadow Portfolio Analytics — read-only diagnostics for Phase 3 preparation.

Computes portfolio-level risk metrics WITHOUT affecting live trading behavior.
Designed to be called from the rebalance loop audit trail, recording what the
portfolio actually looks like at each rebalance cycle.

GOVERNANCE INVARIANT (Phase 2):
    Shadow analytics may observe, calculate, persist, visualize, and generate
    research evidence. They may NOT modify signal weights, selection, sizing,
    order quantity, execution sequence, risk approval, or broker state.

Metrics computed:
    CONCENTRATION (weight-based, no correlation):
        - Gross / net exposure and leverage
        - Currency-factor decomposition (USD, EUR, GBP, AUD, NZD, CAD, CHF, JPY)
        - Asset-class exposure (FX, metals, indices, crypto)
        - Herfindahl-Hirschman Index (HHI)
        - Effective number of positions = 1/HHI (weight-concentration only)
        - Top-N concentration (top-3, top-5)
        - Max position weight

    DEPENDENCE (correlation-aware, requires historical returns):
        - Rolling pairwise correlation matrix
        - Average pairwise correlation
        - Correlation-adjusted effective bets (from covariance eigenvalues)
        - Highly correlated clusters

    COUNTERFACTUALS (what-if analysis, never executed):
        - Current R4 portfolio (baseline)
        - Equal-weight portfolio
        - Inverse-volatility portfolio
        - Factor-constrained portfolio

All outputs are append-only JSONL records. Zero impact on order generation.

IMPORTANT DISTINCTION:
    "Effective number of positions" (1/HHI) measures weight concentration.
    "Effective number of independent bets" requires correlation adjustment.
    A portfolio with 10 equal-weight positions has 10 effective positions
    but may have far fewer independent risk factors if positions are
    highly correlated. These are different metrics.

Usage:
    analyzer = PortfolioAnalyzer()

    # After computing target weights and generating orders
    diagnostics = analyzer.compute_diagnostics(
        target_weights=latest_weights,
        current_positions=current_lots,
        prices=prices,
        contract_sizes=contract_sizes,
        equity=equity,
        returns_history=returns_df,  # optional: for correlation diagnostics
    )

    # Append to audit trail
    analyzer.record(diagnostics)
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Dict, List, Tuple

# ── Currency Factor Definitions ──────────────────────────────────

CURRENCIES = ["USD", "EUR", "GBP", "AUD", "NZD", "CAD", "CHF", "JPY"]

SYMBOL_CURRENCY_MAP: Dict[str, Tuple[str, str]] = {
    "EURUSD": ("EUR", "USD"),
    "GBPUSD": ("GBP", "USD"),
    "AUDUSD": ("AUD", "USD"),
    "NZDUSD": ("NZD", "USD"),
    "USDCAD": ("USD", "CAD"),
    "USDCHF": ("USD", "CHF"),
    "USDJPY": ("USD", "JPY"),
    "EURGBP": ("EUR", "GBP"),
    "EURAUD": ("EUR", "AUD"),
    "EURNZD": ("EUR", "NZD"),
    "EURCAD": ("EUR", "CAD"),
    "EURCHF": ("EUR", "CHF"),
    "EURJPY": ("EUR", "JPY"),
    "GBPAUD": ("GBP", "AUD"),
    "GBPNZD": ("GBP", "NZD"),
    "GBPCAD": ("GBP", "CAD"),
    "GBPCHF": ("GBP", "CHF"),
    "GBPJPY": ("GBP", "JPY"),
    "AUDNZD": ("AUD", "NZD"),
    "AUDCAD": ("AUD", "CAD"),
    "AUDCHF": ("AUD", "CHF"),
    "AUDJPY": ("AUD", "JPY"),
    "NZDCAD": ("NZD", "CAD"),
    "NZDCHF": ("NZD", "CHF"),
    "NZDJPY": ("NZD", "JPY"),
    "CADCHF": ("CAD", "CHF"),
    "CADJPY": ("CAD", "JPY"),
    "CHFJPY": ("CHF", "JPY"),
}

ASSET_CLASS_MAP: Dict[str, str] = {
    "US30": "indices",
    "USTEC": "indices",
    "XAUUSD": "metals",
    "XAGUSD": "metals",
    "BTCUSD": "crypto",
    "ETHUSD": "crypto",
    "USOIL": "energy",
}


def _classify_asset_class(symbol: str) -> str:
    if symbol in ASSET_CLASS_MAP:
        return ASSET_CLASS_MAP[symbol]
    for c1 in CURRENCIES:
        for c2 in CURRENCIES:
            if c1 != c2 and symbol.startswith(c1) and symbol.endswith(c2):
                return "forex"
    return "other"


def _get_currencies(symbol: str) -> Tuple[str, str]:
    if symbol in SYMBOL_CURRENCY_MAP:
        return SYMBOL_CURRENCY_MAP[symbol]
    for c1 in CURRENCIES:
        for c2 in CURRENCIES:
            if c1 != c2 and symbol.startswith(c1) and symbol.endswith(c2):
                return (c1, c2)
    return ("", "")


def _compute_currency_exposure(
    symbol: str,
    weight: float,
    notional: float,
    direction: str,
) -> Dict[str, float]:
    base, quote = _get_currencies(symbol)
    if not base or not quote:
        return {}
    sign = 1.0 if direction == "LONG" else -1.0
    return {
        base: sign * notional,
        quote: -sign * notional,
    }


def _compute_correlation_adjusted_bets(
    returns: Any,  # pd.DataFrame of returns, columns=symbols
    weights: Dict[str, float],  # symbol → weight
) -> Dict[str, Any]:
    """Compute correlation-adjusted effective number of bets.

    Uses the eigendecomposition of the correlation matrix:
        N_eff_corr = (sum(w_i))^2 / (w' Σ w)

    where Σ is the correlation matrix and w is the weight vector.

    Also computes:
        - Average pairwise correlation
        - Number of highly correlated clusters (|corr| > 0.7)
        - Largest eigenvalue fraction (market factor dominance)

    Returns dict with all correlation diagnostics.
    Returns empty dict if returns DataFrame is insufficient.
    """
    try:
        import numpy as np
        import pandas as pd

        if returns is None or not isinstance(returns, pd.DataFrame):
            return {}
        if len(returns) < 30:  # Need reasonable history
            return {}
        if not weights:
            return {}

        # Align symbols
        active_symbols = [s for s in weights if s in returns.columns]
        if len(active_symbols) < 2:
            return {}

        # Compute correlation matrix from recent returns
        recent = returns[active_symbols].tail(60)  # 60-day rolling
        if len(recent) < 30:
            return {}

        corr_matrix = recent.corr()

        # Build weight vector aligned with correlation matrix
        w = np.array([weights[s] for s in active_symbols])
        w_abs = np.abs(w)
        w_sum = w_abs.sum()
        if w_sum <= 0:
            return {}

        # Normalize weights for the formula
        w_norm = w_abs / w_sum

        # Correlation-adjusted effective bets:
        # N_eff = (sum(w_i))^2 / (w' Σ w)
        # Using absolute weights since we care about magnitude of exposure
        corr_np = corr_matrix.values
        portfolio_variance = w_norm @ corr_np @ w_norm
        if portfolio_variance <= 0:
            return {}

        effective_bets = 1.0 / portfolio_variance

        # Average pairwise correlation (off-diagonal)
        n = len(active_symbols)
        if n > 1:
            mask = np.ones((n, n), dtype=bool)
            np.fill_diagonal(mask, False)
            avg_corr = float(np.mean(corr_np[mask]))
        else:
            avg_corr = 0.0

        # Highly correlated clusters (|corr| > 0.7)
        clusters = []
        for i in range(n):
            for j in range(i + 1, n):
                if abs(corr_np[i, j]) > 0.7:
                    clusters.append(
                        {
                            "pair": (active_symbols[i], active_symbols[j]),
                            "correlation": round(float(corr_np[i, j]), 4),
                        }
                    )

        # Eigenvalue analysis (market factor dominance)
        eigenvalues = np.linalg.eigvalsh(corr_np)
        eigenvalues = np.sort(eigenvalues)[::-1]  # descending
        total_variance = float(np.sum(eigenvalues))
        market_factor_fraction = float(eigenvalues[0] / total_variance) if total_variance > 0 else 0

        return {
            "effective_bets": round(float(effective_bets), 2),
            "avg_pairwise_correlation": round(avg_corr, 4),
            "high_corr_clusters": clusters,
            "cluster_count": len(clusters),
            "market_factor_fraction": round(market_factor_fraction, 4),
            "largest_eigenvalue": round(float(eigenvalues[0]), 4) if len(eigenvalues) > 0 else 0,
            "symbols_used": active_symbols,
            "observations_used": len(recent),
        }
    except Exception:
        return {}


def _compute_counterfactuals(
    active_symbols: List[str],
    weights: Dict[str, float],
    prices: Dict[str, float],
    contract_sizes: Dict[str, float],
    equity: float,
    returns: Any = None,  # pd.DataFrame
) -> Dict[str, Any]:
    """Compute counterfactual portfolio constructions (shadow-only, never executed).

    Compares current R4 allocation against:
    1. Equal weight
    2. Inverse volatility
    3. Factor-constrained (equal currency exposure)

    Returns dict of portfolio_name → {weights, concentration, effective_positions}.
    """
    try:
        import numpy as np
        import pandas as pd

        if not active_symbols or not weights:
            return {}

        counterfactuals = {}

        # 1. Equal weight
        n = len(active_symbols)
        eq_weight = 1.0 / n
        eq_hhi = n * (eq_weight**2)
        counterfactuals["equal_weight"] = {
            "weights": {s: round(eq_weight, 4) for s in active_symbols},
            "herfindahl": round(eq_hhi, 6),
            "effective_positions": round(1.0 / eq_hhi, 2) if eq_hhi > 0 else 0,
        }

        # 2. Inverse volatility
        if returns is not None and isinstance(returns, pd.DataFrame):
            vols = {}
            for s in active_symbols:
                if s in returns.columns and len(returns[s].dropna()) >= 20:
                    vol = returns[s].tail(60).std() * np.sqrt(252)
                    if vol > 0:
                        vols[s] = vol

            if len(vols) >= 2:
                inv_vol_total = sum(1.0 / v for v in vols.values())
                iv_weights = {}
                for s in active_symbols:
                    if s in vols:
                        iv_weights[s] = (1.0 / vols[s]) / inv_vol_total
                    else:
                        iv_weights[s] = 0.0

                # Normalize to sum to 1 among active
                active_sum = sum(abs(w) for w in iv_weights.values())
                if active_sum > 0:
                    iv_weights = {s: w / active_sum for s, w in iv_weights.items()}

                iv_hhi = sum(w**2 for w in iv_weights.values())
                counterfactuals["inverse_volatility"] = {
                    "weights": {s: round(w, 4) for s, w in iv_weights.items()},
                    "herfindahl": round(iv_hhi, 6),
                    "effective_positions": round(1.0 / iv_hhi, 2) if iv_hhi > 0 else 0,
                }

        # 3. Factor-constrained: equal exposure per currency
        # (simplified: weight each position to equalize currency contribution)
        currency_buckets: Dict[str, float] = {}
        for s in active_symbols:
            base, quote = _get_currencies(s)
            w = abs(weights.get(s, 0))
            if base:
                currency_buckets[base] = currency_buckets.get(base, 0) + w
            if quote:
                currency_buckets[quote] = currency_buckets.get(quote, 0) + w

        if currency_buckets:
            target_per_ccy = 1.0 / len(currency_buckets) if currency_buckets else 0
            # For now, just report the current currency imbalance vs equal
            counterfactuals["factor_equal_currency"] = {
                "current_currency_weights": {c: round(v, 4) for c, v in currency_buckets.items()},
                "target_per_currency": round(target_per_ccy, 4),
                "currency_count": len(currency_buckets),
                "note": "Phase 3: full implementation requires iterative solver",
            }

        return counterfactuals
    except Exception:
        return {}


@dataclass
class PortfolioDiagnostics:
    """Complete portfolio diagnostics snapshot.

    Two distinct metrics for portfolio "diversification":

    1. effective_positions (HHI-based):
       Measures weight concentration. 1/HHI where HHI = sum(w_i^2).
       A portfolio with 10 equal weights has effective_positions = 10.
       Does NOT account for correlation.

    2. effective_bets (correlation-adjusted):
       Uses eigendecomposition of correlation matrix.
       Accounts for the fact that correlated positions are not independent.
       Requires historical returns data.
    """

    timestamp: str
    equity: float
    position_count: int

    # Exposure
    gross_exposure: float
    net_exposure: float
    long_exposure: float
    short_exposure: float
    gross_leverage: float
    net_leverage: float

    # Currency factors
    currency_exposure: Dict[str, float]
    currency_exposure_pct: Dict[str, float]
    largest_currency_factor: str
    largest_currency_factor_pct: float

    # Asset class
    asset_class_exposure: Dict[str, float]
    asset_class_exposure_pct: Dict[str, float]
    largest_asset_class: str
    largest_asset_class_pct: float

    # Concentration (weight-based, no correlation)
    max_position_weight: float
    max_position_symbol: str
    top3_concentration: float  # sum of top-3 weights
    top5_concentration: float  # sum of top-5 weights
    herfindahl_index: float
    effective_positions: float  # 1/HHI — weight concentration only

    # Dependence (correlation-aware, requires returns history)
    correlation_diagnostics: Dict[str, Any]  # from _compute_correlation_adjusted_bets

    # Counterfactuals (what-if, never executed)
    counterfactuals: Dict[str, Any]

    # Position details
    positions: List[Dict[str, Any]]

    # Signal details
    target_weights: Dict[str, float]
    long_count: int
    short_count: int

    # Methodology metadata
    analytics_version: str = "1.0"
    state_label: str = "pre_trade"  # pre_trade | post_trade | hypothetical

    def to_dict(self) -> Dict[str, Any]:
        return {
            "analytics_version": self.analytics_version,
            "state_label": self.state_label,
            "timestamp": self.timestamp,
            "equity": self.equity,
            "position_count": self.position_count,
            "gross_exposure": self.gross_exposure,
            "net_exposure": self.net_exposure,
            "long_exposure": self.long_exposure,
            "short_exposure": self.short_exposure,
            "gross_leverage": self.gross_leverage,
            "net_leverage": self.net_leverage,
            "currency_exposure": self.currency_exposure,
            "currency_exposure_pct": self.currency_exposure_pct,
            "largest_currency_factor": self.largest_currency_factor,
            "largest_currency_factor_pct": self.largest_currency_factor_pct,
            "asset_class_exposure": self.asset_class_exposure,
            "asset_class_exposure_pct": self.asset_class_exposure_pct,
            "largest_asset_class": self.largest_asset_class,
            "largest_asset_class_pct": self.largest_asset_class_pct,
            "max_position_weight": self.max_position_weight,
            "max_position_symbol": self.max_position_symbol,
            "top3_concentration": self.top3_concentration,
            "top5_concentration": self.top5_concentration,
            "herfindahl_index": self.herfindahl_index,
            "effective_positions": self.effective_positions,
            "correlation_diagnostics": self.correlation_diagnostics,
            "counterfactuals": self.counterfactuals,
            "positions": self.positions,
            "target_weights": self.target_weights,
            "long_count": self.long_count,
            "short_count": self.short_count,
        }


class PortfolioAnalyzer:
    """Shadow-only portfolio analytics engine.

    GOVERNANCE INVARIANT (Phase 2):
        This class may observe, calculate, persist, visualize, and generate
        research evidence. It may NOT modify signal weights, selection, sizing,
        order quantity, execution sequence, risk approval, or broker state.

    Computes all metrics as read-only diagnostics.
    Zero impact on order generation or risk gates.
    """

    def __init__(
        self,
        audit_dir: str = "reports/r4_loop",
    ) -> None:
        self._audit_dir = Path(audit_dir)
        self._analytics_file = self._audit_dir / "portfolio_analytics.jsonl"
        self._audit_dir.mkdir(parents=True, exist_ok=True)

    def compute_diagnostics(
        self,
        target_weights: Any,  # pd.Series
        current_positions: Dict[str, float],  # symbol → signed lots
        prices: Dict[str, float],  # symbol → price
        contract_sizes: Dict[str, float],  # symbol → contract_size
        equity: float,
        order_count: int = 0,
        order_symbols: List[str] | None = None,
        returns_history: Any = None,  # pd.DataFrame of daily returns (optional)
    ) -> PortfolioDiagnostics:
        """Compute comprehensive portfolio diagnostics.

        All computations are pure functions of the inputs.
        No state modification, no side effects.
        """
        now = datetime.now(UTC).isoformat()
        capped_equity = min(equity, 5100.0)

        # ── Build position details ──────────────────────────────
        positions = []
        long_exposure = 0.0
        short_exposure = 0.0
        currency_exposure: Dict[str, float] = {c: 0.0 for c in CURRENCIES}
        asset_class_exposure: Dict[str, float] = {}
        weight_sum_sq = 0.0
        all_weights: Dict[str, float] = {}
        max_weight = 0.0
        max_sym = ""
        long_count = 0
        short_count = 0

        for sym, signed_lots in current_positions.items():
            if signed_lots == 0:
                continue

            price = prices.get(sym, 0)
            cs = contract_sizes.get(sym, 0)
            if price <= 0 or cs <= 0:
                continue

            notional = abs(signed_lots) * price * cs
            direction = "LONG" if signed_lots > 0 else "SHORT"
            weight = notional / capped_equity if capped_equity > 0 else 0

            if signed_lots > 0:
                long_exposure += notional
                long_count += 1
            else:
                short_exposure += notional
                short_count += 1

            # Currency exposure
            curr_exp = _compute_currency_exposure(sym, weight, notional, direction)
            for c, exp in curr_exp.items():
                if c in currency_exposure:
                    currency_exposure[c] += exp

            # Asset class
            ac = _classify_asset_class(sym)
            asset_class_exposure[ac] = asset_class_exposure.get(ac, 0) + notional

            # Concentration
            weight_sum_sq += weight**2
            all_weights[sym] = weight
            if weight > max_weight:
                max_weight = weight
                max_sym = sym

            positions.append(
                {
                    "symbol": sym,
                    "direction": direction,
                    "signed_lots": signed_lots,
                    "notional": notional,
                    "weight": weight,
                    "asset_class": ac,
                }
            )

        gross_exposure = long_exposure + short_exposure
        net_exposure = long_exposure - short_exposure
        gross_leverage = gross_exposure / capped_equity if capped_equity > 0 else 0
        net_leverage = net_exposure / capped_equity if capped_equity > 0 else 0

        # ── Concentration metrics ───────────────────────────────
        herfindahl = weight_sum_sq
        effective_positions = 1.0 / herfindahl if herfindahl > 0 else 0.0

        # Top-N concentration
        sorted_weights = sorted(all_weights.values(), reverse=True)
        top3_concentration = sum(sorted_weights[:3])
        top5_concentration = sum(sorted_weights[:5])

        # Currency exposure as % of equity
        currency_pct = {c: exp / capped_equity if capped_equity > 0 else 0 for c, exp in currency_exposure.items()}

        # Find largest currency factor
        if currency_exposure:
            largest_ccy = max(currency_exposure, key=lambda c: abs(currency_exposure[c]))
            largest_ccy_pct = abs(currency_pct.get(largest_ccy, 0))
        else:
            largest_ccy = ""
            largest_ccy_pct = 0.0

        # Asset class as % of equity
        asset_class_pct = {
            ac: exp / capped_equity if capped_equity > 0 else 0 for ac, exp in asset_class_exposure.items()
        }

        # Find largest asset class
        if asset_class_exposure:
            largest_ac = max(asset_class_exposure, key=lambda a: asset_class_exposure[a])
            largest_ac_pct = asset_class_pct.get(largest_ac, 0)
        else:
            largest_ac = ""
            largest_ac_pct = 0.0

        # ── Correlation diagnostics ─────────────────────────────
        correlation_diag = _compute_correlation_adjusted_bets(
            returns_history,
            all_weights,
        )

        # ── Counterfactuals ─────────────────────────────────────
        counterfactuals = _compute_counterfactuals(
            active_symbols=list(all_weights.keys()),
            weights=all_weights,
            prices=prices,
            contract_sizes=contract_sizes,
            equity=capped_equity,
            returns=returns_history,
        )

        # Target weights as dict
        weights_dict = {}
        if hasattr(target_weights, "items"):
            for sym, w in target_weights.items():
                if abs(w) > 0.001:
                    weights_dict[sym] = float(w)

        return PortfolioDiagnostics(
            timestamp=now,
            equity=capped_equity,
            position_count=sum(1 for v in current_positions.values() if v != 0),
            gross_exposure=gross_exposure,
            net_exposure=net_exposure,
            long_exposure=long_exposure,
            short_exposure=short_exposure,
            gross_leverage=gross_leverage,
            net_leverage=net_leverage,
            currency_exposure={c: round(v, 2) for c, v in currency_exposure.items() if abs(v) > 0.01},
            currency_exposure_pct={c: round(v, 4) for c, v in currency_pct.items() if abs(v) > 0.001},
            largest_currency_factor=largest_ccy,
            largest_currency_factor_pct=round(largest_ccy_pct, 4),
            asset_class_exposure={ac: round(v, 2) for ac, v in asset_class_exposure.items()},
            asset_class_exposure_pct={ac: round(v, 4) for ac, v in asset_class_pct.items()},
            largest_asset_class=largest_ac,
            largest_asset_class_pct=round(largest_ac_pct, 4),
            max_position_weight=round(max_weight, 4),
            max_position_symbol=max_sym,
            top3_concentration=round(top3_concentration, 4),
            top5_concentration=round(top5_concentration, 4),
            herfindahl_index=round(herfindahl, 6),
            effective_positions=round(effective_positions, 2),
            correlation_diagnostics=correlation_diag,
            counterfactuals=counterfactuals,
            positions=positions,
            target_weights=weights_dict,
            long_count=long_count,
            short_count=short_count,
        )

    def record(self, diagnostics: PortfolioDiagnostics) -> None:
        """Append diagnostics to the audit trail.

        Pure append — no modification of existing records.
        """
        with open(self._analytics_file, "a") as f:
            f.write(json.dumps(diagnostics.to_dict(), default=str) + "\n")

    def get_latest(self) -> PortfolioDiagnostics | None:
        """Read the most recent diagnostics record."""
        if not self._analytics_file.exists():
            return None
        try:
            last_line = ""
            with open(self._analytics_file, "rb") as f:
                f.seek(0, 2)
                fsize = f.tell()
                read_size = min(4096, fsize)
                f.seek(max(0, fsize - read_size))
                tail = f.read().decode("utf-8", errors="replace")
                for line in reversed(tail.split("\n")):
                    line = line.strip()
                    if line:
                        last_line = line
                        break
            if last_line:
                data = json.loads(last_line)
                return PortfolioDiagnostics(
                    timestamp=data.get("timestamp", ""),
                    equity=data.get("equity", 0),
                    position_count=data.get("position_count", 0),
                    analytics_version=data.get("analytics_version", "1.0"),
                    state_label=data.get("state_label", "pre_trade"),
                    gross_exposure=data.get("gross_exposure", 0),
                    net_exposure=data.get("net_exposure", 0),
                    long_exposure=data.get("long_exposure", 0),
                    short_exposure=data.get("short_exposure", 0),
                    gross_leverage=data.get("gross_leverage", 0),
                    net_leverage=data.get("net_leverage", 0),
                    currency_exposure=data.get("currency_exposure", {}),
                    currency_exposure_pct=data.get("currency_exposure_pct", {}),
                    largest_currency_factor=data.get("largest_currency_factor", ""),
                    largest_currency_factor_pct=data.get("largest_currency_factor_pct", 0),
                    asset_class_exposure=data.get("asset_class_exposure", {}),
                    asset_class_exposure_pct=data.get("asset_class_exposure_pct", {}),
                    largest_asset_class=data.get("largest_asset_class", ""),
                    largest_asset_class_pct=data.get("largest_asset_class_pct", 0),
                    max_position_weight=data.get("max_position_weight", 0),
                    max_position_symbol=data.get("max_position_symbol", ""),
                    top3_concentration=data.get("top3_concentration", 0),
                    top5_concentration=data.get("top5_concentration", 0),
                    herfindahl_index=data.get("herfindahl_index", 0),
                    effective_positions=data.get("effective_positions", 0),
                    correlation_diagnostics=data.get("correlation_diagnostics", {}),
                    counterfactuals=data.get("counterfactuals", {}),
                    positions=data.get("positions", []),
                    target_weights=data.get("target_weights", {}),
                    long_count=data.get("long_count", 0),
                    short_count=data.get("short_count", 0),
                )
        except (json.JSONDecodeError, OSError):
            pass
        return None

    def get_history(self, last_n: int = 100) -> List[Dict[str, Any]]:
        """Read the last N analytics records."""
        if not self._analytics_file.exists():
            return []
        records = []
        try:
            with open(self._analytics_file) as f:
                for line in f:
                    line = line.strip()
                    if line:
                        records.append(json.loads(line))
        except (json.JSONDecodeError, OSError):
            pass
        return records[-last_n:]

    def format_summary(self, d: PortfolioDiagnostics) -> str:
        """Format a human-readable summary of portfolio diagnostics."""
        lines = [
            f"Portfolio Analytics — {d.timestamp}",
            f"  Equity: ${d.equity:,.2f}",
            f"  Positions: {d.position_count} ({d.long_count} long, {d.short_count} short)",
            "",
            "  Exposure:",
            f"    Gross: ${d.gross_exposure:,.2f} ({d.gross_leverage:.2f}x leverage)",
            f"    Net:   ${d.net_exposure:,.2f} ({d.net_leverage:.2f}x net leverage)",
            f"    Long:  ${d.long_exposure:,.2f}",
            f"    Short: ${d.short_exposure:,.2f}",
            "",
            "  Currency Factors:",
        ]
        for c in CURRENCIES:
            exp = d.currency_exposure.get(c, 0)
            pct = d.currency_exposure_pct.get(c, 0)
            if abs(exp) > 0.01:
                direction = "LONG" if exp > 0 else "SHORT"
                lines.append(f"    {c}: {direction} ${abs(exp):,.2f} ({pct:+.1%} of equity)")

        if d.largest_currency_factor:
            lines.append(f"    → Largest: {d.largest_currency_factor} ({d.largest_currency_factor_pct:+.1%})")

        lines.extend(
            [
                "",
                "  Asset Classes:",
            ]
        )
        for ac, exp in sorted(d.asset_class_exposure.items(), key=lambda x: -abs(x[1])):
            pct = d.asset_class_exposure_pct.get(ac, 0)
            lines.append(f"    {ac}: ${exp:,.2f} ({pct:.1%} of equity)")

        lines.extend(
            [
                "",
                "  Concentration:",
                f"    Max position: {d.max_position_symbol} ({d.max_position_weight:.1%})",
                f"    Top-3: {d.top3_concentration:.1%}  Top-5: {d.top5_concentration:.1%}",
                f"    HHI: {d.herfindahl_index:.4f}",
                f"    Effective positions (1/HHI): {d.effective_positions:.1f}",
            ]
        )

        # Correlation diagnostics
        cd = d.correlation_diagnostics
        if cd:
            lines.extend(
                [
                    "",
                    "  Correlation:",
                    f"    Avg pairwise corr: {cd.get('avg_pairwise_correlation', 0):.3f}",
                    f"    Effective bets (corr-adjusted): {cd.get('effective_bets', 0):.1f}",
                    f"    Market factor fraction: {cd.get('market_factor_fraction', 0):.1%}",
                ]
            )
            clusters = cd.get("high_corr_clusters", [])
            if clusters:
                lines.append(f"    High-corr clusters: {len(clusters)}")
                for cl in clusters[:3]:
                    lines.append(f"      {cl['pair'][0]}<->{cl['pair'][1]}: {cl['correlation']:.3f}")

        lines.append("")
        return "\n".join(lines)
