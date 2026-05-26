import logging
import os
from datetime import datetime

import numpy as np
import pandas as pd
import pytz

from features.builder import build_features, model_path
from labels.meta_labels import MetaLabelModel
from monitoring.importance_tracker import ImportanceStore, StabilityResult
from monitoring.psi_monitor import PSIMonitor, PSISnapshot
from monitoring.validity_state_machine import (
    ValidityStateMachine as _ValidityStateMachine,
)
from paper_trading.asset_governance import AssetGovernance
from paper_trading.asset_inference_pipeline import AssetInferencePipeline
from paper_trading.asset_pnl_controller import AssetPnlController
from paper_trading.asset_training_pipeline import AssetTrainingPipeline
from paper_trading.config_manager import get_config
from paper_trading.data_fetcher import flatten, safe_download
from paper_trading.decision import PositionIntent, TradeDecision
from paper_trading.dynamic_sltp import build_dynamic_sltp_from_config
from paper_trading.position_manager import PositionManager
from paper_trading.regime_classifier import RegimeClassifier
from paper_trading.risk_governance import record_trade_outcome as _record_exit_outcome
from paper_trading.scale_out import build_scale_out_from_config
from paper_trading.state_store import _SKIP_JOURNAL, StateStore
from shared.registry import StrategyRegistry

logger = logging.getLogger("quantforge.asset_engine")

ET = pytz.timezone("US/Eastern")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STORE = StateStore(BASE)


