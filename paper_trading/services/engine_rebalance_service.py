import logging
from datetime import datetime

import pandas as pd
import pytz

from paper_trading.config_manager import get_config
from paper_trading.ops.data_fetcher import fetch_live
from shared.portfolio_weights import WeightMethod, compute_weights

logger = logging.getLogger("eigencapital.engine_rebalance_service")

ET = pytz.timezone("US/Eastern")


class EngineRebalanceService:
    def __init__(self, engine):
        self.engine = engine

    def should_rebalance(self) -> bool:
        engine = self.engine
        today = datetime.now(tz=ET).date()
        today_dow = today.weekday()
        if today_dow != engine._rebalance_dow:
            return False
        if engine._rebalance_last_day == today:
            return False
        engine._rebalance_last_day = today
        return True

    def _collect_daily_returns(self, window: int = 252) -> pd.DataFrame:
        engine = self.engine
        price_data: dict[str, pd.Series] = {}
        for name, asset in engine.assets.items():
            px = asset.current_price
            if px is None or px <= 0:
                continue
            try:
                hist = fetch_live(asset.ticker, min_days=window + 60)
                if hist is not None and "close" in hist.columns and len(hist) >= window:
                    price_data[name] = hist["close"]
            except (OSError, ValueError, TypeError, KeyError):
                logger.warning("Failed to fetch history for %s", name, exc_info=True)
                continue
        if not price_data:
            return pd.DataFrame()
        df = pd.DataFrame(price_data)
        returns = df.pct_change().dropna()
        return returns.iloc[-window:] if len(returns) > window else returns

    def detect_crisis_regime(self) -> bool:
        for name, asset in self.engine.assets.items():
            state = getattr(asset.validity_sm, "current_state", None)
            if state is not None and "CRISIS" in str(state).upper():
                return True
        return False

    def rebalance_portfolio(self, method: WeightMethod | None = None) -> None:
        """Rebalance portfolio using canonical weight computation.

        Covariance is computed from RAW historical returns — no governance
        scaling, no regime adjustment. Governance affects per-position
        sizing at trade time, not the portfolio weight matrix.

        Parameters
        ----------
        method : WeightMethod, optional
            Weight strategy to use. Reads from config 'portfolio.weight_method'
            if not provided (default 'risk_parity_v1').
        """
        if method is None:
            method = get_config().portfolio.get("weight_method", "risk_parity_v1")
        engine = self.engine
        window = 252
        returns = self._collect_daily_returns(window)
        if returns.empty or len(returns.columns) < 2:
            logger.info("Risk parity skipped — insufficient price data")
            return

        total_value = engine._state.compute_mtm_total()

        # Read factor exposure limits from config (P3) for factor-constrained methods.
        # Falls back to DEFAULT_FACTOR_LIMITS if not configured.
        factor_limits = get_config().portfolio.get("factor_exposure_limits", None)
        kwargs = {}
        if factor_limits is not None:
            kwargs["factor_limits"] = factor_limits

        try:
            pw = compute_weights(method, returns, **kwargs)
        except (ValueError, TypeError, RuntimeError) as _rp_exc:
            logger.error("Risk parity optimization failed: %s", _rp_exc, exc_info=True)
            return

        engine._rebalance_weights = pw.weights

        for name, asset in engine.assets.items():
            target = total_value * pw.weights.get(name, 0.0)
            asset.set_capital_base(target)

        logger.info(
            "Risk parity rebalanced %d assets — weights: %s",
            len(engine.assets),
            {n: f"{w:.3f}" for n, w in pw.weights.items() if w > 0.01},
        )

    def write_weights_to_wal(self) -> None:
        engine = self.engine
        if not engine._rebalance_weights or engine._wal is None:
            return
        try:
            weight_method = get_config().defaults.get("weight_method", "risk_parity_v1") or "risk_parity_v1"
            engine._wal.write(
                "portfolio_weights",
                {
                    "timestamp": datetime.now(tz=ET).isoformat(),
                    "cycle": engine._cycle_count,
                    "method": weight_method,
                    "weights": {n: round(w, 4) for n, w in engine._rebalance_weights.items()},
                    "n_assets": len(engine._rebalance_weights),
                },
            )
        except (OSError, RuntimeError, KeyError):
            logger.exception("WAL write failed for portfolio_weights")
