"""High-Volatility Satellite for portfolio isolation.

Extracts designated high-vol assets (initially BTC) from the main portfolio
into a separate construct with:

  1. Independent risk overlay (vol target, drawdown limit)
  2. Regime gate (correlation, vol, macro, CRISIS conditions)
  3. Hard capital cap with auto-reduction on marginal contribution decay
  4. Separate P&L accounting — never bleeds into core Sharpe
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field

import numpy as np

logger = logging.getLogger("quantforge.satellite")


@dataclass
class SatelliteConfig:
    """Configuration for a high-vol satellite bucket.

    Tune via survival sim output from PR #2 before going live.
    """

    # ── Capital constraints ────────────────────────────────────────
    max_allocation_pct: float = 0.05  # hard cap: 5% of AUM
    vol_target: float = 0.40  # separate annualised vol target
    max_drawdown_pct: float = -0.25  # separate max drawdown limit

    # ── Regime gate thresholds ─────────────────────────────────────
    max_correlation_to_portfolio: float = 0.30  # max rolling corr to core
    max_btc_vol_zscore: float = 2.0  # max BTC vol z-score to enter
    vix_threshold: float = 25.0  # VIX below this = risk-on
    dxy_momentum_threshold: float = 0.02  # max DXY 21d momentum (appreciation)
    min_crisis_regime_gap_days: int = 5  # days since last CRISIS regime flag

    # ── SL/TP multipliers (applied to entry price) ─────────────────
    sl_mult: float = 0.58  # stop = entry * (1 - sl_mult)
    tp_mult: float = 1.51  # target = entry * (1 + tp_mult)

    # ── Marginal contribution monitoring ───────────────────────────
    contribution_window_days: int = 63  # rolling window for ΔSharpe calc
    delta_sharpe_alert_threshold: float = -0.5  # soft alert trigger
    delta_sharpe_reduce_threshold: float = -1.0  # auto-reduce allocation


@dataclass
class GateDecision:
    """Result of a regime gate evaluation."""

    allowed: bool
    reasons_blocked: list[str] = field(default_factory=list)
    correlation_value: float = 0.0
    btc_vol_zscore: float = 0.0
    vix_value: float = 0.0
    dxy_momentum: float = 0.0
    days_since_crisis: int = 999


@dataclass
class SatelliteSnapshot:
    """Point-in-time state of the satellite bucket."""

    allocation_pct: float
    gate_open: bool
    gate_reasons: list[str]
    current_value: float
    total_return_pct: float
    sharpe_contribution: float
    delta_sharpe_63d: float
    position_active: bool
    drawdown_pct: float
    entry_price: float | None = None
    stop_price: float | None = None
    target_price: float | None = None
    exit_reason: str | None = None


class HighVolSatellite:
    """Manages a high-volatility asset bucket isolated from the main portfolio.

    Usage:
        satellite = HighVolSatellite(total_aum=100_000, config=sconfig)
        decision = satellite.evaluate_gate(vix=18.0, dxy_mom_21=-0.01, ...)
        satellite.update_pnl(btc_daily_return)
        snapshot = satellite.get_state()
    """

    def __init__(
        self,
        total_aum: float,
        config: SatelliteConfig | None = None,
        name: str = "BTC",
    ):
        self.name = name
        self.config = config or SatelliteConfig()
        self.total_aum = total_aum

        # Capital
        self.max_capital = total_aum * self.config.max_allocation_pct
        self.current_value = 0.0
        self.peak_value = 0.0
        self.initial_capital = 0.0

        # Position
        self.position_active = False
        self.position_entry = 0.0
        self.position_side: str | None = None
        self.entry_price: float | None = None
        self.stop_price: float | None = None
        self.target_price: float | None = None
        self._last_exit_reason: str | None = None

        # Rolling performance buffer
        self._daily_returns: list[float] = []
        self._max_window = max(
            self.config.contribution_window_days,
            self.config.min_crisis_regime_gap_days + 10,
            252,
        )

        # Gate state
        self._last_gate: GateDecision | None = None
        self._days_since_last_crisis_flag = 999
        self._consecutive_gate_closed = 0

    # ── Regime Gate ─────────────────────────────────────────────────

    def evaluate_gate(
        self,
        vix: float = 0.0,
        dxy_mom_21: float = 0.0,
        btc_vol_zscore: float = 0.0,
        portfolio_returns_63d: np.ndarray | None = None,
        btc_returns_63d: np.ndarray | None = None,
        crisis_regime_active: bool = False,
    ) -> GateDecision:
        """Evaluate whether the satellite should be active.

        ALL conditions must be true for the gate to open:
          1. BTC-to-portfolio correlation < max_correlation_to_portfolio
          2. BTC-specific vol z-score < max_btc_vol_zscore
          3. VIX < vix_threshold (risk-on macro regime)
          4. DXY 21d momentum < threshold (no USD strength shock)
          5. No active CRISIS regime flag (or sufficient gap since last)
        """
        reasons: list[str] = []

        # ── Condition 1: Correlation gate ──────────────────────────
        correlation = 0.0
        if (
            portfolio_returns_63d is not None
            and btc_returns_63d is not None
            and len(portfolio_returns_63d) > 5
            and len(btc_returns_63d) > 5
        ):
            corr_matrix = np.corrcoef(portfolio_returns_63d[-63:], btc_returns_63d[-63:])
            correlation = float(corr_matrix[0, 1]) if corr_matrix.shape == (2, 2) else 0.0
            if abs(correlation) > self.config.max_correlation_to_portfolio:
                reasons.append(f"correlation {correlation:.2f} > {self.config.max_correlation_to_portfolio}")

        # ── Condition 2: Vol gate ──────────────────────────────────
        if btc_vol_zscore > self.config.max_btc_vol_zscore:
            reasons.append(f"BTC vol z-score {btc_vol_zscore:.1f} > {self.config.max_btc_vol_zscore}")

        # ── Condition 3: VIX gate (risk-on macro) ──────────────────
        if vix > self.config.vix_threshold:
            reasons.append(f"VIX {vix:.1f} > {self.config.vix_threshold}")

        # ── Condition 4: DXY momentum gate ─────────────────────────
        abs_dxy = abs(dxy_mom_21)
        if abs_dxy > self.config.dxy_momentum_threshold:
            reasons.append(
                f"DXY momentum {dxy_mom_21:+.4f} exceeds threshold \u00b1{self.config.dxy_momentum_threshold}"
            )

        # ── Condition 5: CRISIS regime gate ────────────────────────
        if crisis_regime_active:
            self._days_since_last_crisis_flag = 0
        else:
            self._days_since_last_crisis_flag = min(self._days_since_last_crisis_flag + 1, 9999)
        if self._days_since_last_crisis_flag < self.config.min_crisis_regime_gap_days:
            reasons.append(
                f"CRISIS regime active {self._days_since_last_crisis_flag}d ago "
                f"(need {self.config.min_crisis_regime_gap_days}d gap)"
            )

        allowed = len(reasons) == 0

        if allowed:
            self._consecutive_gate_closed = 0
        else:
            self._consecutive_gate_closed += 1

        decision = GateDecision(
            allowed=allowed,
            reasons_blocked=reasons,
            correlation_value=correlation,
            btc_vol_zscore=btc_vol_zscore,
            vix_value=vix,
            dxy_momentum=dxy_mom_21,
            days_since_crisis=self._days_since_last_crisis_flag,
        )
        self._last_gate = decision
        return decision

    def gate_is_open(self) -> bool:
        return self._last_gate is not None and self._last_gate.allowed

    # ── P&L and Position Management ────────────────────────────────

    def record_return(self, daily_return: float) -> None:
        """Record a daily return and update capital."""
        self._daily_returns.append(daily_return)
        if len(self._daily_returns) > self._max_window:
            self._daily_returns = self._daily_returns[-self._max_window :]

        # Update capital
        if self.position_active:
            self.current_value *= 1.0 + daily_return
        self.peak_value = max(self.peak_value, self.current_value)

    def open_position(self, entry_price: float, side: str = "long", vol: float | None = None) -> None:
        """Open a position in the satellite with vol-adjusted SL/TP levels.

        SL/TP are computed as::

            stop  = entry * (1 - vol * sl_mult)
            target = entry * (1 + vol * tp_mult)

        This mirrors :meth:`PositionIntent.from_price_and_vol`.
        If *vol* is ``None`` the configured vol baseline is used.
        """
        if not self.gate_is_open():
            logger.warning("%s satellite: gate closed, blocking position open", self.name)
            return
        v = vol if vol is not None else 0.45  # fallback BTC vol baseline
        sl_pct = v * self.config.sl_mult * 100
        tp_pct = v * self.config.tp_mult * 100
        logger.info(
            "%s satellite: opening %s position at %.2f (vol=%.4f, sl=%.1f%%, tp=+%.1f%%)",
            self.name,
            side,
            entry_price,
            v,
            sl_pct,
            tp_pct,
        )
        self.position_active = True
        self.position_entry = entry_price
        self.position_side = side
        self.current_value = self.max_capital
        self.entry_price = entry_price
        self.stop_price = entry_price * (1.0 - v * self.config.sl_mult)
        self.target_price = entry_price * (1.0 + v * self.config.tp_mult)
        self._last_exit_reason = None

    def close_position(self, price: float | None = None, reason: str = "MANUAL") -> None:
        """Close the current position with optional exit price and reason."""
        if price is not None and self.entry_price is not None and self.entry_price > 0:
            pnl_pct = (price / self.entry_price - 1.0) * 100
            logger.info(
                "%s satellite: closed at %.2f, reason=%s, pnl=%.2f%%",
                self.name,
                price,
                reason,
                pnl_pct,
            )
        self.position_active = False
        self.position_entry = 0.0
        self.position_side = None
        self.entry_price = None
        self.stop_price = None
        self.target_price = None
        self._last_exit_reason = reason

    def check_exit(self, current_price: float) -> str | None:
        """Check if SL or TP is breached and close position if so.

        Returns the exit reason string (``"SL_HIT"`` or ``"TP_HIT"``) or ``None``.
        Must be called *after* ``record_return`` for the day.
        """
        if not self.position_active or self.stop_price is None or self.target_price is None:
            return None
        if current_price <= self.stop_price:
            logger.warning(
                "%s satellite: SL hit at %.2f (stop=%.2f)",
                self.name,
                current_price,
                self.stop_price,
            )
            self.close_position(price=current_price, reason="SL_HIT")
            return "SL_HIT"
        if current_price >= self.target_price:
            logger.info(
                "%s satellite: TP hit at %.2f (target=%.2f)",
                self.name,
                current_price,
                self.target_price,
            )
            self.close_position(price=current_price, reason="TP_HIT")
            return "TP_HIT"
        return None

    def deploy_capital(self, amount: float) -> None:
        """Allocate capital to the satellite (capped at max)."""
        capped = min(amount, self.max_capital)
        self.current_value = capped
        self.peak_value = capped
        self.initial_capital = capped

    @property
    def drawdown_pct(self) -> float:
        if self.peak_value <= 0:
            return 0.0
        return (self.current_value - self.peak_value) / self.peak_value

    # ── Marginal Contribution Monitoring ──────────────────────────

    def compute_rolling_sharpe(self, returns: list[float] | None = None) -> float:
        """Annualised Sharpe over the contribution_window."""
        r = returns if returns is not None else self._daily_returns
        window = self.config.contribution_window_days
        if len(r) < 20:
            return 0.0
        recent = r[-min(window, len(r)) :]
        mean_r = float(np.mean(recent))
        std_r = float(np.std(recent))
        if std_r < 1e-10:
            return 0.0
        return mean_r / std_r * math.sqrt(252)

    def check_marginal_contribution(
        self,
        core_returns: list[float],
    ) -> dict:
        """Evaluate rolling marginal contribution and return alert level.

        Returns:
            {
                'delta_sharpe': float,
                'alert_level': 'normal' | 'alert' | 'reduce',
                'recommended_allocation_cut_pct': float (0 = no cut),
            }
        """
        # Build combined return series (core + satellite)
        sat_returns = self._daily_returns[-len(core_returns) :] if len(core_returns) > 0 else []
        # Align lengths
        min_len = min(len(core_returns), len(sat_returns))
        if min_len < 20:
            return {"delta_sharpe": 0.0, "alert_level": "normal", "recommended_allocation_cut_pct": 0.0}

        core = core_returns[-min_len:]
        sat = sat_returns[-min_len:]

        # Portfolio weights: core = (1 - w_sat), satellite = w_sat
        w_sat = self.current_value / max(1.0, self.total_aum)
        w_core = 1.0 - w_sat

        # Combined daily returns
        combined = [w_core * c + w_sat * s for c, s in zip(core, sat)]

        delta = self.compute_delta_sharpe(port_core_returns=core, port_combined_returns=combined)

        alert = "normal"
        cut = 0.0
        if delta < self.config.delta_sharpe_reduce_threshold:
            alert = "reduce"
            # Linear cut: at delta = 2x threshold, cut to 0
            cut = min(1.0, abs(delta) / abs(self.config.delta_sharpe_reduce_threshold) * 0.5)
        elif delta < self.config.delta_sharpe_alert_threshold:
            alert = "alert"

        return {
            "delta_sharpe": round(delta, 4),
            "alert_level": alert,
            "recommended_allocation_cut_pct": round(cut * 100, 1),
        }

    def compute_delta_sharpe(
        self,
        port_core_returns: list[float] | np.ndarray,
        port_combined_returns: list[float] | np.ndarray,
    ) -> float:
        core_sharpe = self._compute_sharpe(port_core_returns)
        combined_sharpe = self._compute_sharpe(port_combined_returns)
        return combined_sharpe - core_sharpe

    def _compute_sharpe(self, returns: list[float] | np.ndarray) -> float:
        arr = np.asarray(returns, dtype=np.float64)
        if len(arr) < 20:
            return 0.0
        mean_r = float(np.mean(arr))
        std_r = float(np.std(arr))
        if std_r < 1e-10:
            return 0.0
        return mean_r / std_r * math.sqrt(252)

    # ── State reporting ────────────────────────────────────────────

    def get_state(self) -> SatelliteSnapshot:
        gate = self._last_gate
        total_return = (self.current_value / self.initial_capital - 1.0) * 100 if self.initial_capital > 0 else 0.0
        return SatelliteSnapshot(
            allocation_pct=round(self.current_value / max(1.0, self.total_aum) * 100, 2),
            gate_open=gate.allowed if gate else False,
            gate_reasons=gate.reasons_blocked if gate else ["gate never evaluated"],
            current_value=round(self.current_value, 2),
            total_return_pct=round(total_return, 2),
            sharpe_contribution=round(self.compute_rolling_sharpe(), 2),
            delta_sharpe_63d=0.0,  # computed externally with core context
            position_active=self.position_active,
            drawdown_pct=round(self.drawdown_pct * 100, 2),
            entry_price=self.entry_price,
            stop_price=self.stop_price,
            target_price=self.target_price,
            exit_reason=self._last_exit_reason,
        )
