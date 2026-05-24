import logging
import os
import pickle
from datetime import datetime

import numpy as np
import pandas as pd
import pytz
import xgboost as xgb

from features.builder import build_features, compute_macro_derived, model_path
from features.contract import validate_no_cross_asset_leakage
from features.regime_features import generate_regime_features
from features.registry import FEATURE_REGISTRY
from labels.meta_labels import MetaLabelModel
from monitoring.importance_tracker import ImportanceStore, StabilityResult
from monitoring.validity_state_machine import (
    ValidityStateMachine as _ValidityStateMachine,
)
from paper_trading import diagnostics as diag
from paper_trading import wrappers as _w
from paper_trading.config_manager import get_config
from paper_trading.data_fetcher import fetch_history, fetch_live, fetch_ref, flatten, safe_download
from paper_trading.decision import PositionIntent, TradeDecision
from paper_trading.drift_scoring import get_shadow_intelligence as _get_drift
from paper_trading.dynamic_sltp import build_dynamic_sltp_from_config
from paper_trading.position_manager import PositionManager
from paper_trading.regime_classifier import RegimeClassifier
from paper_trading.risk_governance import evaluate as _risk_evaluate
from paper_trading.risk_governance import record_trade_outcome as _record_exit_outcome
from paper_trading.scale_out import build_scale_out_from_config
from paper_trading.shadow_actions import compute_shadow_actions as _compute_shadow
from paper_trading.shadow_feedback import record_shadow_feedback as _record_feedback
from paper_trading.shadow_learning import compile_shadow_learning as _compile_learning
from paper_trading.shadow_memory import store_event as _shadow_store
from paper_trading.state_store import _SKIP_JOURNAL, StateStore
from paper_trading.tracer import (
    shadow_compare_pnl,
    shadow_compare_signal,
    shadow_compare_sizing,
    shadow_compare_sltp,
    trace_decision,
    trace_diagnostic_report,
)
from shared.registry import StrategyRegistry

logger = logging.getLogger("quantforge.asset_engine")

ET = pytz.timezone("US/Eastern")

BASE = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_STORE = StateStore(BASE)