class AssetEngine:
    _MIN_SIZE_SCALAR = 0.30

    def __init__(
        self,
        ticker,
        name,
        contract,
        allocation,
        halt_config=None,
        config=None,
        expected_prob_conf=0.45,
        state_store=None,
        journal_path=None,
        sl_mult=1.0,
        tp_mult=2.5,
        regime_geometry=None,
        initial_capital=None,
        position_size=None,
        retrain_window=None,
        execution_bridge=None,
    ):
        self.ticker = ticker
        self.name = name
        self.contract = contract
        self.features = list(contract.features)
        self.allocation = allocation
        engine_cfg = get_config()
        self.initial_capital = initial_capital if initial_capital is not None else engine_cfg.capital * allocation
        self.capital_base = self.initial_capital
        self.halt_config = halt_config or dict(engine_cfg.halt)
        self.config = config or {}
        self.expected_prob_conf = expected_prob_conf
        self.model = None
        self.signal_data = None
        self.peak_value = self.initial_capital
        self.current_value = self.initial_capital
        self.start_time = datetime.now(tz=ET)
        self.last_signal_date = None
        self.trades = []
        self.prob_history = []
        self.model_path = model_path(ticker)
        self._trained = False
        self.position = None
        self.trade_log = []
        self.current_price = None
        self.pos_mgr = PositionManager(
            self.initial_capital,
            position_size if position_size is not None else engine_cfg.position_size,
        )
        self.validity_sm = _ValidityStateMachine()
        self._reg = StrategyRegistry.get_instance()
        self._model_iface = self._reg.get_model(self.name)
        self._signal_strategy = self._reg.get_signal(self.name)
        self._sizing_strategy = self._reg.get_sizing(self.name)
        self._pnl_strategy = self._reg.get_pnl(self.name)
        self._feature_pipeline = self._reg.get_features(self.name)
        self._risk_signal = None
        self._shadow_action = None
        self._shadow_drift_intel = None
        self._shadow_learning = None
        self.sl_mult = sl_mult
        self.tp_mult = tp_mult
        self.regime_geometry = regime_geometry or {}
        self.execution_bridge = execution_bridge
        self._research_mode = engine_cfg.research_mode
        self._last_macro_dir: int | None = None
        self._last_blend_dir: int | None = None
        self._entry_signal_dir: int = 0
        self._retrain_window = retrain_window if retrain_window is not None else engine_cfg.retrain_window
        if state_store is not None:
            self.state_store = state_store
        elif journal_path is _SKIP_JOURNAL:
            self.state_store = None
        else:
            self.state_store = _STORE
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        self._importance_store = ImportanceStore(base_dir)
        self._psi_monitor = PSIMonitor(base_dir)
        self.regime_classifier = RegimeClassifier()
        if self.config.get("regime_sizing"):
            self._sizing_strategy.regime_aware = True

        self._sltp_engine = build_dynamic_sltp_from_config(self.config)
        self._scale_out_engine = build_scale_out_from_config(self.config)
        self._scale_out_plan = None
        self._last_adjust_bar = 0
        self._bars_at_entry = 0
        self._entry_vol = None
        self._meta_label_model = None
        self._window_id_counter = 0
        self._current_window_train_start = ""
        self._current_window_train_end = ""
        self._last_stability: StabilityResult | None = None
        self._last_psi_drift: PSISnapshot | None = None
        self.governance = AssetGovernance(self.name, self.config, self.halt_config)
        self.governance.load_narrative_state()
        self.governance.load_liquidity_state(getattr(self, "price_data", None))
        self._last_stop_out_side: str | None = None
        self._last_stop_out_date: pd.Timestamp | None = None
        self._last_stop_out_price: float | None = None
        self._entry_price: float | None = None
        self._regime_adjusted_entry: bool = False
        self._churn_ratio_threshold = self.config.get("churn_ratio_threshold", 0.50)
        self._initial_settlement_done: bool = False
        self._training = AssetTrainingPipeline(self)
        self._pnl = AssetPnlController(self)
        self._inference = AssetInferencePipeline(self)

    def set_narrative_state(self, narr) -> None:
        self.governance.set_narrative_state(narr)

    def _refresh_liquidity(self, df) -> None:
        self.governance.refresh_liquidity(df)

    def _build_features(self, df, ref, macro):
        return build_features(df, macro, ref, self.contract)

    def _effective_capital(self) -> float:
        if self.initial_capital <= 0:
            return self.capital_base
        growth = self.current_value / self.initial_capital
        return self.capital_base * growth

    def _composite_size_scalar(self, extra_scalar: float = 1.0) -> float:
        return (
            self.pos_mgr.position_size
            * self.pos_mgr.exposure_multiplier
            * extra_scalar
            * max(self.governance._narrative_size_scalar * self.governance._liquidity_size_scalar, self._MIN_SIZE_SCALAR)
        )

    def _compute_notional(self, extra_scalar: float = 1.0) -> float:
        return self._effective_capital() * self._composite_size_scalar(extra_scalar)

    def _sizing_config(self, close: pd.Series, position_size_scalar: float = 1.0) -> dict:
        cfg = dict(self.config)
        if self.execution_bridge is None:
            return cfg
        price = float(close.iloc[-1]) if len(close) else 0.0
        if price <= 0:
            return cfg
        notional = self._compute_notional(position_size_scalar)
        cfg["impact_bps"] = self.execution_bridge.estimate_impact_bps(self.ticker, notional)
        return cfg

    def _macro_blend_trade_returns(self, trade_ret: float) -> tuple[float, float]:
        """Attribute trade PnL to macro-only vs blended heads by directional agreement."""
        entry = self._entry_signal_dir
        if entry == 0:
            return trade_ret, trade_ret
        macro_dir = self._last_macro_dir
        blend_dir = self._last_blend_dir
        macro_ret = trade_ret if macro_dir is None or macro_dir == entry else -trade_ret
        blend_ret = trade_ret if blend_dir is None or blend_dir == entry else -trade_ret
        return macro_ret, blend_ret

    def _enable_adaptive_macro(self) -> None:
        if not self.config.get("adaptive_macro") or self.model is None:
            return
        macro_head = getattr(self.model, "macro_head", None)
        if macro_head is not None:
            macro_head.online_weight = True

    def _load_meta_label_model(self) -> None:
        if not self.config.get("meta_labeling", {}).get("enabled", False):
            return
        try:
            model = MetaLabelModel(
                threshold=self.config.get("meta_labeling", {}).get("threshold", 0.55),
            )
            model._load(model._model_path(self.name))
            if model._trained:
                self._meta_label_model = model
                logger.info("%s: meta-label model loaded from cache", self.name)
        except Exception as e:
            logger.debug("%s: no cached meta-label model: %s", self.name, e)

    def _tb_vol(self, df):
        returns = np.log(df["close"] / df["close"].shift(1))
        vol = returns.ewm(span=100).std()
        return vol.iloc[-1] if not pd.isna(vol.iloc[-1]) else 0.01

    def _open_position(self, side, entry_price, entry_date, df=None):
        data = df if df is not None else self.price_data
        vol = self._tb_vol(data)
        if pd.isna(vol) or pd.isna(entry_price) or entry_price == 0:
            logger.error("%s: invalid entry_price=%s or vol=%s", self.name, entry_price, vol)
            return

        # Regime-conditional geometry selection (multipliers on base sl_mult/tp_mult)
        state = self.validity_sm.current_state.value if self.validity_sm else "YELLOW"
        geom = self.regime_geometry.get(state, {"sl_mult": 1.0, "tp_mult": 1.0})
        sl_mult = self.sl_mult * geom.get("sl_mult", 1.0) * self.governance._narrative_sl_mult * self.governance._liquidity_sl_mult
        tp_mult = self.tp_mult * geom.get("tp_mult", 1.0)

        if self.regime_geometry and geom.get("sl_mult", 1.0) != 1.0:
            logger.info(
                "%s: regime-adjusted geometry for %s: sl=%.2f (base %.2f × %.2f), tp=%.2f (base %.2f × %.2f)",
                self.name,
                state,
                sl_mult,
                self.sl_mult,
                geom.get("sl_mult", 1.0),
                tp_mult,
                self.tp_mult,
                geom.get("tp_mult", 1.0),
            )

        fill_price = entry_price
        if self.execution_bridge is not None:
            broker_side = "buy" if side == "long" else "sell"
            notional = self._compute_notional()
            qty = max(notional / entry_price, 1e-6)
            fill_price, _, _ = self.execution_bridge.fill_price(self.ticker, broker_side, qty, entry_price)

        # Use DynamicSLTPEngine if configured, else fall back to original EWM vol method
        if self.config.get("dynamic_sltp", {}).get("enabled", False):
            regime = getattr(self, "_current_regime", "neutral")
            sltp_result = self._sltp_engine.compute_barriers(
                entry_price=fill_price,
                side=side,
                df=data,
                sl_mult=sl_mult,
                tp_mult=tp_mult,
                regime=regime,
                vol=vol,
                meta_confidence=self._last_meta_proba,
            )
            intent = PositionIntent(
                side=side,
                entry_price=fill_price,
                entry_date=entry_date,
                stop_loss=sltp_result.stop_loss,
                take_profit=sltp_result.take_profit,
                vol=vol,
            )
        else:
            intent = PositionIntent.from_price_and_vol(side, fill_price, entry_date, vol, sl_mult, tp_mult)

        self.pos_mgr.open(intent)
        self.position = {
            "side": intent.side,
            "entry": intent.entry_price,
            "sl": intent.stop_loss,
            "tp": intent.take_profit,
            "entry_date": intent.entry_date,
            "vol": intent.vol,
            "sl_mult": sl_mult,
            "tp_mult": tp_mult,
        }
        self._entry_vol = vol
        self._bars_at_entry = 0
        self._initial_sl = (
            float(sltp_result.stop_loss) if self.config.get("dynamic_sltp", {}).get("enabled", False) else None
        )
        self._initial_tp = (
            float(sltp_result.take_profit) if self.config.get("dynamic_sltp", {}).get("enabled", False) else None
        )
        if self._initial_sl is not None:
            self._sltp_engine.reset_best_price(fill_price)
        self._entry_price = intent.entry_price
        self._regime_adjusted_entry = geom.get("sl_mult", 1.0) < 1.0
        self._scale_out_plan = None
        if self._scale_out_engine is not None and intent.take_profit is not None:
            self._scale_out_plan = self._scale_out_engine.build_plan(
                side,
                float(intent.entry_price),
                float(intent.take_profit),
            )

    def _close_position(self, exit_price, exit_date, reason):
        fill_price = exit_price
        if self.execution_bridge is not None and self.pos_mgr.has_position():
            side = self.pos_mgr.position.side
            broker_side = "sell" if side == "long" else "buy"
            notional = self.current_value * self.pos_mgr.position_size * self.pos_mgr.exposure_multiplier
            qty = max(notional / exit_price, 1e-6)
            fill_price, _, _ = self.execution_bridge.fill_price(self.ticker, broker_side, qty, exit_price)

        trade = self.pos_mgr.close(fill_price, exit_date, reason)
        if trade is None:
            return
        trade["asset"] = self.name
        trade["conf_at_entry"] = self.position.get("confidence") if self.position else None

        try:
            macro_head = getattr(self.model, "macro_head", None) if self.model else None
            if macro_head is not None and macro_head.online_weight:
                trade_ret = float(trade.get("return", 0.0))
                macro_ret, blend_ret = self._macro_blend_trade_returns(trade_ret)
                macro_head.update_weight(macro_ret, blend_ret)
        except Exception:
            pass

        self.position = None
        self.current_value = self.pos_mgr.current_value
        self.trade_log = list(self.pos_mgr.trade_log)
        self._save_trade_journal(trade)
        if self.state_store is not None:
            self.state_store.write_trade_outcomes_cache()
        _record_exit_outcome(self.name, reason)

    def _record_stop_out(self, side: str, exit_price: float) -> None:
        if self.pos_mgr.position is not None:
            self._last_stop_out_price = self.pos_mgr.position.stop_loss
        else:
            self._last_stop_out_price = None

        if self._regime_adjusted_entry and self._last_stop_out_price is not None and self._entry_price is not None:
            sl_distance = abs(self._last_stop_out_price - self._entry_price)
            price_beyond_sl = abs(exit_price - self._last_stop_out_price)
            if sl_distance > 0 and (price_beyond_sl / sl_distance) < self._churn_ratio_threshold:
                return

        self._last_stop_out_side = side
        self._last_stop_out_date = pd.Timestamp.now(tz="UTC").normalize()

    def _recently_stopped_out(self, side: str) -> bool:
        if self._last_stop_out_side != side:
            return False
        if self._last_stop_out_date is None:
            return False
        today = pd.Timestamp.now(tz="UTC").normalize()
        return self._last_stop_out_date >= today

    def refresh_price(self):
        # 1. Try absolute real-time price first
        from paper_trading.data_fetcher import fetch_realtime_price

        lp = fetch_realtime_price(self.ticker)
        if lp is not None:
            self.current_price = lp
            return

        # 2. Fallback to 5d download
        try:
            df = safe_download(self.ticker, period="5d", auto_adjust=True, progress=False)
            if not df.empty:
                df = flatten(df)
                close = float(df["close"].ffill().iloc[-1])
                self.current_price = None if pd.isna(close) else close
        except Exception:
            pass

    def train(self, force=False):
        self._training.train(force=force)

    def generate_signal(self, threshold=0.45):
        return self._inference.generate_signal(threshold)

    def _apply_decision(self, decision: TradeDecision, df):
        today = decision.timestamp
        current_side = self.pos_mgr.current_side()
        new_side = "long" if decision.signal == "BUY" else ("short" if decision.signal == "SELL" else None)

        # Minimum confidence gate — skip low-confidence entries
        min_conf = self.config.get("min_confidence", 0.0)
        if new_side and decision.confidence < min_conf:
            logger.debug("%s: skipping trade, confidence %.1f%% < min %.1f%%", self.name, decision.confidence, min_conf)
            new_side = None

        # Meta-label filter — skip trades unlikely to hit TP before SL
        if (
            new_side
            and self._meta_label_model is not None
            and self.config.get("meta_labeling", {}).get("enabled", False)
            and hasattr(self, "_last_meta_proba")
            and not self._meta_label_model.should_enter(self._last_meta_proba)
        ):
            logger.info(
                "%s: meta-label blocking trade (p(TP>SL)=%.2f < threshold=%.2f)",
                self.name,
                self._last_meta_proba,
                self._meta_label_model.threshold,
            )
            new_side = None

        if new_side != current_side:
            if self.pos_mgr.has_position():
                self._close_position(decision.close_price, today, "signal_flip")
            if new_side:
                if self._recently_stopped_out(new_side):
                    logger.debug(
                        "%s: skipping %s entry — stopped out same direction today",
                        self.name,
                        new_side,
                    )
                else:
                    self._open_position(new_side, decision.close_price, today, df)
                    if self.position is not None:
                        self.position["confidence"] = decision.confidence

        self.prob_history.append(
            {
                "date": today,
                "prob_long": round(decision.prob_long * 100, 2),
                "prob_short": round(decision.prob_short * 100, 2),
                "signal": decision.signal,
                "confidence": decision.confidence,
                "close_price": decision.close_price,
            }
        )
        MAX_PROB_HISTORY = 1000
        if len(self.prob_history) > MAX_PROB_HISTORY:
            self.prob_history = self.prob_history[-MAX_PROB_HISTORY:]
        self._log_confidence_buckets()

    def _decision_to_dict(self, decision: TradeDecision):
        pos = self.pos_mgr.position
        macro_weight = None
        macro_head = getattr(self.model, "macro_head", None) if self.model else None
        if macro_head is not None:
            macro_weight = round(float(getattr(macro_head, "current_weight", 0.45)), 4)

        return {
            "asset": self.name,
            "signal": decision.signal,
            "confidence": decision.confidence,
            "macro_weight": macro_weight,
            "close_price": decision.close_price,
            "date": decision.timestamp,
            "label": decision.label,
            "position": (
                {
                    "side": pos.side if pos else None,
                    "entry": round(pos.entry_price, 4) if pos else None,
                    "sl": round(pos.stop_loss, 4) if pos else None,
                    "tp": round(pos.take_profit, 4) if pos else None,
                    "current_pnl": (round(self._position_pnl(decision.close_price), 4) if pos else None),
                }
                if pos
                else None
            ),
        }

    def _position_pnl(self, current_price):
        return self.pos_mgr.position_pnl(current_price)

    def _ensure_position_synced(self):
        if self.position is not None and not self.pos_mgr.has_position():
            intent = PositionIntent(
                side=self.position["side"],
                entry_price=self.position["entry"],
                entry_date=self.position.get("entry_date", ""),
                stop_loss=self.position["sl"],
                take_profit=self.position["tp"],
                vol=self.position.get("vol", 0.01),
            )
            self.pos_mgr.open(intent)

    def update_pnl(self):
        self._pnl.update_pnl()

    @property
    def mtm_value(self) -> float:
        return self._pnl.mtm_value

    def get_metrics(self):
        self._ensure_position_synced()
        cv = self.current_value if not pd.isna(self.current_value) else self.initial_capital
        pv = self.peak_value if not pd.isna(self.peak_value) else cv
        dd = (cv - pv) / pv if pv > 0 else 0
        total_return = (cv - self.initial_capital) / self.initial_capital if self.initial_capital > 0 else 0

        monthly_pfs = []
        if self.trade_log:
            td = pd.DataFrame(self.trade_log)
            td["month"] = pd.to_datetime(td["exit_date"]).dt.to_period("M")
            for m, g in td.groupby("month"):
                profits = g[g["pnl"] > 0]["pnl"].sum()
                losses = abs(g[g["pnl"] < 0]["pnl"].sum())
                monthly_pfs.append({"month": str(m), "pf": profits / losses if losses > 0 else float("inf")})
        monthly_pf = monthly_pfs[-1]["pf"] if monthly_pfs else None

        total_profits = sum(t["pnl"] for t in self.trade_log if t["pnl"] > 0)
        total_losses = abs(sum(t["pnl"] for t in self.trade_log if t["pnl"] < 0))
        pf = total_profits / total_losses if total_losses > 0 else (float("inf") if total_profits > 0 else 0)

        win_rate = len([t for t in self.trade_log if t["pnl"] > 0]) / len(self.trade_log) if self.trade_log else 0
        sc = {"BUY": 0, "SELL": 0, "FLAT": 0}
        for p in self.prob_history:
            sc[p["signal"]] = sc.get(p["signal"], 0) + 1
        mean_conf = np.mean([p["confidence"] for p in self.prob_history]) if self.prob_history else 0
        mean_conf = 0 if pd.isna(mean_conf) else mean_conf

        pos_info = None
        if self.pos_mgr.has_position():
            upnl = (
                self._position_pnl(self.current_price)
                if self.current_price is not None and not pd.isna(self.current_price)
                else 0.0
            )
            pos_info = {
                "side": self.pos_mgr.position.side,
                "entry": round(self.pos_mgr.position.entry_price, 4),
                "sl": round(self.pos_mgr.position.stop_loss, 4),
                "tp": round(self.pos_mgr.position.take_profit, 4),
                "current_vol": round(self.pos_mgr.position.vol, 6),
                "unrealized_pnl": round(upnl, 2),
                "sl_mult": self.position.get("sl_mult") if self.position else None,
                "tp_mult": self.position.get("tp_mult") if self.position else None,
            }

        mtm_val = self.mtm_value
        mtm_return = (mtm_val - self.initial_capital) / self.initial_capital * 100 if self.initial_capital > 0 else 0

        mean_pl = np.mean([p["prob_long"] for p in self.prob_history]) if self.prob_history else 0
        mean_pl = 0 if pd.isna(mean_pl) else mean_pl
        mean_ps = np.mean([p["prob_short"] for p in self.prob_history]) if self.prob_history else 0
        mean_ps = 0 if pd.isna(mean_ps) else mean_ps

        # Exit reason rates from trade_log (paper trading)
        exit_reasons = {}
        if self.trade_log:
            reasons = [t.get("reason", "unknown") for t in self.trade_log]
            n = len(reasons)
            exit_reasons = {
                "tp_rate": round(reasons.count("tp") / n, 4),
                "sl_rate": round(reasons.count("sl") / n, 4),
                "signal_flip_rate": round(reasons.count("signal_flip") / n, 4),
                "avg_r": round(np.mean([t.get("realized_r", 0) for t in self.trade_log]), 4),
            }

        # Current regime-based geometry (multipliers applied to base)
        state = self.validity_sm.current_state.value if self.validity_sm else "YELLOW"
        geom = self.regime_geometry.get(state, {"sl_mult": 1.0, "tp_mult": 1.0})
        current_sl = self.sl_mult * geom.get("sl_mult", 1.0)
        current_tp = self.tp_mult * geom.get("tp_mult", 1.0)

        meta_inference = None
        if self._meta_label_model is not None and self._last_meta_proba is not None:
            meta_inference = {
                "meta_confidence": round(self._last_meta_proba, 4),
                "meta_decision": "ENTER" if self._meta_label_model.should_enter(self._last_meta_proba) else "BLOCK",
            }

        remaining_frac = self.pos_mgr.get_remaining_fraction()
        scale_out_active = (
            self.pos_mgr._scale_out_active
            if hasattr(self.pos_mgr, "_scale_out_active") and self.pos_mgr._scale_out_active
            else False
        )

        # Scale-out tier info for dashboard
        scale_out_tiers = None
        if self._scale_out_plan is not None:
            scale_out_tiers = [
                {
                    "fraction": t.fraction,
                    "price": t.price,
                    "filled": t.filled,
                    "fill_price": t.fill_price,
                }
                for t in self._scale_out_plan.tiers
            ]

        _psi = self._last_psi_drift
        return {
            "asset": self.name,
            "current_value": round(mtm_val, 2),
            "settled_value": round(self.current_value, 2),
            "mtm_value": round(mtm_val, 2),
            "total_return": round(mtm_return, 2),
            "settled_return": round(total_return * 100, 2),
            "mtm_return": round(mtm_return, 2),
            "drawdown": round(dd * 100, 2),
            "profit_factor": round(pf, 2),
            "win_rate": round(win_rate * 100, 2),
            "n_trades": len(self.trade_log),
            "n_signals": len(self.prob_history),
            "signal_distribution": sc,
            "mean_confidence": round(float(mean_conf), 2),
            "mean_prob_long": round(float(mean_pl), 2),
            "mean_prob_short": round(float(mean_ps), 2),
            "current_price": round(self.current_price, 4) if self.current_price else None,
            "last_signal_date": str(self.last_signal_date.date()) if self.last_signal_date else None,
            "monthly_pf": round(float(monthly_pf), 2) if monthly_pf else None,
            "position": pos_info,
            "current_sl_mult": round(current_sl, 4),
            "current_tp_mult": round(current_tp, 4),
            "trade_log": self.trade_log[-10:],
            "feature_stability": {
                "jaccard_top_10": self._last_stability.jaccard_top_10 if self._last_stability else None,
                "spearman_rank_corr": self._last_stability.spearman_rank_corr if self._last_stability else None,
                "penalty": self._last_stability.penalty if self._last_stability else 0.0,
                "window_id": self._last_stability.window_id if self._last_stability else None,
            },
            "exit_reasons": exit_reasons,
            "meta_inference": meta_inference,
            "scale_out_active": scale_out_active,
            "remaining_fraction": round(remaining_frac, 4),
            "scale_out_tiers": scale_out_tiers,
            "psi_drift": {
                "per_feature": [
                    {
                        "feature": e.feature,
                        "psi": e.psi,
                        "classification": e.classification,
                        "trend": e.trend,
                        "importance_score": e.importance_score,
                    }
                    for e in (_psi.per_feature if _psi else [])
                ],
                "worst_classification": _psi.worst_classification if _psi else "NO_DRIFT",
                "moderate_count": _psi.moderate_count if _psi else 0,
                "severe_count": _psi.severe_count if _psi else 0,
                "psi_ok": _psi.psi_ok if _psi else True,
                "penalty": _psi.penalty if _psi else 0.0,
            },
        }

    def _save_trade_journal(self, trade):
        if self.state_store is not None:
            self.state_store.append_trade(trade)

    def _log_confidence_buckets(self):
        bucket = {"asset": self.name, "date": str(datetime.now(tz=ET).date())}
        for p in self.prob_history[-20:]:
            conf = p["confidence"]
            bucket.setdefault(f"count_{int(conf / 10) * 10}_{int(conf / 10 + 1) * 10}", 0)
            bucket[f"count_{int(conf / 10) * 10}_{int(conf / 10 + 1) * 10}"] += 1
        bucket["mean_conf"] = np.mean([p["confidence"] for p in self.prob_history[-20:]]) if self.prob_history else 0
        bucket["n_signals"] = min(20, len(self.prob_history))
        if self.state_store is not None:
            self.state_store.append_confidence_bucket(bucket)

    def update_validity(self):
        halt = self.check_halt_conditions()
        score = 0.80
        if not halt["drawdown_ok"]:
            score -= 0.25
        if not halt["monthly_pf_ok"]:
            score -= 0.20
        if not halt["drought_ok"]:
            score -= 0.15
        if not halt["drift_ok"]:
            score -= 0.15
        if not halt.get("narrative_ok", True):
            score -= 0.10
        if not halt.get("liquidity_ok", True):
            score -= 0.10

        if self._last_stability is not None:
            penalty = self._last_stability.penalty
            if penalty < 0:
                logger.info(
                    "%s stability penalty: %.3f (jaccard=%.3f, spearman=%.3f)",
                    self.name,
                    penalty,
                    self._last_stability.jaccard_top_10,
                    self._last_stability.spearman_rank_corr,
                )
                score += penalty

        if self._last_psi_drift is not None and self._last_psi_drift.penalty < 0:
            psi_p = self._last_psi_drift.penalty
            logger.info(
                "%s PSI drift penalty: %.3f (worst=%s, moderate=%d, severe=%d)",
                self.name,
                psi_p,
                self._last_psi_drift.worst_classification,
                self._last_psi_drift.moderate_count,
                self._last_psi_drift.severe_count,
            )
            score += psi_p

        score = max(0.0, min(1.0, score))
        result = self.validity_sm.transition(score, pd.Timestamp.now())
        result["feature_stability"] = {
            "jaccard_top_10": self._last_stability.jaccard_top_10 if self._last_stability else None,
            "spearman_rank_corr": self._last_stability.spearman_rank_corr if self._last_stability else None,
            "penalty_applied": self._last_stability.penalty if self._last_stability else 0.0,
        }
        result["psi_drift"] = {
            "worst_classification": self._last_psi_drift.worst_classification if self._last_psi_drift else "NO_DRIFT",
            "moderate_count": self._last_psi_drift.moderate_count if self._last_psi_drift else 0,
            "severe_count": self._last_psi_drift.severe_count if self._last_psi_drift else 0,
            "penalty_applied": self._last_psi_drift.penalty if self._last_psi_drift else 0.0,
        }
        return result

    def check_halt_conditions(self):
        metrics = self.get_metrics()
        dd = metrics.get("drawdown", 0) / 100
        if pd.isna(dd):
            dd = 0
        hc = self.halt_config
        reasons = []
        if dd <= hc["drawdown"]:
            reasons.append(f"DD {metrics['drawdown']:.1f}% <= {hc['drawdown'] * 100:.0f}%")
        mpf = metrics.get("monthly_pf")
        if mpf is not None and not pd.isna(mpf) and mpf < hc["monthly_pf"]:
            reasons.append(f"PF {mpf:.2f} < {hc['monthly_pf']:.2f}")
        drought_ok = True
        drought_days = hc.get("signal_drought", 30)
        if self.last_signal_date is not None:
            days_since = (datetime.now(tz=ET).date() - pd.Timestamp(self.last_signal_date).date()).days
            if days_since > drought_days:
                reasons.append(f"Signal drought: {days_since}d > {drought_days}d")
                drought_ok = False
        drift_ok = True
        if len(self.prob_history) < 3:
            pass  # not enough signals to measure drift — skip
        prob_drift_limit = hc.get("prob_drift", 0.25)
        metrics = self.get_metrics()
        mean_conf = metrics.get("mean_confidence", 0) / 100
        if pd.isna(mean_conf):
            mean_conf = 0
        drift = abs(mean_conf - self.expected_prob_conf)
        if drift > prob_drift_limit:
            reasons.append(f"Confidence drift: {drift:.3f} > {prob_drift_limit:.2f}")
            drift_ok = False

        narrative_ok = True
        narr_warnings = self.governance.narrative_warnings()
        if narr_warnings:
            reasons.extend(narr_warnings)

        liquidity_ok = True
        liq_warnings = self.governance.liquidity_warnings()
        if liq_warnings:
            reasons.extend(liq_warnings)
            if self.governance._liquidity_halted:
                liquidity_ok = False

        psi_ok = True
        if self._last_psi_drift is not None and not self._last_psi_drift.psi_ok:
            reasons.append(
                f"PSI drift SEVERE on {self._last_psi_drift.severe_count} features "
                f"(worst={self._last_psi_drift.worst_classification})"
            )
            psi_ok = False

        return {
            "halted": len(reasons) > 0,
            "reasons": reasons,
            "drawdown_ok": dd > hc["drawdown"],
            "monthly_pf_ok": mpf is None or pd.isna(mpf) or mpf >= hc["monthly_pf"],
            "drought_ok": drought_ok,
            "drift_ok": drift_ok,
            "narrative_ok": narrative_ok,
            "liquidity_ok": liquidity_ok,
            "psi_ok": psi_ok,
        }

    def set_capital_base(self, new_base: float) -> None:
        self._pnl.set_capital_base(new_base)