class AssetEngine:
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

    def _build_features(self, df, ref, macro):
        return build_features(df, macro, ref, self.contract)

    def _sizing_config(self, close: pd.Series, position_size_scalar: float = 1.0) -> dict:
        cfg = dict(self.config)
        if self.execution_bridge is None:
            return cfg
        price = float(close.iloc[-1]) if len(close) else 0.0
        if price <= 0:
            return cfg
        notional = (
            self.current_value * self.pos_mgr.position_size * self.pos_mgr.exposure_multiplier * position_size_scalar
        )
        cfg["impact_bps"] = self.execution_bridge.estimate_impact_bps(self.ticker, notional)
        return cfg

    def _record_inference_proxies(self, proba: np.ndarray, X: pd.DataFrame, signal: str) -> None:
        """Store macro vs blend directions for adaptive weight feedback on trade close."""
        self._last_macro_dir = None
        self._last_blend_dir = None
        self._entry_signal_dir = 1 if signal == "BUY" else (-1 if signal == "SELL" else 0)

        macro_head = getattr(self.model, "macro_head", None) if self.model else None
        if macro_head is None or X.empty:
            return
        try:
            macro_cols = [c for c in macro_head.features if c in X.columns]
            if len(macro_cols) < 3:
                return
            macro_probs = macro_head.predict_proba(X.iloc[[-1]][macro_cols])[0]
            self._last_macro_dir = int(np.argmax(macro_probs)) - 1
            self._last_blend_dir = int(np.argmax(proba[-1])) - 1
        except Exception:
            pass

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
        sl_mult = self.sl_mult * geom.get("sl_mult", 1.0)
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
            notional = self.current_value * self.pos_mgr.position_size * self.pos_mgr.exposure_multiplier
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
        _record_exit_outcome(self.name, reason)

    def refresh_price(self):
        try:
            df = safe_download(self.ticker, period="5d", auto_adjust=True, progress=False)
            if not df.empty:
                df = flatten(df)
                close = float(df["close"].ffill().iloc[-1])
                self.current_price = None if pd.isna(close) else close
        except Exception:
            pass

    def train(self, force=False):
        if os.path.exists(self.model_path) and not force:
            with open(self.model_path, "rb") as f:
                self.model = pickle.load(f)
                self._trained = True
            self._enable_adaptive_macro()
            self._load_meta_label_model()
            return

        logger.info("%s: downloading history...", self.name)
        df = fetch_history(self.ticker)
        ref = fetch_ref("SPY")
        macro = compute_macro_derived(pd.read_parquet(os.path.join(BASE, "data/processed/macro_factors.parquet")))
        features = self._build_features(df, ref, macro)
        validate_no_cross_asset_leakage(features, self.contract, known_slugs=FEATURE_REGISTRY.keys())
        logger.info("%s: %d feature rows", self.name, len(features))

        end_date = features.index[-1]
        start_date = end_date - pd.DateOffset(years=self._retrain_window)
        train = features[features.index >= start_date]
        if len(train) < 200:
            train = features

        X = train[self.features]
        y = train["label"].astype(int)
        split = int(len(X) * 0.8)

        model = xgb.XGBClassifier(
            n_estimators=300,
            max_depth=2,
            learning_rate=0.02,
            objective="multi:softprob",
            num_class=3,
            random_state=42,
            n_jobs=1,
            tree_method="hist",
            verbosity=0,
        )
        model.fit(
            X.iloc[:split],
            y.iloc[:split],
            eval_set=[(X.iloc[split:], y.iloc[split:])],
            verbose=False,
        )
        self.model = model
        self._trained = True
        self._enable_adaptive_macro()
        with open(self.model_path, "wb") as f:
            pickle.dump(model, f)

        # Train meta-label model
        if self.config.get("meta_labeling", {}).get("enabled", False):
            self._meta_label_model = MetaLabelModel(
                threshold=self.config.get("meta_labeling", {}).get("threshold", 0.55),
            )
            try:
                primary_pred = model.predict_proba(X)
                full_train = train.copy()
                full_train["label"] = y
                self._meta_label_model.train(full_train, primary_pred, self.features, self.name)
            except Exception as e:
                logger.warning("%s: meta-label training failed: %s", self.name, e)

        # Log feature importances
        self._window_id_counter += 1
        self._current_window_train_start = start_date.strftime("%Y-%m-%d")
        self._current_window_train_end = end_date.strftime("%Y-%m-%d")
        window_id = f"w{self._window_id_counter}_{self._current_window_train_end}"
        try:
            self._importance_store.log_snapshot(
                asset=self.name,
                feature_names=self.features,
                importances=model.feature_importances_,
                window_id=window_id,
                train_start=self._current_window_train_start,
                train_end=self._current_window_train_end,
                model_type="xgboost",
            )
            stability = self._importance_store.compute_stability(self.name)
            if stability is not None:
                self._last_stability = stability
                logger.info(
                    "%s stability — jaccard=%.3f spearman=%.3f penalty=%.3f",
                    self.name,
                    stability.jaccard_top_10,
                    stability.spearman_rank_corr,
                    stability.penalty,
                )
        except Exception as e:
            logger.warning("%s: failed to log feature importances: %s", self.name, e)

    def generate_signal(self, threshold=0.45):
        return self._generate_and_apply(threshold)

    def _generate_and_apply(self, threshold=0.45):
        self._ensure_position_synced()
        if not self._trained:
            self.train()

        df = fetch_live(self.ticker)

        # Sync with latest price (same as dashboard) to ensure responsive SL/TP
        self.refresh_price()
        if self.current_price is not None:
            # Update the last row's close with the real-time price
            df.loc[df.index[-1], "close"] = self.current_price

        self.price_data = df
        df["close"] = df["close"].ffill()
        ref = fetch_ref("SPY")
        macro = self._feature_pipeline.macro_derived(
            pd.read_parquet(os.path.join(BASE, "data/processed/macro_factors.parquet"))
        )
        features_df = self._feature_pipeline.build(df, macro, ref, self.contract)
        validate_no_cross_asset_leakage(features_df, self.contract, known_slugs=FEATURE_REGISTRY.keys())

        X = features_df[self.features]
        if len(X) == 0:
            raise ValueError(f"No valid feature rows after building features for {self.name}")

        proba = self._model_iface.predict(self.model, X)
        if proba.shape[1] < 3:
            raise ValueError(f"Model returned {proba.shape[1]} classes, expected 3")

        # Meta-label inference
        self._last_meta_proba = None
        if self._meta_label_model is not None and self._meta_label_model._trained:
            try:
                self._last_meta_proba = self._meta_label_model.predict_proba(X, proba)
            except Exception as e:
                logger.debug("%s: meta-label inference failed: %s", self.name, e)

        sizing_cfg = self._sizing_config(df["close"])
        if self.config.get("regime_sizing"):
            regime_features_df = generate_regime_features(df)
            regime_results = self.regime_classifier.classify(regime_features_df)
            current_regime = regime_results["regime"].iloc[-1]
            self._current_regime = current_regime
            pos_size = self._sizing_strategy.compute(df["close"], sizing_cfg, regime=current_regime)
        else:
            self._current_regime = "neutral"
            pos_size = self._sizing_strategy.compute(df["close"], sizing_cfg)

        result = self._signal_strategy.compute(proba, X.index, threshold, df["close"], pos_size)

        self._record_inference_proxies(proba, X, result.signal_type)
        self.signal_data = result.signal_data

        latest = self.signal_data.iloc[-1]
        self.last_signal_date = latest.name

        decision = TradeDecision(
            asset=self.name,
            signal=result.signal_type,
            label=result.label,
            confidence=result.confidence_pct,
            prob_long=round(float(latest["prob_long"]), 4),
            prob_short=round(float(latest["prob_short"]), 4),
            prob_neutral=round(float(latest["prob_neutral"]), 4),
            close_price=round(float(latest["close"]), 4),
            timestamp=str(latest.name.date()),
            position_size=float(pos_size),
        )

        self._apply_decision(decision, df)

        trace_decision(
            asset=self.name,
            features={k: round(float(v), 6) for k, v in X.iloc[-1].items()},
            proba=[float(proba[-1, 0]), float(proba[-1, 1]), float(proba[-1, 2])],
            threshold=threshold,
            signal=decision.signal,
            confidence=decision.confidence,
            pos_size=float(pos_size),
            close_price=float(latest["close"]),
            current_side=self.pos_mgr.current_side(),
            halt_flags=self.check_halt_conditions(),
        )

        _shadow_signal_df = _w.compute_signals(proba, X.index, threshold)
        _shadow_latest = _shadow_signal_df.iloc[-1]
        _shadow_stype, _shadow_conf, _shadow_conf_pct = _w.signal_type_and_confidence(
            int(_shadow_latest["signal"]),
            float(_shadow_latest["prob_long"]),
            float(_shadow_latest["prob_short"]),
        )
        shadow_compare_signal(
            asset=self.name,
            proba_produced=[float(proba[-1, 0]), float(proba[-1, 1]), float(proba[-1, 2])],
            wrapper_signal=_shadow_stype,
            wrapper_confidence=_shadow_conf_pct,
            original_signal=decision.signal,
            original_confidence=decision.confidence,
        )

        _shadow_size = _w.compute_vol_scalar(df["close"]) if self.config.get("vol_scalar") else 1.0
        shadow_compare_sizing(
            asset=self.name,
            wrapper_size=_shadow_size,
            original_size=float(pos_size),
        )

        try:
            _proba_list = [float(proba[-1, 0]), float(proba[-1, 1]), float(proba[-1, 2])]
            _sig_div = diag.analyze_signal_divergence(
                _proba_list,
                threshold,
                decision.signal,
                decision.confidence,
                _shadow_stype,
                _shadow_conf_pct,
            )
            _mod_div = diag.analyze_model_distribution(self.name, _proba_list)
            _feat_drivers = diag.analyze_feature_impact(
                self.model,
                X.iloc[[-1]],
                self.features,
                proba[-1:],
            )
            _regime = diag.analyze_regime_context(df["close"])
            _report = diag.build_shadow_report(
                asset=self.name,
                timestamp=str(latest.name.date()),
                signal_match=_sig_div["match"],
                signal_divergence=_sig_div,
                model_divergence=_mod_div,
                feature_drivers=_feat_drivers,
                regime_context=_regime,
            )
            trace_diagnostic_report(_report)
            _shadow_store(self.name, _report)
            self._risk_signal = _risk_evaluate(self.name)
            self._shadow_drift_intel = _get_drift(self.name)
            self._shadow_action = _compute_shadow(
                asset=self.name,
                state=None,
                drift_report=self._shadow_drift_intel,
                risk_signal=self._risk_signal,
            )
            _record_feedback(
                asset=self.name,
                signal_data={"signal": decision.signal, "confidence": decision.confidence},
                drift=self._shadow_drift_intel,
                risk=self._risk_signal,
                action=self._shadow_action,
            )
            self._shadow_learning = _compile_learning(
                asset=self.name,
                feedback_logs=None,
                drift_history=self._shadow_drift_intel,
                risk_history=self._risk_signal,
            )
        except Exception:
            pass

        self._reg.validate_strategies(
            self.name,
            {
                "_model": self._model_iface,
                "_signal": self._signal_strategy,
                "_sizing": self._sizing_strategy,
                "_pnl": self._pnl_strategy,
                "_feature_pipeline": self._feature_pipeline,
            },
        )

        return self._decision_to_dict(decision)

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
        self._ensure_position_synced()

        # 1. Intraday SL/TP Check - ALWAYS run this on every refresh using real-time price
        max_hold = self.config.get("max_holding_days")
        if self.pos_mgr.has_position() and self.current_price is not None:
            # ── Scale-out tier check ─────────────────────────────
            if self._scale_out_plan is not None:
                so_fills = self._scale_out_engine.check_tiers(
                    self._scale_out_plan,
                    self.pos_mgr.position.side,
                    self.current_price,
                    self.current_value,
                    self.pos_mgr.position_size,
                    self.pos_mgr.exposure_multiplier,
                )
                for so in so_fills:
                    if so.get("fraction", 0) > 0:
                        self.pos_mgr.partial_close(
                            so["fraction"],
                            so["fill_price"],
                            str(datetime.now(tz=ET).date()),
                            so["reason"],
                        )
                    breakeven = so.get("breakeven_price")
                    if breakeven is not None:
                        self.pos_mgr.activate_breakeven_stop()
                    if so.get("reason") == "trailing_activated":
                        logger.info("%s: trailing activated by scale-out tier fill", self.name)

            hit = self.pos_mgr.check_sl_tp(self.current_price)
            if hit:
                last_bar = str(datetime.now(tz=ET).date())
                if self.signal_data is not None and len(self.signal_data) > 0:
                    last_bar = str(self.signal_data.index[-1].date())

                logger.info(
                    "%s: SL/TP HIT: %s at %s (Current: %s)", self.name, hit[0].upper(), hit[1], self.current_price
                )
                self._close_position(hit[1], last_bar, hit[0])
                if self.current_value > self.peak_value:
                    self.peak_value = self.current_value
                return

            # ── Trailing stop check ──────────────────────────────
            if self.config.get("dynamic_sltp", {}).get("enabled", False) and self._entry_vol is not None:
                data = getattr(self, "price_data", None) or (df if (df := getattr(self, "_price_df", None)) else None)
                if data is not None and self.pos_mgr.position is not None:
                    trailing = self._sltp_engine.compute_trailing_stop(
                        side=self.pos_mgr.position.side,
                        entry_price=self.pos_mgr.position.entry_price,
                        current_price=self.current_price,
                        initial_sl=self._initial_sl or self.pos_mgr.position.stop_loss,
                        current_sl=self.pos_mgr.position.stop_loss,
                        take_profit=self.pos_mgr.position.take_profit,
                        df=data,
                    )
                    if trailing.trailing_sl is not None:
                        self.pos_mgr.update_stop_loss(float(trailing.trailing_sl))
                        logger.info(
                            "%s: trailing stop activated to %.4f (locked profit=%.2f%%)",
                            self.name,
                            trailing.trailing_sl,
                            (trailing.locked_profit or 0) * 100,
                        )
                        shadow_compare_sltp(
                            self.name,
                            label_sl=self._initial_sl or self.pos_mgr.position.stop_loss,
                            label_tp=self.pos_mgr.position.take_profit,
                            runtime_sl=trailing.trailing_sl,
                            runtime_tp=self.pos_mgr.position.take_profit,
                            entry_price=self.pos_mgr.position.entry_price,
                            reason="trailing",
                        )

                    # ── Post-entry adjustment ────────────────────────
                    self._bars_at_entry += 1
                    adjust = self._sltp_engine.post_entry_adjust(
                        side=self.pos_mgr.position.side,
                        entry_price=self.pos_mgr.position.entry_price,
                        current_sl=self.pos_mgr.position.stop_loss,
                        current_tp=self.pos_mgr.position.take_profit,
                        df=data,
                        vol=self._entry_vol,
                        bars_since_entry=self._bars_at_entry,
                    )
                    if adjust.new_sl is not None:
                        self.pos_mgr.update_stop_loss(float(adjust.new_sl))
                        logger.info(
                            "%s: post-entry SL adjusted: %s (new=%.4f)",
                            self.name,
                            adjust.reason,
                            adjust.new_sl,
                        )
                        shadow_compare_sltp(
                            self.name,
                            label_sl=self._initial_sl or self.pos_mgr.position.stop_loss,
                            label_tp=self.pos_mgr.position.take_profit,
                            runtime_sl=adjust.new_sl,
                            runtime_tp=self.pos_mgr.position.take_profit,
                            entry_price=self.pos_mgr.position.entry_price,
                            reason=adjust.reason or "post_entry_sl",
                        )
                    if adjust.new_tp is not None:
                        self.pos_mgr.update_take_profit(float(adjust.new_tp))
                        logger.info(
                            "%s: post-entry TP adjusted: %s (new=%.4f)",
                            self.name,
                            adjust.reason,
                            adjust.new_tp,
                        )
                        shadow_compare_sltp(
                            self.name,
                            label_sl=self.pos_mgr.position.stop_loss,
                            label_tp=self._initial_tp or self.pos_mgr.position.take_profit,
                            runtime_sl=self.pos_mgr.position.stop_loss,
                            runtime_tp=adjust.new_tp,
                            entry_price=self.pos_mgr.position.entry_price,
                            reason=adjust.reason or "post_entry_tp",
                        )

            # Time stop check — force close if held beyond max_holding_days
            if max_hold is not None and self.pos_mgr.position is not None:
                entry_str = str(self.pos_mgr.position.entry_date)
                try:
                    entry_dt = pd.Timestamp(entry_str)
                    if entry_dt.tz is None:
                        entry_dt = entry_dt.tz_localize("US/Eastern")
                    elapsed = (datetime.now(tz=ET) - entry_dt).days
                    if elapsed >= max_hold:
                        last_bar = str(datetime.now(tz=ET).date())
                        logger.info("%s: TIME STOP after %d days (max=%d)", self.name, elapsed, max_hold)
                        self._close_position(self.current_price, last_bar, "time_stop")
                        return
                except Exception:
                    pass

        # 2. Daily P&L Settlement - Only run if signal_data is available (historical context)
        if self.signal_data is None or len(self.signal_data) < 2:
            return

        close = self.signal_data["close"]
        today_close = float(close.iloc[-1])
        last_bar = str(self.signal_data.index[-1].date())

        if self.trades and self.trades[-1]["date"] == last_bar:
            return
        # (Existing daily pnl logic continues...)
        sig = self.signal_data["signal"].iloc[-2]
        direction = 1 if sig == 2 else (-1 if sig == 0 else 0)
        pos_size = (
            float(self.signal_data["position_size"].iloc[-2]) if "position_size" in self.signal_data.columns else 1.0
        )
        prev_close = float(close.iloc[-2])
        ret = (
            (today_close / prev_close - 1)
            if len(close) >= 2 and prev_close != 0 and not pd.isna(today_close) and not pd.isna(prev_close)
            else 0
        )
        if pd.isna(ret) or np.isinf(ret):
            ret = 0
        pnl = self.pos_mgr.compute_daily_pnl(direction, ret, pos_size)
        _shadow_pnl = _w.compute_daily_pnl(
            self.pos_mgr.current_value,
            direction,
            ret,
            self.pos_mgr.position_size,
            pos_size,
        )
        shadow_compare_pnl(asset=self.name, wrapper_pnl=_shadow_pnl, original_pnl=pnl)
        try:
            _pnl_decomp = diag.analyze_pnl_decomposition(
                self.pos_mgr.current_value,
                direction,
                ret,
                self.pos_mgr.position_size,
                pos_size,
                pnl,
            )
            _regime = diag.analyze_regime_context(close)
            _report = diag.build_shadow_report(
                asset=self.name,
                timestamp=last_bar,
                signal_match=True,
                pnl_match=_pnl_decomp["match"],
                regime_context=_regime,
                pnl_decomposition=_pnl_decomp,
            )
            trace_diagnostic_report(_report)
            _shadow_store(self.name, _report)
        except Exception:
            pass
        self.pos_mgr.apply_pnl(pnl)
        self.current_value = self.pos_mgr.current_value
        self.peak_value = self.pos_mgr.peak_value
        if direction != 0:
            self.trades.append(
                {
                    "date": last_bar,
                    "direction": direction,
                    "return": float(ret),
                    "pnl": float(pnl),
                }
            )

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

        pnl_pct = (
            self._position_pnl(self.current_price) / 100
            if self.pos_mgr.has_position() and self.current_price is not None and not pd.isna(self.current_price)
            else 0
        )
        pos_size_config = get_config().position_size
        mtm_value = cv + cv * pnl_pct * pos_size_config
        mtm_return = (mtm_value - self.initial_capital) / self.initial_capital * 100 if self.initial_capital > 0 else 0

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

        return {
            "asset": self.name,
            "current_value": round(self.current_value, 2),
            "mtm_value": round(mtm_value, 2),
            "total_return": round(total_return * 100, 2),
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

        score = max(0.0, min(1.0, score))
        result = self.validity_sm.transition(score, pd.Timestamp.now())
        result["feature_stability"] = {
            "jaccard_top_10": self._last_stability.jaccard_top_10 if self._last_stability else None,
            "spearman_rank_corr": self._last_stability.spearman_rank_corr if self._last_stability else None,
            "penalty_applied": self._last_stability.penalty if self._last_stability else 0.0,
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
        prob_drift_limit = hc.get("prob_drift", 0.15)
        metrics = self.get_metrics()
        mean_conf = metrics.get("mean_confidence", 0) / 100
        if pd.isna(mean_conf):
            mean_conf = 0
        drift = abs(mean_conf - self.expected_prob_conf)
        if drift > prob_drift_limit:
            reasons.append(f"Confidence drift: {drift:.3f} > {prob_drift_limit:.2f}")
            drift_ok = False
        return {
            "halted": len(reasons) > 0,
            "reasons": reasons,
            "drawdown_ok": dd > hc["drawdown"],
            "monthly_pf_ok": mpf is None or pd.isna(mpf) or mpf >= hc["monthly_pf"],
            "drought_ok": drought_ok,
            "drift_ok": drift_ok,
        }
